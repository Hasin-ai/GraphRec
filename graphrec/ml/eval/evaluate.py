"""Scoring a trained model under the same protocol the baseline gets.

The comparison is only meaningful if both sides answer the same question, so
this module and `eval.baseline` share one rule set:

* rank over the **whole catalogue**, not a sampled subset of 100 negatives. The
  sampled protocol is common in papers and flattering; it also measures
  something the served system never does, since serving ranks everything. A
  model that wins under sampling and loses over the full catalogue is a model
  that would disappoint a tenant, and this is the phase where that has to be
  visible.
* exclude the user's history, because the funnel in Phase 11 does.
* one relevant item per user, from the temporal split.

The evaluation graph is the **training** graph. Not a graph rebuilt over
everything — that would put the held-out interaction one hop from the user being
scored, which is the leakage the split exists to prevent, reintroduced by the
evaluator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import torch

from graphrec.ml.eval.metrics import DEFAULT_K, Metrics, evaluate_rankings
from graphrec.ml.graph.sample import DEFAULT_FANOUTS, sample_two_hop

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from graphrec.ml.eval.split import HeldOut
    from graphrec.ml.features.builder import Dataset, FeatureBuilder
    from graphrec.ml.graph.build import InteractionGraph
    from graphrec.ml.model.dgsr import DGSR

#: Users scored per forward pass. Evaluation is `n_users` by `n_items` scores,
#: so the batch bounds the score matrix rather than the model input.
EVAL_BATCH = 64


@torch.no_grad()
def rank_users(
    model: DGSR,
    graph: InteractionGraph,
    builder: FeatureBuilder,
    holdout: Sequence[HeldOut],
    *,
    k: int = DEFAULT_K,
    fanouts: tuple[int, int] = DEFAULT_FANOUTS,
    seed: int = 0,
    batch_size: int = EVAL_BATCH,
) -> list[list[int]]:
    """Top-`k` item indices per held-out user, history excluded.

    `torch.no_grad` and `model.eval()` are both set: dropout left on during
    evaluation makes the metric depend on the RNG, and a metric floor applied to
    a number that moves between runs is a floor that rejects models at random.
    """
    was_training = model.training
    model.eval()
    rng = np.random.default_rng(seed)
    rankings: list[list[int]] = []

    try:
        for start in range(0, len(holdout), batch_size):
            chunk = holdout[start : start + batch_size]
            histories = [builder.recent(row.history) for row in chunk]
            state = _user_states(model, graph, histories, rng, fanouts=fanouts)

            scores = state @ model.item_matrix().T
            for row, history in enumerate(histories):
                seen = torch.as_tensor(sorted(set(history)), dtype=torch.long)
                if seen.numel():
                    scores[row, seen] = float("-inf")

            top = torch.topk(scores, k=min(k, scores.shape[1]), dim=1).indices
            rankings.extend(row.tolist() for row in top)
    finally:
        model.train(was_training)

    return rankings


def evaluate_model(
    model: DGSR,
    graph: InteractionGraph,
    builder: FeatureBuilder,
    train: Dataset,
    holdout: Sequence[HeldOut],
    *,
    k: int = DEFAULT_K,
    seed: int = 0,
) -> Metrics:
    """Rank, then score. The function Phase 9's `evaluating` stage calls."""
    if not holdout:
        return Metrics(k=k, n_users=0, recall=0.0, hit_rate=0.0, ndcg=0.0, coverage=0.0)
    rankings = rank_users(model, graph, builder, holdout, k=k, seed=seed)
    relevant: list[Collection[int]] = [{row.item} for row in holdout]
    return evaluate_rankings(rankings, relevant, n_items=train.n_items, k=k)


def _user_states(
    model: DGSR,
    graph: InteractionGraph,
    histories: Sequence[Sequence[int]],
    rng: np.random.Generator,
    *,
    fanouts: tuple[int, int],
) -> torch.Tensor:
    """`(n, dim)` fused representations for a batch of histories."""
    sequences = pad_sequences(histories, model.config.max_sequence_length)
    seeds = sequences[:, -1].numpy()
    neighbourhood = sample_two_hop(graph, seeds.clip(min=0), rng, fanouts=fanouts)

    return model.user_representation(
        sequences,
        torch.as_tensor(neighbourhood.hop2, dtype=torch.long),
        torch.as_tensor(neighbourhood.hop1_mask),
        torch.as_tensor(neighbourhood.hop2_mask),
    )


def pad_sequences(sequences: Sequence[Sequence[int]], length: int) -> torch.Tensor:
    """`(n, length)` int64, **left**-padded with -1.

    Left, so the final column is always the user's most recent item and both the
    sequence read-out and the graph seed are a fixed column rather than a gather
    per row. Shared with the training loop, because a model trained on
    right-padded sequences and served left-padded ones is a model that has
    learned the position of the pad.
    """
    out = torch.full((len(sequences), length), -1, dtype=torch.long)
    for row, sequence in enumerate(sequences):
        tail = list(sequence[-length:])
        if tail:
            out[row, length - len(tail) :] = torch.as_tensor(tail, dtype=torch.long)
    return out


__all__ = ["EVAL_BATCH", "evaluate_model", "pad_sequences", "rank_users"]
