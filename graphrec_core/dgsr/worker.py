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
        if time.monotonic() - started > 180:
            raise ValueError('Local training exceeded its 180-second processing budget; use a smaller snapshot or import a prepared checkpoint.')
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
    size = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, tenant_id)
        job = db.scalar(select(TrainingJob).where(TrainingJob.id == job_id).with_for_update())
        if job.cancel_requested:
            raise Cancelled()
        now, version_id = datetime.now(timezone.utc), uuid4()
        require_capacity(db, tenant_id, 'artifact_storage_bytes', size)
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
        cancelled = isinstance(exc, Cancelled)
        if not cancelled:
            logger.exception('Training job %s failed', job_id)
        with SessionLocal() as db, db.begin():
            set_local_tenant(db, tenant_id)
            job = db.get(TrainingJob, job_id)
            job.status = job.stage = 'cancelled' if cancelled else 'failed'
            job.failure_reason = None if cancelled else f'{type(exc).__name__}: {str(exc)[:500]}'
            job.completed_at = datetime.now(timezone.utc)
            ModelRegistryService(db)._audit(tenant_id, f'training_{job.status}', job_id,
                outcome='succeeded' if cancelled else 'failed', details={'reason': type(exc).__name__})
    return True


def main():
    logging.basicConfig(level=logging.INFO)
    # One local CPU trainer across worker processes; Postgres releases the lock
    # automatically if its process or database connection dies.
    with engine.connect() as guard:
        if not guard.scalar(text('SELECT pg_try_advisory_lock(714629381)')):
            raise RuntimeError('A training worker already owns local CPU capacity.')
        guard.commit()
        while True:
            try:
                guard.execute(text('SELECT 1'))
                guard.commit()
                if not run_once():
                    time.sleep(2)
            except Exception:
                logger.exception('Worker polling failed; retrying in five seconds')
                time.sleep(5)


if __name__ == '__main__':
    main()
