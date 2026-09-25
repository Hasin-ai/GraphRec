"""Serve a trained DGSR checkpoint: load, verify, encode a shopper, score items.

A DGSR artifact directory holds what the training notebook writes:

    best.pt             validation-selected weights + config + data fingerprint
    config.json         the training Config
    id_maps.json        tenant user_id / item_id strings in index order
    interactions.npz    the training interaction graph (users, items, times, ...)
    final_metrics.json  offline evaluation (optional; validation_metrics.json also read)

Two encoding paths share one model:

* ``encode_known`` - a user from the training graph, scored exactly as the
  notebook's ``recommend()`` does (Algorithm 1 over the saved graph).
* ``encode_history`` - a *virtual root*: any chronological item history (a
  session, a known user with new events, a brand-new shopper). The root's own
  edges come from the supplied history; its neighbourhood is expanded through
  the saved graph. An unknown user starts from the mean user embedding, which
  is an inductive approximation the model was not trained for, so callers
  label it ``session`` rather than ``personalized``.

The model is transductive; item scores are ``query . item_embedding`` (Eq. 18),
so the item table can be indexed in a vector store and the query vector used
for retrieval.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import torch

from graphrec_core.dgsr.config import Config
from graphrec_core.dgsr.data import Example, InteractionData
from graphrec_core.dgsr.graph import (
    GraphSample,
    MessageEdges,
    TemporalGraph,
    TemporalSampler,
    as_long,
    collate_graphs,
)
from graphrec_core.dgsr.model import DGSR

logger = logging.getLogger(__name__)

SUPPORTED_ENGINES = ("beauty-t4-v1", "beauty-t4-v2", "dgsr-multidata-v4", "graphrec-cpu-v1")
REQUIRED_FILES = ("best.pt", "config.json", "id_maps.json", "interactions.npz")


class ArtifactError(ValueError):
    """The artifact directory is incomplete, inconsistent or unsupported."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class HistoryEvent:
    item: int    # item index in the artifact's id map
    time: int    # unix seconds; orders the root's edges among the graph's


@dataclass
class Encoded:
    query: np.ndarray            # float32 [dim]
    strategy: str                # personalized | session
    known_user: bool
    history_length: int
    subgraph_users: int
    subgraph_items: int


