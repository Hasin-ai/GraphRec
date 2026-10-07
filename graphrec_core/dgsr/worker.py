"""Single-capacity CPU worker for the durable tenant training queue.

The demonstration deliberately bounds data, epochs and elapsed training time.
Large supplied datasets use the separately verified checkpoint import path.
"""
from __future__ import annotations

import copy
import csv
import json
import logging
import math
import shutil
import signal
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import numpy as np
import torch
from sqlalchemy import select, text

from graphrec_core.database.models import DatasetSnapshot, DatasetSnapshotContent, ModelVersion, TrainingJob, UsageEvent
from graphrec_core.database.session import SessionLocal, engine
from graphrec_core.database.tenancy import set_local_tenant
from graphrec_core.dgsr.config import Config
from graphrec_core.dgsr.data import InteractionData
from graphrec_core.dgsr.graph import TemporalGraph, TemporalSampler, collate_graphs
from graphrec_core.dgsr.model import DGSR, training_loss
from graphrec_core.dgsr.serving import DGSRArtifact
from graphrec_core.models_reg.service import ModelRegistryService
from graphrec_core.settings import get_settings
from graphrec_core.usage.limits import require_capacity
from graphrec_core.vector_store.client import get_qdrant_client
from graphrec_core.vector_store.collections import collection_name, delete_collection
from graphrec_core.vector_store.indexer import index_item_embeddings

logger = logging.getLogger(__name__)


class Cancelled(Exception):
    pass


#: Local CPU worker cap per job, whatever the plan allows.
LOCAL_TRAINING_BUDGET_SECONDS = 180


def training_budget_seconds(plan_minutes) -> int:  # noqa: ANN001
    """D-11: the smaller of the plan's ``maximum_training_duration_minutes`` and the
    local worker cap. A missing plan value falls back to the local cap."""
    if plan_minutes is None:
        return LOCAL_TRAINING_BUDGET_SECONDS
    return max(1, min(LOCAL_TRAINING_BUDGET_SECONDS, int(plan_minutes) * 60))


class ShuttingDown(Exception):
    """The worker received SIGTERM/SIGINT: hand the job back to the queue."""


#: Set by the signal handler; checked at every progress pulse.
STOP = threading.Event()

#: ER-NF-05 (A-21): failures worth one more attempt. Everything else (invalid or
#: insufficient data, non-finite training, exceeded budgets) is deterministic and
#: fails the job immediately with its reason.
MAX_ATTEMPTS = 2


def is_transient(exc: BaseException) -> bool:
    from sqlalchemy.exc import DBAPIError, OperationalError
    if isinstance(exc, (OperationalError, ConnectionError, TimeoutError)):
        return True
    if isinstance(exc, DBAPIError) and exc.connection_invalidated:
        return True
    try:  # Qdrant over gRPC or HTTP
        import grpc
        if isinstance(exc, grpc.RpcError):
            return True
    except ImportError:  # pragma: no cover
        pass
    try:
        from qdrant_client.http.exceptions import ResponseHandlingException
        if isinstance(exc, ResponseHandlingException):
            return True
    except ImportError:  # pragma: no cover
        pass
    return False


def progress(tenant_id, job_id, stage, percent):
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tenant_id)
        job = db.get(TrainingJob, job_id)
        if job.cancel_requested:
            raise Cancelled()
        job.stage, job.progress, job.heartbeat_at = stage, max(job.progress, percent), datetime.now(timezone.utc)


