"""DGSR and all eleven Table 3 variants, implemented using PyTorch primitives.

Notation map (paper, arXiv:2104.07368v2):
    W1 = item_projection; W2 = user_projection
    Eq. 13 W3 = last_item_query; Eq. 14 W4 = last_user_query
    Eq. 15/16 W3/W4 = user_update/item_update (DISTINCT matrices)
    Eq. 18 W_P^T = readout.weight

Both node types update SYNCHRONOUSLY from layer l-1. Candidate scores use the
BASE item embedding e_i, not the final subgraph item state.
"""
from __future__ import annotations

import math
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F

from .config import Config
from .graph import GraphBatch, MessageEdges


def full_precision(x: torch.Tensor) -> torch.Tensor:
    return x.float() if x.dtype in (torch.float16, torch.bfloat16) else x


def segment_sum(values: torch.Tensor, destinations: torch.Tensor, size: int) -> torch.Tensor:
    # FP32 accumulation prevents half-precision reduction overflow on a T4.
    if values.dtype in (torch.float16, torch.bfloat16):
        values = values.float()
    result = values.new_zeros((size,) + values.shape[1:])
    return result.index_add(0, destinations, values)


def segment_softmax(scores: torch.Tensor, destinations: torch.Tensor, size: int) -> torch.Tensor:
    """A separate numerically stable softmax over each node's incoming edges."""
    if scores.dtype in (torch.float16, torch.bfloat16):
        scores = scores.float()
    if scores.numel() == 0:
        return scores
    maxima = scores.new_full((size,), -torch.inf)
    # Subtracting a detached segment maximum preserves the softmax derivative.
    maxima.scatter_reduce_(0, destinations, scores.detach(), reduce="amax", include_self=True)
    numerator = torch.exp(scores - maxima[destinations])
    denominator = segment_sum(numerator, destinations, size)
    return numerator / denominator[destinations]


class ChronologicalGRU(nn.Module):
    """A GRU recurrence from primitives, for the Section 4.3 RNN alternative.

    Standard reset-after-linear GRU convention:
      r = sigmoid(x_r + h_r); z = sigmoid(x_z + h_z)
      n = tanh(x_n + r * h_n); h' = (1-z)*n + z*h
    Each destination's messages are consumed oldest to newest. The paper does
    not specify a GRU gate convention; this matches torch.nn.GRU's convention.
    """
    def __init__(self, dim: int):
        super().__init__()
        self.input_linear = nn.Linear(dim, 3 * dim)
        self.hidden_linear = nn.Linear(dim, 3 * dim)
        self.dim = dim

    def forward(self, source: torch.Tensor, edges: MessageEdges) -> torch.Tensor:
        h = source.new_zeros((edges.counts.numel(), self.dim))
        if not edges.src.numel():
            return h
        # Group independent destinations by their next chronological step;
        # no dense [nodes, max_degree, dim] padding is allocated.
        order = torch.argsort(edges.position, stable=True)
        step_counts = torch.bincount(edges.position).cpu().tolist()
        projected = self.input_linear(source[edges.src])
        cursor = 0
        for count in step_counts:
            idx = order[cursor:cursor + count]
            dst = edges.dst[idx]
            old = h[dst]
            xr, xz, xn = projected[idx].chunk(3, dim=-1)
            hr, hz, hn = self.hidden_linear(old).chunk(3, dim=-1)
            reset = torch.sigmoid(xr + hr)
            update = torch.sigmoid(xz + hz)
            candidate = torch.tanh(xn + reset * hn)
            new = (1.0 - update) * candidate + update * old
            h = h.index_copy(0, dst, new)
            cursor += count
        return h