class DGSRArtifact:
    """A loaded checkpoint plus the interaction graph it was trained on."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        missing = [name for name in REQUIRED_FILES if not (self.directory / name).is_file()]
        if missing:
            raise ArtifactError(f"Artifact {self.directory} is missing {missing}")

        checkpoint = torch.load(self.directory / "best.pt", map_location="cpu", weights_only=True)
        engine = checkpoint.get("engine_version")
        if engine not in SUPPORTED_ENGINES:
            raise ArtifactError(f"Unsupported checkpoint engine {engine!r}")
        self.engine_version: str = engine
        self.cfg = Config.from_dict(checkpoint["config"])
        on_disk = Config.load(self.directory / "config.json")
        if on_disk.to_dict() != self.cfg.to_dict():
            raise ArtifactError("config.json differs from the configuration stored in best.pt")

        self.data = _load_interactions(self.directory)
        self.data_fingerprint = _artifact_fingerprint(self.data, self.directory, engine)
        if checkpoint.get("data_fingerprint") != self.data_fingerprint:
            raise ArtifactError("interactions.npz does not match the data fingerprint in best.pt")
        if (checkpoint.get("num_users"), checkpoint.get("num_items")) != (self.data.num_users, self.data.num_items):
            raise ArtifactError("Vocabulary sizes in best.pt differ from id_maps.json")
        capacity = int(checkpoint["position_capacity"])
        if capacity != self.data.position_capacity(self.cfg):
            raise ArtifactError("position_capacity in best.pt differs from the interaction graph")

        torch.set_num_threads(max(1, self.cfg.torch_threads))
        self.model = DGSR(self.data.num_users, self.data.num_items, capacity, self.cfg)
        self.model.load_state_dict(checkpoint["model"], strict=True)
        self.model.eval()
        for parameter in self.model.parameters():
            if not torch.isfinite(parameter).all():
                raise ArtifactError("Checkpoint contains non-finite model parameters")
            parameter.requires_grad_(False)

        self.checkpoint_sha256 = file_sha256(self.directory / "best.pt")
        self.checkpoint_epoch = checkpoint.get("epoch")
        self.selection_ndcg10 = checkpoint.get("selection_ndcg10")
        self.metrics = _load_metrics(self.directory)
        del checkpoint

        # Everything is visible at serving time (the notebook's "inference" policy).
        self.graph = TemporalGraph(self.data, self.data.allowed_events("inference", self.cfg))
        self.sampler = TemporalSampler(self.graph, self.cfg)
        self.cutoff = len(self.data.users) - 1
        with torch.no_grad():
            self.mean_user_embedding = self.model.user_embedding.weight.mean(dim=0).clone()
        self._lock = threading.Lock()

    # -- identity -----------------------------------------------------------------

    @property
    def dim(self) -> int:
        return self.cfg.embedding_dim

    @property
    def item_ids(self) -> list[str]:
        return self.data.item_ids

    @property
    def user_ids(self) -> list[str]:
        return self.data.user_ids

    def item_index(self, external_id: str) -> int | None:
        return self.data.item_to_index.get(external_id)

    def user_index(self, user_id: str) -> int | None:
        return self.data.user_to_index.get(user_id)

    def item_embeddings(self) -> np.ndarray:
        """Base item table e_i (Eq. 18 scores against this, not the subgraph state)."""
        return self.model.item_embedding.weight.detach().cpu().numpy().astype(np.float32)

    def known_history(self, user: int) -> list[str]:
        return [self.data.item_ids[int(i)] for i in self.data.items[self.data.by_user[user]]]

    def describe(self) -> dict[str, Any]:
        return {
            "engine_version": self.engine_version,
            "checkpoint_sha256": self.checkpoint_sha256,
            "checkpoint_epoch": self.checkpoint_epoch,
            "selection_ndcg10": self.selection_ndcg10,
            "embedding_dim": self.dim,
            "layers": self.cfg.layers,
            "users": self.data.num_users,
            "items": self.data.num_items,
            "interactions": int(len(self.data.users)),
            "data_fingerprint": self.data_fingerprint,
        }

    # -- encoding -----------------------------------------------------------------

    def encode_known(self, user: int) -> Encoded:
        """The notebook's serving path for a user of the training graph."""
        with self._lock:
            sample = self.sampler.sample(user, self.cutoff)
            batch, _ = collate_graphs([(sample, Example(user, self.cutoff, 0, self.cutoff))])
            with torch.no_grad():
                query = self.model.encode(batch)[0]
        return Encoded(
            query=query.float().numpy().astype(np.float32),
            strategy="personalized",
            known_user=True,
            history_length=int(len(self.data.by_user[user])),
            subgraph_users=int(sample.users.numel()),
            subgraph_items=int(sample.items.numel()),
        )

    def encode_history(self, history: Sequence[HistoryEvent], user: int | None = None) -> Encoded:
        """Encode a virtual root whose own edges are ``history`` (chronological).

        ``user`` names a training-graph user to take the root embedding from; the
        graph's copy of that user's events is replaced by ``history`` so nothing
        is counted twice. ``None`` uses the mean user embedding.
        """
        if not history:
            raise ValueError("A history with at least one known item is required")
        cfg = self.cfg
        with self._lock:
            sample, root_local = self._sample_virtual(list(history), user)
            batch, _ = collate_graphs([(sample, Example(root_local, self.cutoff, 0, self.cutoff))])
            root_vector = None if user is not None else self.mean_user_embedding
            with torch.no_grad():
                query = _encode_with_root(self.model, batch, root_vector)[0]
        return Encoded(
            query=query.float().numpy().astype(np.float32),
            strategy="personalized" if user is not None else "session",
            known_user=user is not None,
            history_length=len(history),
            subgraph_users=int(sample.users.numel()),
            subgraph_items=int(sample.items.numel()),
        )

    def score(self, query: np.ndarray, exclude_items: Sequence[int] = ()) -> np.ndarray:
        """Full-catalog scores for one query vector (Eq. 18)."""
        with torch.no_grad():
            scores = (torch.as_tensor(query, dtype=torch.float32) @ self.model.item_embedding.weight.T).numpy()
        if len(exclude_items):
            scores[np.asarray(list(exclude_items), dtype=np.int64)] = -np.inf
        return scores

    def top_k(self, scores: np.ndarray, k: int) -> list[tuple[str, float]]:
        finite = int(np.isfinite(scores).sum())
        count = min(k, finite)
        if count <= 0:
            return []
        # Stable ordering: ties keep ascending item index, as in the notebook.
        order = np.lexsort((np.arange(len(scores)), -scores))[:count]
        return [(self.data.item_ids[int(i)], float(scores[i])) for i in order]

    # -- virtual-root sampling (Algorithm 1 with a supplied root history) ----------

    def _sample_virtual(self, history: list[HistoryEvent], root_user: int | None) -> tuple[GraphSample, int]:
        cfg, data, graph = self.cfg, self.data, self.graph
        cutoff = self.cutoff
        root_items = [event.item for event in history[-cfg.recent_items:]]
        users: set[int] = set()
        items: set[int] = set(root_items)
        item_frontier = set(items)
        self.sampler._check_nodes(users, items)
        for _ in range(cfg.sampling_order + 1):
            new_users: set[int] = set()
            for item in sorted(item_frontier):
                events = graph.item_events(item, cutoff, cfg.item_neighbor_limit)
                new_users.update(map(int, data.users[events]))
            new_users.difference_update(users)
            if root_user is not None:
                new_users.discard(root_user)
            if not new_users:
                break
            users.update(new_users)
            self.sampler._check_nodes(users, items)
            new_items: set[int] = set()
            for anchor in sorted(new_users):
                events = graph.user_events(anchor, cutoff, cfg.recent_items)
                new_items.update(map(int, data.items[events]))
            new_items.difference_update(items)
            if not new_items:
                break
            items.update(new_items)
            self.sampler._check_nodes(users, items)
            item_frontier = new_items

        ordered_users = sorted(users)
        ordered_items = sorted(items)
        root_local = len(ordered_users)          # the root is the last local user
        user_local = {u: k for k, u in enumerate(ordered_users)}
        item_local = {i: k for k, i in enumerate(ordered_items)}
        item_array = np.asarray(ordered_items, dtype=np.int64)

        # Induced real edges: every visible event of a sampled user on a sampled item.
        if ordered_users:
            per_user = [graph.user_events(u, cutoff) for u in ordered_users]
            eids = np.concatenate(per_user) if per_user else np.empty(0, dtype=np.int64)
            keep = np.isin(data.items[eids], item_array)
            eids = eids[keep]
        else:
            eids = np.empty(0, dtype=np.int64)
        if cfg.max_sample_edges and len(eids) + len(history) > cfg.max_sample_edges:
            raise RuntimeError(f"Subgraph exceeded max_sample_edges={cfg.max_sample_edges}")

        # Edge table: (time, order key, user_local, item_local). Real events are
        # ordered by their global event id (= (time, csv row)); root events follow
        # any real event with the same timestamp. Like the induced subgraph in
        # Algorithm 1, only root events on sampled items are edges: the newest
        # ``recent_items`` always are, older ones only if their item was reached.
        real_time = data.times[eids]
        real_user = np.fromiter((user_local[int(u)] for u in data.users[eids]), dtype=np.int64, count=len(eids))
        real_item = np.fromiter((item_local[int(i)] for i in data.items[eids]), dtype=np.int64, count=len(eids))
        root_events = [event for event in history if event.item in item_local]
        root_time = np.asarray([event.time for event in root_events], dtype=np.int64)
        root_item_local = np.asarray([item_local[event.item] for event in root_events], dtype=np.int64)
        root_key = np.arange(len(root_events), dtype=np.int64) + (len(data.users) + 1)
        edge_time = np.concatenate([real_time, root_time])
        edge_key = np.concatenate([eids, root_key])
        edge_user = np.concatenate([real_user, np.full(len(root_events), root_local, dtype=np.int64)])
        edge_item = np.concatenate([real_item, root_item_local])
        edge_event = np.concatenate([eids, np.full(len(root_events), -1, dtype=np.int64)])
        order = np.lexsort((edge_key, edge_time))

        to_users = _messages(edge_user[order], edge_item[order], edge_event[order],
                             len(ordered_users) + 1, cfg.recent_items)
        to_items = _messages(edge_item[order], edge_user[order], edge_event[order],
                             len(ordered_items), cfg.item_neighbor_limit)
        # The virtual root's embedding row is the mean vector or the known user's.
        root_global = root_user if root_user is not None else 0
        sample = GraphSample(
            as_long(ordered_users + [root_global]), as_long(ordered_items),
            to_users, to_items, root_local, cutoff, as_long(np.sort(eids)),
        )
        return sample, root_local