def train_job(tenant_id, job_id):
    started = time.monotonic()
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tenant_id)
        job = db.get(TrainingJob, job_id)
        snapshot = db.get(DatasetSnapshot, job.dataset_snapshot_id)
        content = db.get(DatasetSnapshotContent, job.dataset_snapshot_id).content
        configuration = dict(job.configuration)
        snapshot_checksum = snapshot.checksum
        from graphrec_core.capacity import effective_limits
        plan_minutes = effective_limits(db, tenant_id).get('maximum_training_duration_minutes')
    # D-11: the plan's maximum training duration, capped by this worker's local budget.
    budget = training_budget_seconds(plan_minutes)
    cfg = Config(embedding_dim=16, layers=1, recent_items=10, sampling_order=1,
                 item_neighbor_limit=10, epochs=configuration['epochs'], batch_size=16,
                 torch_threads=1, device='cpu', seed=42, evaluation='full')
    cfg.validate()
    torch.set_num_threads(1)
    torch.manual_seed(cfg.seed)
    rng = np.random.default_rng(cfg.seed)
    directory = Path(get_settings().generated_model_root) / str(tenant_id) / str(job_id)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / 'training.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['user_id', 'item_id', 'time'])
        for event in content['events']:
            if event['user_id'] and event['external_product_id']:
                writer.writerow([event['user_id'], event['external_product_id'],
                    int(datetime.fromisoformat(event['occurred_at']).timestamp())])
    data = InteractionData.from_csv(directory / 'training.csv', cfg)
    data.make_splits(cfg)
    data.require_training_examples()
    if not data.examples['validation'] or not data.examples['test'] or data.num_items < 2:
        raise ValueError('Held-out validation and test examples and at least two distinct items are required.')
    data.save(directory)
    (directory / 'config.json').write_text(json.dumps(cfg.to_dict()), encoding='utf-8')
    model = DGSR(data.num_users, data.num_items, data.position_capacity(cfg), cfg)
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg.learning_rate)
    samplers = {split: TemporalSampler(TemporalGraph(data, data.allowed_events(split, cfg)), cfg)
                for split in ('train', 'validation', 'test')}

    def pulse(stage, percent):
        if STOP.is_set():
            raise ShuttingDown()
        if time.monotonic() - started > budget:
            raise ValueError(f'Training exceeded its {budget}-second processing budget (plan limit or local worker cap); '
                             'use a smaller snapshot or import a prepared checkpoint.')
        progress(tenant_id, job_id, stage, percent)

    def evaluate(split, baseline=False):
        model.eval()
        ranks, recommended = [], set()
        categories = {p['external_id']: p.get('category') for p in content['products']}
        diversities = []
        popular = np.bincount(data.items[data.roles == 0], minlength=data.num_items).astype(float)
        for index, example in enumerate(data.examples[split]):
            if index % 20 == 0:
                pulse(f'evaluating_{split}', 85 if split == 'test' else 70)
            if baseline:
                scores = popular.copy()
            else:
                batch, _ = collate_graphs([(samplers[split].sample(example.user, example.cutoff), example)])
                with torch.no_grad():
                    scores = model(batch)[0].numpy().copy()
            if not np.isfinite(scores).all():
                raise ValueError('Training produced non-finite prediction scores.')
            seen = data.excluded_items(example, 'prefix') - {example.target}
            scores[list(seen)] = -np.inf
            order = np.argsort(-scores, kind='stable')
            rank = int(np.flatnonzero(order == example.target)[0]) + 1
            ranks.append(rank)
            top = [int(i) for i in order[:10] if np.isfinite(scores[i])]
            recommended.update(top)
            labels = [categories.get(data.item_ids[i]) for i in top]
            labels = [v for v in labels if v]
            if len(labels) >= 2:
                diversities.append(sum(a != b for i, a in enumerate(labels) for b in labels[i + 1:]) / (len(labels) * (len(labels) - 1) / 2))
        result = {'examples': len(ranks), 'Hit@1': float(np.mean([r == 1 for r in ranks])),
                  'Hit@10': float(np.mean([r <= 10 for r in ranks])),
                  'Recall@10': float(np.mean([r <= 10 for r in ranks])),
                  'NDCG@10': float(np.mean([1 / math.log2(r + 1) if r <= 10 else 0 for r in ranks])),
                  'MRR@10': float(np.mean([1 / r if r <= 10 else 0 for r in ranks])),
                  'catalog_coverage@10': len(recommended) / data.num_items}
        if diversities:
            result['category_diversity@10'] = float(np.mean(diversities))
        return result

    best, best_score, best_epoch = None, -1.0, 0
    for epoch in range(cfg.epochs):
        model.train()
        order = rng.permutation(len(data.examples['train']))
        for offset in range(0, len(order), cfg.batch_size):
            pulse('training', min(65, 5 + int(60 * (epoch + offset / len(order)) / cfg.epochs)))
            examples = [data.examples['train'][int(i)] for i in order[offset:offset + cfg.batch_size]]
            batch, _ = collate_graphs([(samplers['train'].sample(e.user, e.cutoff), e) for e in examples])
            optimizer.zero_grad()
            loss, _ = training_loss(model, model(batch), torch.tensor([e.target for e in examples]))
            if not torch.isfinite(loss):
                raise ValueError('Training produced a non-finite loss.')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
            optimizer.step()
        validation = evaluate('validation')
        if validation['NDCG@10'] > best_score:
            best_score, best, best_epoch = validation['NDCG@10'], copy.deepcopy(model.state_dict()), epoch + 1
    model.load_state_dict(best)
    metrics = {'validation': evaluate('validation'), 'test': evaluate('test'),
               'popularity_baseline': evaluate('test', baseline=True),
               'evaluation_protocol': 'Full catalog; chronological leave-two-out; observed prefix excluded except repeated target.',
               'training': {'epochs_completed': cfg.epochs, 'selected_epoch': best_epoch, 'events': len(data.users)}}
    torch.save({'engine_version': 'graphrec-cpu-v1', 'config': cfg.to_dict(),
        'data_fingerprint': data.fingerprint(), 'num_users': data.num_users, 'num_items': data.num_items,
        'position_capacity': data.position_capacity(cfg), 'model': best, 'epoch': best_epoch,
        'selection_ndcg10': best_score}, directory / 'best.pt')
    (directory / 'final_metrics.json').write_text(json.dumps(metrics, allow_nan=False), encoding='utf-8')
    (directory / 'tenant_identity.json').write_text(json.dumps({'tenant_id': str(tenant_id),
        'snapshot_id': str(snapshot.id), 'snapshot_checksum': snapshot_checksum}), encoding='utf-8')
    pulse('validating_artifact', 95)
    artifact = DGSRArtifact(directory)
    artifact.encode_known(0)
    pulse('comparing_versions', 97)
    metrics['comparison'] = compare_with_active(tenant_id, artifact, data, directory)
    (directory / 'final_metrics.json').write_text(json.dumps(metrics, allow_nan=False), encoding='utf-8')
    size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tenant_id)
        job = db.scalar(select(TrainingJob).where(TrainingJob.id == job_id).with_for_update())
        if job.cancel_requested:
            raise Cancelled()
        now, version_id = datetime.now(timezone.utc), uuid4()
        require_capacity(db, tenant_id, 'artifact_storage_bytes', size)
        require_capacity(db, tenant_id, 'active_model_versions')
        table = artifact.item_embeddings()
        norms = np.linalg.norm(table, axis=1, keepdims=True)
        if not np.isfinite(table).all() or np.any(norms <= 0):
            raise ValueError('The trained item table cannot be indexed.')
        try:
            indexed = index_item_embeddings(
                client=get_qdrant_client(), tenant_id=tenant_id, version_id=version_id,
                external_ids=artifact.item_ids, embedding_matrix=table / norms,
            )
            if indexed != len(artifact.item_ids):
                raise ValueError('The item index is incomplete.')
        except Exception:
            try:
                delete_collection(get_qdrant_client(), collection_name(tenant_id, version_id))
            except Exception:
                logger.warning('Could not clean up an incomplete item index for %s', version_id)
            raise
        source = {**artifact.describe(), 'tenant_id': str(tenant_id), 'snapshot_checksum': snapshot_checksum,
                  'artifact_bytes': size, 'indexed_items': indexed}
        version = ModelVersion(id=version_id, tenant_id=tenant_id, version_tag=f'trained-{job_id.hex[:12]}',
            model_type='dgsr', status='eligible', metrics={**metrics, 'source': source},
            artifact_uri=f'file://{directory.resolve().as_posix()}', created_at=now)
        db.add(version)
        job.status, job.stage, job.progress = 'succeeded', 'completed', 100
        job.model_version_id, job.completed_at = version_id, now
        for dimension, quantity in [('training_cpu_seconds', time.monotonic() - started), ('artifact_storage_bytes', size)]:
            db.add(UsageEvent(id=uuid4(), tenant_id=tenant_id, usage_type=dimension, quantity=Decimal(str(quantity)),
                source_id=str(job_id), idempotency_key=f'{dimension}-{job_id}', occurred_at=now))
        ModelRegistryService(db)._audit(tenant_id, 'training_completed', job_id, details={'model_version_id': str(version_id), 'mode': 'train'})


