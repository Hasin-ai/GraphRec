"""What `training_worker` can run: training, and nothing else.

A worker's claim filter is derived from its registry (`HandlerRegistry.job_types`),
so registering one type here is what keeps a training process from leasing an
ingestion batch — and, more importantly, what keeps an ingestion process from
leasing a training job and holding it for four hours behind a queue of CSV
uploads. The split is the point; see `apps/job_worker/registry.py` for the other
half of it.

The handler is built here rather than imported ready-made because it needs a
store and a minimum, and both come from settings. `HandlerRegistry.register`
takes a callable, so a bound method of a configured `TrainingPipeline` is a
handler in exactly the way a module-level function is.
"""

from __future__ import annotations

from graphrec.common.config import get_settings
from graphrec.domain.training.pipeline import TrainingPipeline
from graphrec.jobs.handlers import HandlerRegistry
from graphrec.jobs.states import JobType
from graphrec.storage.factory import create_artifact_store


def build_registry() -> HandlerRegistry:
    """A registry with one handler, wired to the configured store.

    A function rather than a module-level constant, because a module-level
    constant would open a boto3 client at import time — which makes the module
    unimportable in a test that has no MinIO, and makes `--help` require an
    object store.
    """
    settings = get_settings()
    pipeline = TrainingPipeline(
        create_artifact_store(settings),
        min_sequences=settings.training_min_sequences,
    )
    registry = HandlerRegistry()
    registry.register(JobType.TRAINING)(pipeline.run)
    return registry


__all__ = ["build_registry"]
