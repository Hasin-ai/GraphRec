"""Snapshot data, train a DGSR model, review it and put it into service.

export GRAPHREC_ADMIN_EMAIL=owner@acme.example GRAPHREC_ADMIN_PASSWORD=...
python examples/train_and_deploy.py
"""

from __future__ import annotations

import contextlib
import os

from graphrec_sdk import GraphRec, StateConflictError

MIN_NDCG = 0.5


def main() -> None:
    with GraphRec(
        email=os.environ["GRAPHREC_ADMIN_EMAIL"], password=os.environ["GRAPHREC_ADMIN_PASSWORD"]
    ) as admin:
        snapshot = admin.datasets.create_snapshot()
        print(
            f"snapshot {snapshot.id}: {snapshot.event_count} events, "
            f"{snapshot.product_count} products, {snapshot.user_count} users"
        )

        job = admin.training_jobs.create(
            dataset_snapshot_id=snapshot.id,
            configuration={"batch_size": 256, "learning_rate": 0.001, "gnn_layers": 2},
        )
        job = admin.training_jobs.wait(job.id, timeout=1800, poll_interval=10)
        if not job.succeeded or job.model_version_id is None:
            raise SystemExit(f"training {job.status}: {job.failure_reason}")

        candidate = admin.model_versions.get(job.model_version_id)
        previous = admin.model_versions.get_active()
        print(f"candidate {candidate.version_tag}: {candidate.metrics or 'no offline metrics'}")
        ndcg = candidate.metrics.get("ndcg_at_10")
        if ndcg is not None and float(ndcg) < MIN_NDCG:
            raise SystemExit(f"ndcg@10 {float(ndcg):.3f} below threshold - not activating")
        if ndcg is None:
            # The current training slice indexes placeholder embeddings and reports no metrics.
            print("warning: no ndcg_at_10 reported; activating without a quality gate")

        admin.model_versions.activate(candidate.id)
        status = admin.deployment.get()
        print(f"deployment {status.status}, ready replicas {status.ready_replicas}")

        metrics = admin.metrics.summary()
        if previous is not None and metrics.error_rate > 0.05:
            print("error rate too high, rolling back")
            admin.model_versions.rollback(previous.id)

        for version in admin.model_versions.list():
            if version.status == "retired":
                with contextlib.suppress(StateConflictError):
                    admin.model_versions.archive(version.id)


if __name__ == "__main__":
    main()