def compare_with_active(tenant_id, candidate: DGSRArtifact, data: InteractionData, directory: Path) -> dict:
    """XR-F-10: score the candidate, the tenant's active DGSR version and a popularity
    baseline on the candidate's held-out test examples (``common_evaluation.json``)."""
    from graphrec_core.dgsr.evaluation import common_set_from_split, compare
    from graphrec_core.dgsr.serving import load_artifact
    from graphrec_core.models_reg.service import DGSR_MODEL_TYPE, artifact_directory, validate_artifact_binding
    examples = common_set_from_split(data, data.examples['test'])
    (directory / 'common_evaluation.json').write_text(json.dumps({'examples': [e.as_dict() for e in examples]}), encoding='utf-8')
    train_items = [data.item_ids[int(i)] for i in data.items[data.roles == 0]]
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tenant_id)
        active = db.scalar(select(ModelVersion).where(ModelVersion.tenant_id == tenant_id, ModelVersion.status == 'active',
                                                      ModelVersion.model_type == DGSR_MODEL_TYPE))
        active_id, active_uri = (str(active.id), active.artifact_uri) if active else (None, None)
    active_artifact, reason = None, None
    if active_id:
        try:
            path = artifact_directory(active_uri)
            if path is None:
                raise ValueError('artifact directory not found')
            validate_artifact_binding(path, tenant_id)
            active_artifact = load_artifact(path)
        except Exception as exc:  # the comparison is reported as unavailable, never invented
            reason = f'{type(exc).__name__}: {str(exc)[:200]}'
            logger.warning('Active version %s could not be loaded for comparison: %s', active_id, reason)
    result = compare(candidate, examples, train_items, active_artifact, active_id)
    if active_id and active_artifact is None:
        result['active'] = {'model_version_id': active_id, 'unavailable_reason': reason}
    return result