def _messages(dst: np.ndarray, src: np.ndarray, events: np.ndarray, size: int, limit: int) -> MessageEdges:
    """Group chronologically ordered edges per destination, keeping the last ``limit``."""
    src_out: list[int] = []
    dst_out: list[int] = []
    relative: list[int] = []
    position: list[int] = []
    counts = [0] * size
    latest = [-1] * size
    event_out: list[int] = []
    if len(dst):
        grouping = np.argsort(dst, kind="stable")
        dst_sorted = dst[grouping]
        boundaries = np.flatnonzero(np.diff(dst_sorted)) + 1
        starts = np.concatenate([[0], boundaries])
        ends = np.concatenate([boundaries, [len(dst_sorted)]])
        for start, end in zip(starts, ends):
            chosen = grouping[start:end]
            if limit:
                chosen = chosen[-limit:]
            dest = int(dst_sorted[start])
            count = len(chosen)
            counts[dest] = count
            latest[dest] = int(src[chosen[-1]])
            src_out.extend(int(s) for s in src[chosen])
            dst_out.extend([dest] * count)
            relative.extend(range(count - 1, -1, -1))
            position.extend(range(count))
            event_out.extend(int(e) for e in events[chosen])
    return MessageEdges(*(as_long(x) for x in (src_out, dst_out, relative, position, counts, latest, event_out)))


