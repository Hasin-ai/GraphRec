"""Bayesian Personalised Ranking, and why the loss is pairwise.

Implicit feedback has no negatives. A user who did not view a product may have
disliked it or may never have been shown it, and there is no column that tells
the difference. Training a pointwise classifier on "interacted = 1, everything
else = 0" therefore teaches the model that most of the catalogue is bad, which
is both false and exactly the wrong bias for a system whose job is to surface
things the user has not seen.

BPR asks the weaker question the data can actually answer: *did this user
prefer the item they touched to one they did not?* The loss is
`-log sigmoid(s_pos - s_neg)`, which depends only on the **difference** between
the two scores. Absolute score is left unconstrained, which is what allows the
dot product to rank without ever being calibrated as a probability.

Two details are ours rather than the paper's.

**Interaction weights scale the term.** `FeatureBuilder` says a purchase is worth
five views; that has to reach the gradient or it is a comment. The weight
multiplies the per-pair loss, so a purchase pair moves the embeddings five times
as far as a view pair.

**Multiple negatives per positive are averaged, not summed.** Raising the negative
count would otherwise raise the effective learning rate, and a hyper-parameter
that silently changes another one is a hyper-parameter nobody can tune.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F  # noqa: N812

#: Below this the sigmoid saturates and `log` underflows to `-inf`. Clamping the
#: *logit* rather than the probability keeps the gradient finite without
#: distorting the well-behaved range.
LOGIT_CLAMP = 15.0


def bpr_loss(
    positive_scores: torch.Tensor,
    negative_scores: torch.Tensor,
    weights: torch.Tensor | None = None,
) -> torch.Tensor:
    """`(n,)` positives against `(n, m)` negatives → a scalar.

    `softplus(-x)` and not `-log(sigmoid(x))`: they are the same function and
    the first is the numerically stable one, which matters because early in
    training the score difference is near zero and late in training it is not.
    """
    difference = positive_scores.unsqueeze(1) - negative_scores
    difference = difference.clamp(-LOGIT_CLAMP, LOGIT_CLAMP)
    per_pair = F.softplus(-difference)

    per_positive = per_pair.mean(dim=1)
    if weights is not None:
        # Normalised by the weight total, not by count, so that a batch of
        # purchases and a batch of views produce comparable loss magnitudes and
        # the reported training curve stays readable across epochs.
        return (per_positive * weights).sum() / weights.sum().clamp(min=1e-8)
    return per_positive.mean()


def l2_penalty(*tensors: torch.Tensor) -> torch.Tensor:
    """Mean squared magnitude of the embeddings involved in a batch.

    Applied to the batch's embeddings rather than through the optimiser's
    `weight_decay`, because decay applied by the optimiser touches every row of
    the table on every step — including the millions of items not in the batch,
    which it would shrink towards zero purely for being unpopular.
    """
    total = torch.zeros((), device=tensors[0].device, dtype=tensors[0].dtype)
    for tensor in tensors:
        total = total + tensor.pow(2).sum() / max(tensor.shape[0], 1)
    return total


__all__ = ["LOGIT_CLAMP", "bpr_loss", "l2_penalty"]