def run_once():
    with SessionLocal() as db:
        row = db.execute(text('SELECT * FROM public.claim_training_job()')).first()
        db.commit()
    if row is None:
        return False
    job_id, tenant_id = row
    try:
        train_job(tenant_id, job_id)
    except Exception as exc:
        finish_failed_job(tenant_id, job_id, exc)
    return True


def _job_directory(tenant_id, job_id) -> Path:
    return Path(get_settings().generated_model_root) / str(tenant_id) / str(job_id)


def finish_failed_job(tenant_id, job_id, exc: BaseException) -> str:
    """Record the outcome of a job that did not succeed; returns its new status.

    * cancelled  - the tenant asked for it.
    * queued     - the worker is shutting down, or a transient failure with
                   attempts left: the job is handed back and retried once.
    * failed     - a deterministic failure, or a transient one with no attempts left.
    The partial artifact directory is removed in every case.
    """
    cancelled = isinstance(exc, Cancelled)
    shutting_down = isinstance(exc, ShuttingDown)
    transient = not cancelled and not shutting_down and is_transient(exc)
    if not (cancelled or shutting_down):
        logger.error('Training job %s failed (%s)', job_id, 'transient' if transient else 'deterministic',
                     exc_info=exc)
    shutil.rmtree(_job_directory(tenant_id, job_id), ignore_errors=True)
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tenant_id)
        job = db.get(TrainingJob, job_id)
        if shutting_down:
            # Not the job's fault: give the attempt back.
            job.status, job.stage, job.attempts = 'queued', 'requeued_on_shutdown', max(0, job.attempts - 1)
            job.heartbeat_at = None
            ModelRegistryService(db)._audit(tenant_id, 'training_requeued', job_id, outcome='succeeded',
                                            details={'reason': 'worker_shutdown'})
            return 'queued'
        if transient and job.attempts < MAX_ATTEMPTS:
            job.status, job.stage, job.failure_reason, job.heartbeat_at = 'queued', 'retry_scheduled', None, None
            ModelRegistryService(db)._audit(tenant_id, 'training_retry_scheduled', job_id, outcome='failed',
                                            details={'reason': type(exc).__name__, 'attempt': job.attempts})
            return 'queued'
        job.status = job.stage = 'cancelled' if cancelled else 'failed'
        if cancelled:
            job.failure_reason = None
        else:
            kind = 'transient failure, retry budget exhausted' if transient else 'deterministic failure'
            job.failure_reason = f'{type(exc).__name__}: {str(exc)[:450]} ({kind})'
        job.completed_at = datetime.now(timezone.utc)
        ModelRegistryService(db)._audit(tenant_id, f'training_{job.status}', job_id,
            outcome='succeeded' if cancelled else 'failed',
            details={'reason': type(exc).__name__, 'transient': transient})
        return job.status


def _install_signal_handlers() -> None:
    def stop(signum, _frame):  # noqa: ANN001
        logger.warning('Received signal %s: finishing at the next checkpoint and requeueing the job', signum)
        STOP.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)


def main():
    logging.basicConfig(level=logging.INFO)
    _install_signal_handlers()
    # One local CPU trainer across worker processes; Postgres releases the lock
    # automatically if its process or database connection dies.
    with engine.connect() as guard:
        if not guard.scalar(text('SELECT pg_try_advisory_lock(714629381)')):
            raise RuntimeError('A training worker already owns local CPU capacity.')
        guard.commit()
        while not STOP.is_set():
            try:
                guard.execute(text('SELECT 1'))
                guard.commit()
                if not run_once():
                    STOP.wait(2)
            except Exception:
                logger.exception('Worker polling failed; retrying in five seconds')
                STOP.wait(5)
        logger.info('Training worker stopped')


if __name__ == '__main__':
    main()