def _encode_with_root(model: DGSR, batch, root_vector: torch.Tensor | None) -> torch.Tensor:
    """``DGSR.encode`` with the root's layer-0 state optionally replaced."""
    users = model.user_embedding(batch.users)
    if root_vector is not None:
        users = users.clone()
        users[batch.roots] = root_vector.to(users.dtype)
    items = model.item_embedding(batch.items)
    roots = [users[batch.roots]]
    for layer in model.layers:
        users, items, _ = layer(users, items, batch, model.key_positions, model.value_positions, False)
        roots.append(users[batch.roots])
    return model.readout(torch.cat(roots, dim=-1))


def _artifact_fingerprint(data: InteractionData, directory: Path, engine: str) -> str:
    """Match each training engine's identity contract, including v4 split rows.

    Hash the original arrays directly; creating hundreds of thousands of Example
    objects is unnecessary at serving time. Never weaken the legacy checksum.
    """
    if engine != "dgsr-multidata-v4":
        return data.fingerprint()
    digest = hashlib.sha256()
    for array in (data.users, data.items, data.times, data.row_ids, data.roles):
        digest.update(array.tobytes())
    digest.update(json.dumps([data.user_ids, data.item_ids], ensure_ascii=False).encode("utf-8"))
    with np.load(directory / "interactions.npz", allow_pickle=False) as arrays:
        for split in ("train", "validation", "test"):
            digest.update(np.asarray(arrays[f"examples_{split}"], dtype=np.int64).tobytes())
    return digest.hexdigest()


def _load_interactions(directory: Path) -> InteractionData:
    """``InteractionData.load`` without materialising the training examples."""
    maps = json.loads((directory / "id_maps.json").read_text(encoding="utf-8"))
    report_path = directory / "data_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    with np.load(directory / "interactions.npz", allow_pickle=False) as arrays:
        data = InteractionData(arrays["users"], arrays["items"], arrays["times"], arrays["row_ids"],
                               maps["user_ids"], maps["item_ids"], report)
        data.roles = arrays["roles"].copy()
    return data


def _load_metrics(directory: Path) -> dict[str, Any]:
    for name in ("final_metrics.json", "validation_metrics.json"):
        path = directory / name
        if not path.is_file():
            continue
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if name == "final_metrics.json" and isinstance(loaded, dict) and "validation" in loaded:
            summary = {}
            for split, values in loaded.items():
                if isinstance(values, dict):
                    summary[split] = {k: v for k, v in values.items()
                                      if k.startswith(("Hit@", "NDCG@")) or k in ("evaluated_examples", "mode")}
            return summary
        if isinstance(loaded, dict):
            return {"validation": {k: v for k, v in loaded.items()
                                   if k.startswith(("Hit@", "NDCG@")) or k in ("evaluated_examples", "mode")}}
    return {}


# -- process-wide cache -----------------------------------------------------------

_ARTIFACTS: dict[str, DGSRArtifact] = {}
_CACHE_LOCK = threading.Lock()


def load_artifact(directory: str | Path) -> DGSRArtifact:
    key = str(Path(directory).resolve())
    with _CACHE_LOCK:
        cached = _ARTIFACTS.get(key)
        if cached is not None:
            return cached
    artifact = DGSRArtifact(Path(directory))
    with _CACHE_LOCK:
        return _ARTIFACTS.setdefault(key, artifact)


def evict_artifact(directory: str | Path) -> None:
    with _CACHE_LOCK:
        _ARTIFACTS.pop(str(Path(directory).resolve()), None)
