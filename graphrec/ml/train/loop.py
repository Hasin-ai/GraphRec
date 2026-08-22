"""The training loop: examples, batches, steps, epochs, checkpoints.

Deliberately a plain loop rather than a framework. Phase 9 wraps this in a
worker that has to report a stage index and a progress percentage after every
epoch, resume from a checkpoint after a crash, and stop promptly when a tenant
cancels — and every one of those is easier to write against a loop we own than
to extract from a callback system.

The unit of training is an **example**, not a user: for a user with a sequence
of *n* items there are *n-1* examples, one per position, each predicting the
item at that position from the prefix before it. That is what makes a single
epoch over a small tenant's data worth running at all, and it is also why the
prefix is built by slicing the sequence rather than by re-querying: the slice is
by construction strictly earlier in time than its target, so an example cannot
leak into itself.

Two things the loop is careful about:

* **Determinism.** One seeded `numpy.random.Generator` drives shuffling,
  neighbour sampling and negative sampling; `torch.manual_seed` covers
  initialisation and dropout. Both are checkpointed. A run repeated with the
  same seed produces the same metrics, which BUILD_PROMPT requires and which is
  the only way to tell a real improvement from a lucky one.
* **Early stopping on validation, never on training loss.** A recommender
  overfits by memorising the training interactions it is scored on, and a
  training curve that keeps improving while validation NDCG falls is the normal
  case rather than the pathological one.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import torch

from graphrec.ml.eval.evaluate import evaluate_model, pad_sequences
from graphrec.ml.graph.build import InteractionGraph, build_graph
from graphrec.ml.graph.sample import DEFAULT_FANOUTS, sample_two_hop
from graphrec.ml.model.dgsr import DGSR, DGSRConfig
from graphrec.ml.model.loss import bpr_loss, l2_penalty
from graphrec.ml.train.checkpoint import (
    TrainingState,
    load_checkpoint,
    restore_generator,
    save_checkpoint,
)
from graphrec.ml.train.negatives import NegativePolicy, NegativeSampler

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from graphrec.ml.eval.metrics import Metrics
    from graphrec.ml.eval.split import Split
    from graphrec.ml.features.builder import Dataset, FeatureBuilder

logger = logging.getLogger("graphrec.ml.train")


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    """Loop hyper-parameters. Model shape lives in `DGSRConfig`."""

    epochs: int = 20
    batch_size: int = 256
    learning_rate: float = 3e-3
    #: Negatives per positive. More is a better gradient and a linear cost.
    n_negatives: int = 8
    l2: float = 1e-5
    fanouts: tuple[int, int] = DEFAULT_FANOUTS
    negative_policy: NegativePolicy = NegativePolicy.POPULARITY
    #: Epochs without a validation improvement before stopping. `0` disables.
    patience: int = 5
    seed: int = 1337
    #: Cut-off for the validation metric that drives early stopping.
    k: int = 10


@dataclass(slots=True)
class EpochReport:
    """One row of the training curve — what Phase 9 writes to `training_metrics`."""

    epoch: int
    loss: float
    validation: Metrics | None
    seconds: float


@dataclass(slots=True)
class TrainingResult:
    model: DGSR
    history: list[EpochReport] = field(default_factory=list)
    best_epoch: int = 0
    best_metric: float = 0.0
    stopped_early: bool = False


@dataclass(frozen=True, slots=True)
class Example:
    """One (prefix → target) pair, flattened out of a user's sequence."""

    user: int
    position: int
    target: int
    weight: float


def build_examples(split: Split) -> list[Example]:
    """Every predictable position in every training sequence.

    Position 0 is skipped: predicting a user's first interaction from an empty
    prefix is the popularity prior, and training on it teaches the model to
    output the popularity prior for everyone.
    """
    examples: list[Example] = []
    for user, sequence in enumerate(split.train.sequences):
        for position in range(1, len(sequence)):
            examples.append(
                Example(
                    user=user,
                    position=position,
                    target=sequence[position],
                    weight=abs(split.train.weights[user][position]),
                )
            )
    return examples