class DGRNLayer(nn.Module):
    def __init__(self, cfg: Config, position_capacity: int):
        super().__init__()
        self.dim = cfg.embedding_dim
        self.scale = math.sqrt(self.dim)
        self.long_term, self.short_term = cfg.long_term, cfg.short_term
        # Biases are absent from the printed attention/update equations.
        self.item_projection = nn.Linear(self.dim, self.dim, bias=False)  # W1
        self.user_projection = nn.Linear(self.dim, self.dim, bias=False)  # W2
        self.last_item_query = nn.Linear(self.dim, self.dim, bias=False)  # short W3
        self.last_user_query = nn.Linear(self.dim, self.dim, bias=False)  # short W4
        self.user_update = nn.Linear(3 * self.dim, self.dim, bias=False)
        self.item_update = nn.Linear(3 * self.dim, self.dim, bias=False)
        self.user_gru = ChronologicalGRU(self.dim) if cfg.long_term == "gru" else None
        self.item_gru = ChronologicalGRU(self.dim) if cfg.long_term == "gru" else None
        self.key_positions = (nn.Embedding(position_capacity, self.dim)
                              if cfg.long_term == "dat" and cfg.position_sharing == "layer" else None)
        self.value_positions = (nn.Embedding(position_capacity, self.dim)
                                if cfg.long_term == "dat" and cfg.position_sharing == "layer" else None)

    def _long(self, center: torch.Tensor, source: torch.Tensor,
              projected_center: torch.Tensor, projected_source: torch.Tensor,
              edges: MessageEdges, gru: ChronologicalGRU | None,
              key_positions: nn.Embedding | None,
              value_positions: nn.Embedding | None) -> tuple[torch.Tensor, torch.Tensor | None]:
        n = center.shape[0]
        if self.long_term == "none":
            return torch.zeros_like(center), None
        if self.long_term == "gru":  # Eq. 3-4
            assert gru is not None
            return gru(source, edges), None
        if self.long_term == "gcn":  # Eq. 1-2: neighbor MEAN, not symmetric GCN normalization
            result = segment_sum(projected_source[edges.src], edges.dst, n)
            return result / edges.counts.clamp_min(1).unsqueeze(-1), None
        assert key_positions is not None and value_positions is not None
        # Eq. 5-10: different relative-order embeddings for KEYS and VALUES.
        keys = projected_source[edges.src] + key_positions(edges.relative)
        values = projected_source[edges.src] + value_positions(edges.relative)
        logits = (full_precision(projected_center[edges.dst]) * full_precision(keys)).sum(-1) / self.scale
        attention = segment_softmax(logits, edges.dst, n)
        return segment_sum(attention.unsqueeze(-1) * values, edges.dst, n), attention

    def _short(self, center: torch.Tensor, source: torch.Tensor,
               edges: MessageEdges, query_layer: nn.Linear,
               key_layer: nn.Linear) -> tuple[torch.Tensor, torch.Tensor | None]:
        if self.short_term == "none":
            return torch.zeros_like(center), None
        latest = source[edges.last_src.clamp_min(0)]
        latest = latest * (edges.last_src >= 0).unsqueeze(-1)
        if self.short_term == "last":
            return latest, None
        # Eq. 11-14. Values are RAW previous-layer neighbor states.
        queries = query_layer(latest)
        keys = key_layer(source)[edges.src]
        logits = (full_precision(queries[edges.dst]) * full_precision(keys)).sum(-1) / self.scale
        attention = segment_softmax(logits, edges.dst, center.shape[0])
        result = segment_sum(attention.unsqueeze(-1) * source[edges.src], edges.dst, center.shape[0])
        return result, attention

    def forward(self, users: torch.Tensor, items: torch.Tensor, batch: GraphBatch,
                key_positions: nn.Embedding | None = None,
                value_positions: nn.Embedding | None = None,
                return_trace: bool = False) -> tuple[torch.Tensor, torch.Tensor, dict[str, Any] | None]:
        kp = self.key_positions if self.key_positions is not None else key_positions
        vp = self.value_positions if self.value_positions is not None else value_positions
        pu, pi = self.user_projection(users), self.item_projection(items)
        long_u, alpha = self._long(users, items, pu, pi, batch.to_users, self.user_gru, kp, vp)
        long_i, beta = self._long(items, users, pi, pu, batch.to_items, self.item_gru, kp, vp)
        # Literal equation sharing: Eq. 13 applies W2 to ITEM states, while
        # Eq. 14 applies W1 to USER states. Do not silently interchange them.
        short_u, alpha_short = self._short(users, items, batch.to_users,
                                          self.last_item_query, self.user_projection)
        short_i, beta_short = self._short(items, users, batch.to_items,
                                         self.last_user_query, self.item_projection)
        # Eq. 15-16: both updates read the SAME old layer states.
        # Keep the UPDATE projection and tanh in FP32 under CUDA autocast.
        # Casting AFTER a half-precision tanh cannot recover values rounded to +/-1.
        # This changes precision, not the DGSR node-update equation. Float64 tests
        # retain float64 through full_precision(). Other projections still use AMP.
        with torch.autocast(device_type=users.device.type, enabled=False):
            next_users = torch.tanh(self.user_update(full_precision(torch.cat([long_u, short_u, users], dim=-1))))
            next_items = torch.tanh(self.item_update(full_precision(torch.cat([long_i, short_i, items], dim=-1))))
        trace = None
        if return_trace:
            trace = {"long_users": long_u, "long_items": long_i,
                     "short_users": short_u, "short_items": short_i,
                     "attention_long_users": alpha, "attention_long_items": beta,
                     "attention_short_users": alpha_short, "attention_short_items": beta_short,
                     "updated_users": next_users, "updated_items": next_items}
        return next_users, next_items, trace


