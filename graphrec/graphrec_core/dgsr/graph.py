"""Temporal graph construction, Algorithm 1, and disjoint subgraph batching.

No DGL, PyG, networkx, or pretrained recommender is used. Sampling works with
CPU adjacency lists; neural message passing uses flat PyTorch tensors.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, fields
from typing import Iterable

import numpy as np
import torch
from torch.utils.data import Dataset

from .config import Config
from .data import Example, InteractionData


def as_long(values: Iterable[int] | np.ndarray) -> torch.Tensor:
    return torch.as_tensor(np.asarray(list(values) if not isinstance(values, np.ndarray) else values,
                                      dtype=np.int64)).clone()


@dataclass
class MessageEdges:
    src: torch.Tensor        # local index of the OTHER node type
    dst: torch.Tensor        # local destination index
    relative: torch.Tensor   # last observed neighbor has rank 0
    position: torch.Tensor   # chronological rank, first neighbor has rank 0
    counts: torch.Tensor     # number of incoming event messages per destination
    last_src: torch.Tensor   # latest neighbor, -1 for an isolated destination
    events: torch.Tensor     # original global event IDs, for audits

    def to(self, device: torch.device | str, non_blocking: bool = False) -> "MessageEdges":
        return MessageEdges(**{f.name: getattr(self, f.name).to(device, non_blocking=non_blocking)
                               for f in fields(self)})

    def pin_memory(self) -> "MessageEdges":
        return MessageEdges(**{f.name: getattr(self, f.name).pin_memory() for f in fields(self)})


@dataclass
class GraphSample:
    users: torch.Tensor
    items: torch.Tensor
    to_users: MessageEdges
    to_items: MessageEdges
    root: int
    cutoff: int
    induced_events: torch.Tensor

    def pin_memory(self) -> "GraphSample":
        return GraphSample(self.users.pin_memory(), self.items.pin_memory(),
                           self.to_users.pin_memory(), self.to_items.pin_memory(),
                           self.root, self.cutoff, self.induced_events.pin_memory())


@dataclass
class GraphBatch:
    users: torch.Tensor
    items: torch.Tensor
    to_users: MessageEdges
    to_items: MessageEdges
    roots: torch.Tensor
    targets: torch.Tensor

    def to(self, device: torch.device | str, non_blocking: bool = False) -> "GraphBatch":
        return GraphBatch(self.users.to(device, non_blocking=non_blocking),
                          self.items.to(device, non_blocking=non_blocking),
                          self.to_users.to(device, non_blocking=non_blocking),
                          self.to_items.to(device, non_blocking=non_blocking),
                          self.roots.to(device, non_blocking=non_blocking),
                          self.targets.to(device, non_blocking=non_blocking))

    def pin_memory(self) -> "GraphBatch":
        return GraphBatch(self.users.pin_memory(), self.items.pin_memory(),
                          self.to_users.pin_memory(), self.to_items.pin_memory(),
                          self.roots.pin_memory(), self.targets.pin_memory())

    @property
    def batch_size(self) -> int:
        return self.roots.numel()


class TemporalGraph:
    """An edge-visibility view, with binary search over global event IDs."""
    def __init__(self, data: InteractionData, allowed: np.ndarray | None = None):
        self.data = data
        if allowed is None:
            allowed = np.ones(len(data.users), dtype=bool)
        allowed = np.asarray(allowed, dtype=bool)
        if allowed.shape != data.users.shape:
            raise ValueError("allowed mask must have one entry per interaction")
        self.allowed = allowed
        self.by_user = [events[allowed[events]] for events in data.by_user]
        self.by_item = [events[allowed[events]] for events in data.by_item]

    @staticmethod
    def _before(events: np.ndarray, cutoff: int, limit: int) -> np.ndarray:
        end = int(np.searchsorted(events, cutoff, side="right"))
        start = max(0, end - limit) if limit else 0
        return events[start:end]

    def user_events(self, user: int, cutoff: int, limit: int = 0) -> np.ndarray:
        return self._before(self.by_user[user], cutoff, limit)

    def item_events(self, item: int, cutoff: int, limit: int = 0) -> np.ndarray:
        return self._before(self.by_item[item], cutoff, limit)


class TemporalSampler:
    """Section 4.2 / Algorithm 1 with explicit choices for underspecified details.

    * Initialize with the root's most recent n interaction items.
    * Literally use j=0 and j<=m, i.e. m+1 alternating expansion rounds.
    * Never resample already-expanded anchor nodes.
    * Form the timestamp-filtered node-induced bipartite multigraph.
    * Retain most recent n messages per user; item messages are uncapped
      unless item_neighbor_limit is explicitly set.
    * Rebase relative orders within the retained incoming event sequence.

    An LRU cache stores CPU samples. Limits RAISE rather than truncate.
    """
    def __init__(self, graph: TemporalGraph, cfg: Config):
        self.graph, self.cfg = graph, cfg
        self.cache: OrderedDict[tuple[int, int], GraphSample] = OrderedDict()

    def _check_nodes(self, users: set[int], items: set[int]) -> None:
        limit = self.cfg.max_sample_nodes
        if limit and len(users) + len(items) > limit:
            raise RuntimeError(f"Subgraph exceeded max_sample_nodes={limit}. No edges were silently "
                               "dropped. Lower sampling_order, explicitly set item_neighbor_limit, "
                               "or increase this safety limit; see IMPLEMENTATION_NOTES.md.")

    def sample(self, user: int, cutoff: int) -> GraphSample:
        key = (int(user), int(cutoff))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        data, cfg = self.graph.data, self.cfg
        root_events = self.graph.user_events(user, cutoff, cfg.recent_items)
        if not len(root_events):
            raise ValueError(f"User {data.user_ids[user]!r} has no visible history at cutoff {cutoff}")
        users = {int(user)}
        items = set(map(int, data.items[root_events]))
        item_frontier = set(items)
        self._check_nodes(users, items)
        for _ in range(cfg.sampling_order + 1):
            new_users: set[int] = set()
            for item in sorted(item_frontier):
                events = self.graph.item_events(item, cutoff, cfg.item_neighbor_limit)
                new_users.update(map(int, data.users[events]))
            new_users.difference_update(users)
            if not new_users:
                break
            users.update(new_users)
            self._check_nodes(users, items)
            new_items: set[int] = set()
            for anchor in sorted(new_users):
                events = self.graph.user_events(anchor, cutoff, cfg.recent_items)
                new_items.update(map(int, data.items[events]))
            new_items.difference_update(items)
            if not new_items:
                break
            items.update(new_items)
            self._check_nodes(users, items)
            item_frontier = new_items

        ordered_users, ordered_items = sorted(users), sorted(items)
        user_local = {u: k for k, u in enumerate(ordered_users)}
        item_local = {i: k for k, i in enumerate(ordered_items)}
        user_incident: list[list[int]] = [[] for _ in ordered_users]
        item_incident: list[list[int]] = [[] for _ in ordered_items]
        induced: list[int] = []
        for u in ordered_users:
            for eid_np in self.graph.user_events(u, cutoff):
                eid = int(eid_np)
                i = int(data.items[eid])
                if i not in item_local:
                    continue
                induced.append(eid)
                user_incident[user_local[u]].append(eid)
                item_incident[item_local[i]].append(eid)
                if cfg.max_sample_edges and len(induced) > cfg.max_sample_edges:
                    raise RuntimeError(f"Subgraph exceeded max_sample_edges={cfg.max_sample_edges}; "
                                       "raise the limit or explicitly configure smaller sampling.")
        for events in item_incident:
            events.sort()  # construction above traversed users, not timestamps

        def messages(incident: list[list[int]], opposite: np.ndarray,
                     mapping: dict[int, int], limit: int) -> MessageEdges:
            src, dst, relative, position, counts, latest, event_ids = [], [], [], [], [], [], []
            for dest, ids in enumerate(incident):
                chosen = ids[-limit:] if limit else ids
                count = len(chosen)
                counts.append(count)
                latest.append(mapping[int(opposite[chosen[-1]])] if count else -1)
                for rank, eid in enumerate(chosen):
                    src.append(mapping[int(opposite[eid])])
                    dst.append(dest)
                    relative.append(count - rank - 1)
                    position.append(rank)
                    event_ids.append(eid)
            return MessageEdges(*(as_long(x) for x in
                                  (src, dst, relative, position, counts, latest, event_ids)))

        sample = GraphSample(as_long(ordered_users), as_long(ordered_items),
                             messages(user_incident, data.items, item_local, cfg.recent_items),
                             messages(item_incident, data.users, user_local, cfg.item_neighbor_limit),
                             user_local[user], cutoff, as_long(sorted(induced)))
        if cfg.graph_cache_size:
            self.cache[key] = sample
            while len(self.cache) > cfg.graph_cache_size:
                self.cache.popitem(last=False)
        return sample


class ExampleDataset(Dataset):
    def __init__(self, examples: list[Example], sampler: TemporalSampler):
        self.examples, self.sampler = examples, sampler

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> tuple[GraphSample, Example]:
        ex = self.examples[index]
        return self.sampler.sample(ex.user, ex.cutoff), ex


def collate_graphs(rows: list[tuple[GraphSample, Example]]) -> tuple[GraphBatch, list[Example]]:
    """Keep snapshots disjoint even when their global node IDs are identical."""
    if not rows:
        raise ValueError("Cannot batch an empty list")
    user_offsets, item_offsets, nu, ni = [], [], 0, 0
    for graph, _ in rows:
        user_offsets.append(nu)
        item_offsets.append(ni)
        nu += graph.users.numel()
        ni += graph.items.numel()

    def cat_messages(name: str, src_offsets: list[int], dst_offsets: list[int]) -> MessageEdges:
        values: dict[str, list[torch.Tensor]] = {f.name: [] for f in fields(MessageEdges)}
        for ((g, _), so, do) in zip(rows, src_offsets, dst_offsets):
            edge = getattr(g, name)
            for f in fields(MessageEdges):
                value = getattr(edge, f.name)
                if f.name == "src":
                    value = value + so
                elif f.name == "dst":
                    value = value + do
                elif f.name == "last_src":
                    value = torch.where(value >= 0, value + so, value)
                values[f.name].append(value)
        return MessageEdges(**{k: torch.cat(v) for k, v in values.items()})

    batch = GraphBatch(torch.cat([g.users for g, _ in rows]), torch.cat([g.items for g, _ in rows]),
                       cat_messages("to_users", item_offsets, user_offsets),
                       cat_messages("to_items", user_offsets, item_offsets),
                       as_long([g.root + off for (g, _), off in zip(rows, user_offsets)]),
                       as_long([e.target for _, e in rows]))
    return batch, [e for _, e in rows]