def train(
    split: Split,
    builder: FeatureBuilder,
    *,
    config: TrainingConfig | None = None,
    model_config: DGSRConfig | None = None,
    checkpoint_path: Path | None = None,
    resume: bool = False,
    on_epoch: Callable[[EpochReport], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> TrainingResult:
    """Train on the split's training view and return the best model seen.

    `on_epoch` and `should_stop` are the two seams Phase 9 needs and the only
    ones: the worker reports progress through the first and honours a
    cancellation through the second. Neither is used here, which is how it stays
    true that the offline run and the worker's run are the same code path.
    """
    config = config or TrainingConfig()
    torch.manual_seed(config.seed)
    rng = np.random.default_rng(config.seed)

    dataset = split.train
    model_config = model_config or DGSRConfig.for_dataset(
        dataset, max_sequence_length=builder.max_sequence_length
    )
    model = DGSR(model_config)
    model.load_catalogue(dataset)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)

    graph = build_graph(dataset)
    sampler = NegativeSampler(
        dataset.n_items,
        dataset.item_popularity(),
        policy=config.negative_policy,
    )
    examples = build_examples(split)

    start_epoch = 0
    result = TrainingResult(model=model)
    best_state: dict[str, torch.Tensor] = {
        name: value.detach().clone() for name, value in model.state_dict().items()
    }

    if resume and checkpoint_path is not None and checkpoint_path.exists():
        state, _ = load_checkpoint(checkpoint_path, model, optimizer)
        restore_generator(rng, state)
        start_epoch = state.epoch
        result.best_metric = state.best_metric
        logger.info("training_resumed", extra={"epoch": start_epoch})

    stale = 0
    for epoch in range(start_epoch, config.epochs):
        if should_stop is not None and should_stop():
            break

        began = time.monotonic()
        loss = _run_epoch(
            model, optimizer, graph, dataset, examples, sampler, rng, config, model_config
        )

        validation = (
            evaluate_model(
                model, graph, builder, dataset, split.validation, k=config.k, seed=config.seed
            )
            if split.validation
            else None
        )
        report = EpochReport(
            epoch=epoch + 1,
            loss=loss,
            validation=validation,
            seconds=time.monotonic() - began,
        )
        result.history.append(report)
        if on_epoch is not None:
            on_epoch(report)

        score = validation.ndcg if validation is not None else -loss
        if score > result.best_metric or epoch == start_epoch:
            result.best_metric = score
            result.best_epoch = epoch + 1
            best_state = {
                name: value.detach().clone() for name, value in model.state_dict().items()
            }
            stale = 0
        else:
            stale += 1

        if checkpoint_path is not None:
            save_checkpoint(
                checkpoint_path,
                model,
                optimizer,
                TrainingState(
                    epoch=epoch + 1,
                    step=(epoch + 1) * max(len(examples) // config.batch_size, 1),
                    best_metric=result.best_metric,
                    numpy_state=dict(rng.bit_generator.state),
                ),
                model_config,
            )

        if config.patience and stale >= config.patience:
            result.stopped_early = True
            break

    # The returned model is the best one, not the last one. Without this the
    # early-stopping patience window is trained *into* the model that gets
    # registered, and the metric recorded against a version is a metric that
    # version no longer has.
    model.load_state_dict(best_state)
    return result


def _run_epoch(
    model: DGSR,
    optimizer: torch.optim.Optimizer,
    graph: InteractionGraph,
    dataset: Dataset,
    examples: list[Example],
    sampler: NegativeSampler,
    rng: np.random.Generator,
    config: TrainingConfig,
    model_config: DGSRConfig,
) -> float:
    """One pass over the examples in shuffled order. Returns the mean loss."""
    model.train()
    order = rng.permutation(len(examples))
    total, batches = 0.0, 0

    for start in range(0, len(order), config.batch_size):
        chunk = [examples[int(i)] for i in order[start : start + config.batch_size]]
        prefixes = [
            dataset.sequences[example.user][: example.position][-model_config.max_sequence_length :]
            for example in chunk
        ]
        sequences = pad_sequences(prefixes, model_config.max_sequence_length)
        seeds = sequences[:, -1].numpy().clip(min=0)
        neighbourhood = sample_two_hop(graph, seeds, rng, fanouts=config.fanouts)

        state = model.user_representation(
            sequences,
            torch.as_tensor(neighbourhood.hop2, dtype=torch.long),
            torch.as_tensor(neighbourhood.hop1_mask),
            torch.as_tensor(neighbourhood.hop2_mask),
        )

        positives = torch.as_tensor([example.target for example in chunk], dtype=torch.long)
        negatives = torch.as_tensor(
            sampler.draw(
                [
                    set(prefix) | {example.target}
                    for prefix, example in zip(prefixes, chunk, strict=True)
                ],
                rng,
                count=config.n_negatives,
            ),
            dtype=torch.long,
        )

        positive_scores = model.score(state, positives.unsqueeze(1)).squeeze(1)
        negative_scores = model.score(state, negatives)
        weights = torch.as_tensor([example.weight for example in chunk], dtype=torch.float32)

        loss = bpr_loss(positive_scores, negative_scores, weights)
        if config.l2:
            loss = loss + config.l2 * l2_penalty(state, model.encode_items(positives))

        optimizer.zero_grad(set_to_none=True)
        loss.backward()  # type: ignore[no-untyped-call]
        optimizer.step()

        total += float(loss.detach())
        batches += 1

    return total / max(batches, 1)


__all__ = [
    "EpochReport",
    "Example",
    "TrainingConfig",
    "TrainingResult",
    "build_examples",
    "train",
]
