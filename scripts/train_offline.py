"""Train DGSR on the synthetic fixture and print the comparison table.

Phase 8 is specified as offline-first: BUILD_PROMPT says to run this "before
wiring it to jobs and storage", and the reason is that a model wired into a job
queue fails in two ways at once. This script is the whole pipeline with nothing
around it — build features, split, train, evaluate, compare against popularity —
so the modelling can be judged on its own.

    python scripts/train_offline.py
    python scripts/train_offline.py --epochs 30 --seed 7 --checkpoint /tmp/dgsr.safetensors

The exit status is the criterion: `0` when the model beats the popularity
baseline on both Recall@10 and NDCG@10, `1` when it does not. That makes the
script usable as a gate rather than as something a human reads and interprets.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from graphrec.ml.eval.baseline import evaluate_popularity
from graphrec.ml.eval.evaluate import evaluate_model
from graphrec.ml.eval.split import leave_last_out
from graphrec.ml.features.builder import FeatureBuilder
from graphrec.ml.fixtures import synthetic
from graphrec.ml.graph.build import build_graph
from graphrec.ml.train.loop import TrainingConfig, train

if TYPE_CHECKING:
    from graphrec.ml.eval.metrics import Metrics
    from graphrec.ml.eval.split import Split
    from graphrec.ml.features.builder import Dataset
    from graphrec.ml.graph.build import InteractionGraph


def main(argv: list[str] | None = None) -> int:
    # An instance, not the class: `TrainingConfig` uses `slots=True`, so
    # `TrainingConfig.seed` is a descriptor rather than the default value and
    # argparse would hand it straight to `torch.manual_seed`.
    defaults = TrainingConfig()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    parser.add_argument("--epochs", type=int, default=defaults.epochs)
    parser.add_argument("--users", type=int, default=160)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s",
    )

    tenant = synthetic.generate(n_users=args.users)
    builder = FeatureBuilder()
    dataset = builder.build(tenant.interactions, tenant.products)
    split = leave_last_out(dataset)

    # Asserted here and not only in the tests. A leakage bug that reaches a
    # training run produces a metric that looks like success, and the cost of
    # checking is one pass over the training rows.
    split.assert_no_leakage()

    graph = build_graph(split.train)
    _report_corpus(dataset, split, graph)

    config = TrainingConfig(seed=args.seed, epochs=args.epochs)
    result = train(
        split,
        builder,
        config=config,
        checkpoint_path=args.checkpoint,
        resume=args.resume,
        on_epoch=lambda report: print(
            f"  epoch {report.epoch:>3}  loss {report.loss:.4f}"
            + (
                f"  val NDCG@10 {report.validation.ndcg:.4f}"
                if report.validation is not None
                else ""
            )
            + f"  {report.seconds:.1f}s"
        ),
    )

    model_metrics = evaluate_model(result.model, graph, builder, split.train, split.test)
    baseline_metrics = evaluate_popularity(split.train, split.test)

    _report_metrics(baseline_metrics, model_metrics, result.best_epoch)

    if not model_metrics.beats(baseline_metrics):
        print("\nFAIL — the model does not beat popularity on both Recall@10 and NDCG@10.")
        return 1
    print("\nPASS — the model beats the popularity baseline.")
    return 0


def _report_corpus(dataset: Dataset, split: Split, graph: InteractionGraph) -> None:
    print(
        f"corpus   {dataset.n_users} users, {dataset.n_items} items, "
        f"{dataset.n_interactions} interactions\n"
        f"split    {split.train.n_interactions} train, "
        f"{len(split.validation)} validation, {len(split.test)} test\n"
        f"graph    {graph.n_edges} edges, {graph.isolated_items().size} isolated items\n"
    )


def _report_metrics(baseline: Metrics, model: Metrics, best_epoch: int) -> None:
    print(f"\nbest epoch {best_epoch}, {model.n_users} test users\n")
    header = f"{'metric':<14}{'popularity':>12}{'DGSR':>12}{'delta':>12}"
    print(header)
    print("-" * len(header))
    for name in ("recall", "hit_rate", "ndcg", "coverage"):
        left = getattr(baseline, name)
        right = getattr(model, name)
        print(f"{name:<14}{left:>12.4f}{right:>12.4f}{right - left:>+12.4f}")


if __name__ == "__main__":
    sys.exit(main())