class DGSR(nn.Module):
    def __init__(self, num_users: int, num_items: int, position_capacity: int, cfg: Config):
        super().__init__()
        cfg.validate()
        if min(num_users, num_items, position_capacity) < 1:
            raise ValueError("Vocabulary sizes and position capacity must be positive")
        self.cfg = cfg
        self.num_users, self.num_items, self.position_capacity = num_users, num_items, position_capacity
        d = cfg.embedding_dim
        self.user_embedding = nn.Embedding(num_users, d)
        self.item_embedding = nn.Embedding(num_items, d)
        self.key_positions = (nn.Embedding(position_capacity, d)
                              if cfg.long_term == "dat" and cfg.position_sharing == "global" else None)
        self.value_positions = (nn.Embedding(position_capacity, d)
                                if cfg.long_term == "dat" and cfg.position_sharing == "global" else None)
        self.layers = nn.ModuleList([DGRNLayer(cfg, position_capacity) for _ in range(cfg.layers)])
        self.readout = nn.Linear((cfg.layers + 1) * d, d, bias=False)
        self.reset_parameters()

    def reset_parameters(self) -> None:
        # Initialization is an explicit engineering choice; unspecified in paper.
        for module in self.modules():
            if isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, mean=0.0, std=0.1)
            elif isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def encode(self, batch: GraphBatch, return_trace: bool = False):
        users, items = self.user_embedding(batch.users), self.item_embedding(batch.items)
        roots = [users[batch.roots]]
        traces = []
        for layer in self.layers:
            users, items, trace = layer(users, items, batch, self.key_positions,
                                        self.value_positions, return_trace)
            roots.append(users[batch.roots])
            if return_trace:
                traces.append(trace)
        concatenated = torch.cat(roots, dim=-1)   # Eq. 17 includes layer ZERO
        query = self.readout(concatenated)        # h_u^T W_P, Eq. 18
        return (query, {"root_states": roots, "concatenated": concatenated, "layers": traces}) if return_trace else query

    def score_candidates(self, query: torch.Tensor, candidates: torch.Tensor) -> torch.Tensor:
        if candidates.ndim == 1:
            return query @ self.item_embedding(candidates).T
        if candidates.ndim == 2 and candidates.shape[0] == query.shape[0]:
            return (query.unsqueeze(1) * self.item_embedding(candidates)).sum(-1)
        raise ValueError("Candidates must have shape [C] or [batch_size, C]")

    def forward(self, batch: GraphBatch, candidates: torch.Tensor | None = None) -> torch.Tensor:
        query = self.encode(batch)
        if candidates is None:
            return query @ self.item_embedding.weight.T  # full-catalog scores
        return self.score_candidates(query, candidates)


def eq20_loss(logits: torch.Tensor, targets: torch.Tensor, reduction: str = "mean") -> torch.Tensor:
    """Printed Eq. 20 data term: BCE over SOFTMAX probabilities, not sigmoid BCE.

    For one-hot y: -log(p_target) - sum_{j != target} log(1-p_j).
    A separate logsumexp computation for the largest-probability class avoids
    log(0) / vanishing clamped gradients when its probability rounds to 1.
    This costs O(batch * catalog), not O(catalog**2).
    """
    if logits.ndim != 2 or targets.shape != (logits.shape[0],):
        raise ValueError("Expected logits [B, I] and targets [B]")
    if logits.shape[1] < 1:
        raise ValueError("Empty item vocabulary")
    logits = full_precision(logits)
    log_p = F.log_softmax(logits, dim=-1)
    positive = -log_p.gather(1, targets[:, None]).squeeze(1)
    if logits.shape[1] == 1:
        per_example = positive
    else:
        top = logits.argmax(dim=-1, keepdim=True)
        # For all non-max classes p <= 1/2, so log1p(-p) is well-conditioned.
        safe_log_p = log_p.scatter(1, top, -torch.inf)
        log_complement = torch.log1p(-safe_log_p.exp())
        without_top = logits.scatter(1, top, -torch.inf)
        top_complement = torch.logsumexp(without_top, dim=-1) - torch.logsumexp(logits, dim=-1)
        log_complement = log_complement.scatter(1, top, top_complement[:, None])
        negative = -log_complement.scatter(1, targets[:, None], 0.0).sum(dim=-1)
        per_example = positive + negative
    if reduction == "none":
        return per_example
    if reduction == "sum":
        return per_example.sum()
    if reduction == "mean":
        return per_example.mean()
    raise ValueError("Reduction must be none, mean, or sum")


def parameter_penalty(model: nn.Module, kind: str) -> torch.Tensor:
    first = next(model.parameters())
    if kind == "none":
        return first.new_zeros(())
    norms = torch.stack([torch.linalg.vector_norm(p) for p in model.parameters()])
    if kind == "l2_norm":  # unsquared norm in the printed equation/text
        return torch.linalg.vector_norm(norms)
    if kind == "l2_squared":
        return norms.square().sum()
    raise ValueError(f"Unknown regularizer: {kind}")


def training_loss(model: DGSR, logits: torch.Tensor, targets: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    cfg = model.cfg
    if cfg.loss == "eq20":
        data_loss = eq20_loss(logits, targets, cfg.loss_reduction)
    else:
        data_loss = F.cross_entropy(logits, targets, reduction=cfg.loss_reduction)
    penalty = cfg.regularization * parameter_penalty(model, cfg.regularizer)
    return data_loss + penalty, data_loss
