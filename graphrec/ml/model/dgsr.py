"""DGSR: a graph pathway, a sequence pathway, and a gate that chooses between them.

CON-01 fixes the model family, and the reason the family has two pathways is
that a recommendation question has two halves that fail in opposite conditions.
The graph knows what an item *is* — what else the people who touched it touched —
and it knows that even for a user seen once. The sequence knows what this user is
doing *right now*, which the graph averages away. A user with a long history and
a cold catalogue needs the sequence; a first-time visitor on a mature catalogue
needs the graph. Picking one at build time would be picking which of a tenant's
users to serve badly.

So both run, and a **gate** — not a fixed weight, not a concatenation — decides
per user how much of each to use. The gate is a learned sigmoid over the two
representations, so it can settle differently for a user with two interactions
and a user with fifty, which is precisely the behaviour a fixed blend cannot
have.

**Written in plain PyTorch, without PyTorch Geometric** (ADR 0023). The graph
pathway here is two masked means and two linear layers over fixed-shape tensors
that `graph.sample` already produced. PyG would supply message passing over
ragged structures we deliberately do not have, and would add a compiled
extension pinned to a specific torch build to the deployment surface of the
inference container. The bounded sampler is what makes the trade available.

**Shapes are stated on every method** because the padding convention is the part
that goes wrong: `graph.sample` pads with `-1`, and `-1` is a valid index in
PyTorch that silently reads the *last* embedding row. Every gather in this file
clamps the index and multiplies by the mask, in that order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import torch
from torch import nn

if TYPE_CHECKING:
    from graphrec.ml.features.builder import Dataset

#: Padding index for a sequence position that does not exist. Distinct from
#: `graph.sample.PAD` in type but the same idea, and both are resolved by
#: clamp-then-mask rather than by `padding_idx`, because a padded slot must
#: contribute nothing rather than contribute a learned "nothing" vector.
SEQ_PAD = -1


@dataclass(frozen=True, slots=True)
class DGSRConfig:
    """Every hyper-parameter, in one serialisable place.

    A frozen dataclass rather than kwargs so the bundle manifest can record the
    exact configuration a checkpoint was trained under, and Phase 10 can refuse
    to load a checkpoint into a differently-shaped model instead of hitting a
    size mismatch halfway through `load_state_dict`.
    """

    n_items: int
    n_categories: int
    n_static_features: int
    embedding_dim: int = 64
    #: Attention heads in the sequence pathway. Must divide `embedding_dim`.
    n_heads: int = 4
    #: Longest sequence the positional table covers. Sequences are truncated to
    #: it by `FeatureBuilder.recent`, so the two constants must agree.
    max_sequence_length: int = 50
    dropout: float = 0.1

    def __post_init__(self) -> None:
        if self.embedding_dim % self.n_heads:
            msg = f"embedding_dim={self.embedding_dim} is not divisible by n_heads={self.n_heads}"
            raise ValueError(msg)

    @classmethod
    def for_dataset(cls, dataset: Dataset, **overrides: object) -> DGSRConfig:
        """Size the model to a built dataset.

        Taking the sizes from the dataset rather than from configuration is what
        stops the classic off-by-one where the embedding table is one row short
        of the catalogue and the last product is unrecommendable.
        """
        return cls(
            n_items=dataset.n_items,
            n_categories=dataset.n_categories,
            n_static_features=int(dataset.item_features.shape[1]),
            **overrides,  # type: ignore[arg-type]
        )


class ItemEncoder(nn.Module):
    """Item index + category + static features → one vector.

    Shared by both pathways and by scoring, which is the point: the graph
    pathway aggregating one representation while the scorer used another would
    train a model whose two halves disagree about what an item is.
    """

    def __init__(self, config: DGSRConfig) -> None:
        super().__init__()
        dim = config.embedding_dim
        self.item = nn.Embedding(config.n_items, dim)
        # Index 0 is the reserved "no category" row from `FeatureBuilder`, and
        # it is a learned vector rather than a zero: "we do not know this item's
        # category" is itself informative and the model may use it.
        self.category = nn.Embedding(config.n_categories, dim)
        self.static = nn.Linear(config.n_static_features, dim)
        self.norm = nn.LayerNorm(dim)

    def forward(
        self, items: torch.Tensor, categories: torch.Tensor, features: torch.Tensor
    ) -> torch.Tensor:
        """`(..., ) → (..., dim)`. Arbitrary leading shape, so hop-2's
        `(n, f1, f2)` block needs no reshaping at the call site."""
        encoded = self.item(items) + self.category(categories) + self.static(features)
        normalised: torch.Tensor = self.norm(encoded)
        return normalised


class GraphPathway(nn.Module):
    """Two hops of masked mean aggregation, item → user → item.

    Mean and not sum: a bestseller with ten sampled neighbours and a cold item
    with one must produce representations on the same scale, or the norm of an
    embedding becomes a proxy for popularity and the dot-product scorer ranks by
    degree.
    """

    def __init__(self, config: DGSRConfig) -> None:
        super().__init__()
        dim = config.embedding_dim
        self.user_message = nn.Linear(dim, dim)
        self.item_message = nn.Linear(dim, dim)
        self.combine = nn.Linear(dim * 2, dim)
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(config.dropout)

    def forward(
        self,
        seed_encoded: torch.Tensor,
        hop2_encoded: torch.Tensor,
        hop1_mask: torch.Tensor,
        hop2_mask: torch.Tensor,
    ) -> torch.Tensor:
        """`(n, dim)`, `(n, f1, f2, dim)`, `(n, f1)`, `(n, f1, f2)` → `(n, dim)`.

        Hop 2 collapses first: each sampled user becomes the mean of the items
        it touched, which is a user representation built entirely from item
        features and therefore defined for a user the model has never seen. That
        is what lets a session from an anonymous visitor be scored at all.
        """
        users = _masked_mean(hop2_encoded, hop2_mask, dim=2)
        users = self.dropout(self.activation(self.user_message(users)))

        neighbours = _masked_mean(users, hop1_mask, dim=1)
        neighbours = self.dropout(self.activation(self.item_message(neighbours)))

        fused: torch.Tensor = self.combine(torch.cat([seed_encoded, neighbours], dim=-1))
        return fused


class SequencePathway(nn.Module):
    """Self-attention over the user's recent items, read out at the last position.

    Attention rather than a GRU because the useful pattern in a session is
    usually a return — the user looks at three unrelated things and then goes
    back to the first — and a recurrent state has to carry that through every
    intervening step while attention reaches it directly.

    Padding is on the **left**, so the last position is always real and the
    read-out needs no per-row gather. `FeatureBuilder.recent` keeps the tail of
    a sequence, so the two conventions line up.
    """

    def __init__(self, config: DGSRConfig) -> None:
        super().__init__()
        dim = config.embedding_dim
        self.position = nn.Embedding(config.max_sequence_length, dim)
        self.attention = nn.MultiheadAttention(
            dim, config.n_heads, dropout=config.dropout, batch_first=True
        )
        self.norm = nn.LayerNorm(dim)
        self.feed_forward = nn.Sequential(
            nn.Linear(dim, dim * 2),
            nn.ReLU(),
            nn.Dropout(config.dropout),
            nn.Linear(dim * 2, dim),
        )
        self.out_norm = nn.LayerNorm(dim)

    def forward(self, encoded: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        """`(n, L, dim)`, `(n, L)` → `(n, dim)`."""
        length = encoded.shape[1]
        positions = torch.arange(length, device=encoded.device)
        hidden = self.norm(encoded + self.position(positions).unsqueeze(0))

        # A row that is entirely padding — a user with no history at all — would
        # make every key invalid and `MultiheadAttention` would emit NaN. Such
        # rows are given a fully-visible mask and zeroed afterwards instead.
        empty = ~mask.any(dim=1, keepdim=True)
        key_padding = ~(mask | empty)

        attended, _ = self.attention(
            hidden, hidden, hidden, key_padding_mask=key_padding, need_weights=False
        )
        hidden = self.out_norm(hidden + attended)
        hidden = hidden + self.feed_forward(hidden)

        readout: torch.Tensor = hidden[:, -1, :]
        return readout * (~empty).to(readout.dtype)


class GatedFusion(nn.Module):
    """`g ⊙ graph + (1 - g) ⊙ sequence`, with `g` learned per element.

    Per element and not per user: the two pathways do not disagree uniformly.
    Some dimensions of the representation are about what an item is, where the
    graph should win regardless of history length, and some are about immediate
    intent, where the sequence should. A scalar gate would force one answer for
    both.

    `gate_value` is kept as a method rather than folded into `forward` because
    Phase 11 reports it: a deployment whose gate has collapsed to ~1.0 is a
    deployment where the sequence pathway is dead weight, and that is worth
    seeing before a tenant reports it as "recommendations ignore my session".
    """

    def __init__(self, config: DGSRConfig) -> None:
        super().__init__()
        dim = config.embedding_dim
        self.gate = nn.Linear(dim * 2, dim)
        self.project = nn.Linear(dim, dim)

    def gate_value(self, graph: torch.Tensor, sequence: torch.Tensor) -> torch.Tensor:
        """`(n, dim)` in `[0, 1]`. 1 means "trust the graph"."""
        return torch.sigmoid(self.gate(torch.cat([graph, sequence], dim=-1)))

    def forward(self, graph: torch.Tensor, sequence: torch.Tensor) -> torch.Tensor:
        gate = self.gate_value(graph, sequence)
        fused: torch.Tensor = self.project(gate * graph + (1.0 - gate) * sequence)
        return fused


class DGSR(nn.Module):
    """The whole model: encode, run both pathways, fuse, score by dot product.

    Scoring is a dot product and not an MLP over `(user, item)` pairs, and that
    is a serving decision made at training time. A dot product means a model
    version can be exported as a matrix of item vectors, and top-K becomes one
    matrix multiply against a `CandidateIndex` — the port Phase 10 defines.
    A pairwise MLP would require a forward pass per candidate and make NR-NF-04's
    300 ms budget a function of catalogue size.
    """

    # Declared before `register_buffer` so the type checker sees tensors rather
    # than `Tensor | Module`, which is what `nn.Module.__getattr__` is annotated
    # to return and which makes every use of a buffer an error.
    item_categories: torch.Tensor
    item_features: torch.Tensor

    def __init__(self, config: DGSRConfig) -> None:
        super().__init__()
        self.config = config
        self.encoder = ItemEncoder(config)
        self.graph_pathway = GraphPathway(config)
        self.sequence_pathway = SequencePathway(config)
        self.fusion = GatedFusion(config)

        # Static item attributes travel with the model as buffers, not as
        # parameters: they are inputs, but they are also the only way a saved
        # model can encode an item without the caller re-supplying a catalogue.
        self.register_buffer("item_categories", torch.zeros(config.n_items, dtype=torch.long))
        self.register_buffer("item_features", torch.zeros(config.n_items, config.n_static_features))

    def load_catalogue(self, dataset: Dataset) -> None:
        """Copy the dataset's static item attributes into the buffers."""
        self.item_categories.copy_(torch.as_tensor(dataset.item_categories, dtype=torch.long))
        self.item_features.copy_(
            torch.as_tensor(dataset.item_features, dtype=self.item_features.dtype)
        )

    def encode_items(self, items: torch.Tensor) -> torch.Tensor:
        """`(...)` of item indices → `(..., dim)`. Padding-safe.

        The clamp is the padding defence: `-1` would index the last row of the
        embedding table without error, so indices are clamped to a valid row and
        the result multiplied by the mask. Clamp first, mask second — masking a
        NaN produced by a bad gather does not remove the NaN.
        """
        valid = items >= 0
        safe = items.clamp(min=0)
        encoded: torch.Tensor = self.encoder(
            safe, self.item_categories[safe], self.item_features[safe]
        )
        return encoded * valid.unsqueeze(-1).to(encoded.dtype)

    def user_representation(
        self,
        sequence: torch.Tensor,
        hop2: torch.Tensor,
        hop1_mask: torch.Tensor,
        hop2_mask: torch.Tensor,
    ) -> torch.Tensor:
        """`(n, L)`, `(n, f1, f2)`, `(n, f1)`, `(n, f1, f2)` → `(n, dim)`.

        The graph pathway is seeded with the user's **most recent item**, which
        is the closest thing to "a node for this user" that also exists for an
        anonymous session. Seeding with a user embedding would give the model
        nothing to say about a visitor who has never been seen, which is most of
        them.
        """
        sequence_mask = sequence >= 0
        encoded_sequence = self.encode_items(sequence)
        sequence_state: torch.Tensor = self.sequence_pathway(encoded_sequence, sequence_mask)

        seed_encoded = encoded_sequence[:, -1, :]
        graph_state: torch.Tensor = self.graph_pathway(
            seed_encoded, self.encode_items(hop2), hop1_mask, hop2_mask
        )
        fused: torch.Tensor = self.fusion(graph_state, sequence_state)
        return fused

    def score(self, user_state: torch.Tensor, items: torch.Tensor) -> torch.Tensor:
        """`(n, dim)` against `(n, c)` candidate indices → `(n, c)` scores."""
        candidates = self.encode_items(items)
        return torch.einsum("nd,ncd->nc", user_state, candidates)

    def item_matrix(self) -> torch.Tensor:
        """`(n_items, dim)` — every item encoded, for export and for indexing.

        This is the artifact Phase 10 writes into the bundle and Phase 11's
        `CandidateIndex` searches. It is computed without the graph pathway
        because an item's exported vector must not depend on which users were
        sampled the moment it was exported.
        """
        items = torch.arange(self.config.n_items, device=self.item_features.device)
        return self.encode_items(items)


def _masked_mean(values: torch.Tensor, mask: torch.Tensor, *, dim: int) -> torch.Tensor:
    """Mean over `dim`, counting only masked-in entries, zero where none are.

    `clamp(min=1)` on the denominator rather than adding an epsilon: an empty
    neighbourhood has a numerator of exactly zero, so dividing by one gives
    exactly zero, whereas an epsilon gives a very large vector if the numerator
    was ever nonzero — which is how a padding bug becomes an exploding gradient.
    """
    weights = mask.unsqueeze(-1).to(values.dtype)
    total = (values * weights).sum(dim=dim)
    count = weights.sum(dim=dim).clamp(min=1.0)
    return total / count


__all__ = [
    "SEQ_PAD",
    "DGSR",
    "DGSRConfig",
    "GatedFusion",
    "GraphPathway",
    "ItemEncoder",
    "SequencePathway",
]
