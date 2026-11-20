"""CSV ingestion, chronological sequences, prefix labels and graph visibility.

Each interaction is an event, including repeated (user, item) pairs. Event IDs
are ordered by (timestamp, original CSV row). There is no padding ID: ID 0 is
an ordinary, trainable user/item.
"""
from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from .config import Config


@dataclass(frozen=True)
class Example:
    user: int
    cutoff: int            # GLOBAL event ID of the LAST OBSERVED interaction
    target: int            # next item, NOT an input edge
    target_event: int

    def as_list(self) -> list[int]:
        return [self.user, self.cutoff, self.target, self.target_event]


class InteractionData:
    def __init__(self, users: np.ndarray, items: np.ndarray, times: np.ndarray,
                 row_ids: np.ndarray, user_ids: list[str], item_ids: list[str],
                 report: dict[str, Any] | None = None):
        self.users = np.asarray(users, dtype=np.int64)
        self.items = np.asarray(items, dtype=np.int64)
        self.times = np.asarray(times, dtype=np.int64)
        self.row_ids = np.asarray(row_ids, dtype=np.int64)
        self.user_ids, self.item_ids = user_ids, item_ids
        self.user_to_index = {v: k for k, v in enumerate(user_ids)}
        self.item_to_index = {v: k for k, v in enumerate(item_ids)}
        self.report = report or {}
        self.by_user = self._index(self.users, self.num_users)
        self.by_item = self._index(self.items, self.num_items)
        self.user_order = self._orders(self.by_user)
        self.item_order = self._orders(self.by_item)
        self.examples: dict[str, list[Example]] = {s: [] for s in ("train", "validation", "test")}
        self.roles = np.zeros(len(self.users), dtype=np.int8)

    @property
    def num_users(self) -> int:
        return len(self.user_ids)

    @property
    def num_items(self) -> int:
        return len(self.item_ids)

    def _index(self, column: np.ndarray, n: int) -> list[np.ndarray]:
        result: list[list[int]] = [[] for _ in range(n)]
        for eid, node in enumerate(column):
            result[int(node)].append(eid)
        return [np.asarray(v, dtype=np.int64) for v in result]

    def _orders(self, index: list[np.ndarray]) -> np.ndarray:
        result = np.empty(len(self.users), dtype=np.int64)
        for events in index:
            result[events] = np.arange(1, len(events) + 1)
        return result

    @classmethod
    def from_csv(cls, path: str | Path, cfg: Config) -> "InteractionData":
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"CSV not found: {path}")
        records: list[tuple[str, str, int, int]] = []
        seen: set[tuple[str, str, int]] = set()
        duplicates = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("CSV is empty; expected user_id,item_id,time header")
            reader.fieldnames = [s.strip() for s in reader.fieldnames]
            required = {"user_id", "item_id", "time"}
            if not required.issubset(reader.fieldnames):
                raise ValueError(f"CSV requires {sorted(required)}; got {reader.fieldnames}")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("CSV contains duplicate column names")
            for row_id, row in enumerate(reader):
                if None in row:
                    raise ValueError(f"CSV row {row_id + 2} has more fields than the header")
                if any(row.get(k) is None or not str(row[k]).strip() for k in required):
                    raise ValueError(f"CSV row {row_id + 2} has a missing user/item/time")
                u, i = row["user_id"].strip(), row["item_id"].strip()
                try:
                    value = Decimal(row["time"].strip())
                    if not value.is_finite() or value != value.to_integral_value():
                        raise ValueError("time must be an integer timestamp")
                    t = int(value)
                    if not np.iinfo(np.int64).min <= t <= np.iinfo(np.int64).max:
                        raise ValueError("timestamp is outside signed 64-bit range")
                except (InvalidOperation, ValueError, OverflowError) as exc:
                    raise ValueError(f"Invalid time on CSV row {row_id + 2}: {row['time']!r}") from exc
                key = (u, i, t)
                if key in seen:
                    duplicates += 1
                    if cfg.duplicates == "error":
                        raise ValueError(f"Duplicate event on CSV row {row_id + 2}: {key}")
                    if cfg.duplicates == "drop":
                        continue
                seen.add(key)
                records.append((u, i, t, row_id))
        initial = len(records)
        # Iterative filtering: a removal on one side can lower the other's degree.
        iterations = 0
        while records:
            uc, ic = Counter(r[0] for r in records), Counter(r[1] for r in records)
            filtered = [r for r in records if uc[r[0]] >= cfg.min_user_interactions
                        and ic[r[1]] >= cfg.min_item_interactions]
            if len(filtered) == len(records):
                break
            records = filtered
            iterations += 1
        if not records:
            raise ValueError("No interactions remain after parsing/filtering. The paper's "
                             "5-core needs repeated histories on BOTH user and item sides. "
                             "Use thresholds 1 for unfiltered data, not fabricated events.")
        user_ids = sorted({r[0] for r in records})
        item_ids = sorted({r[1] for r in records})
        um = {s: k for k, s in enumerate(user_ids)}
        im = {s: k for k, s in enumerate(item_ids)}
        records.sort(key=lambda r: (r[2], r[3]))
        report = {"input_file": str(path.resolve()), "duplicate_rows": duplicates,
                  "duplicate_policy": cfg.duplicates, "parsed_rows_after_dedup": initial,
                  "removed_by_core_filter": initial - len(records),
                  "core_filter_iterations": iterations}
        return cls(np.array([um[r[0]] for r in records]), np.array([im[r[1]] for r in records]),
                   np.array([r[2] for r in records]), np.array([r[3] for r in records]),
                   user_ids, item_ids, report)

    def make_splits(self, cfg: Config) -> None:
        self.examples = {s: [] for s in ("train", "validation", "test")}
        self.roles = np.zeros(len(self.users), dtype=np.int8)
        if cfg.split == "global_time":
            unique_times = np.unique(self.times)
            if len(unique_times) < 3:
                raise ValueError("global_time split needs at least three distinct timestamps")
            a = min(max(1, int(len(unique_times) * cfg.train_fraction)), len(unique_times) - 2)
            b = min(max(a + 1, int(len(unique_times) * (cfg.train_fraction + cfg.validation_fraction))),
                    len(unique_times) - 1)
            train_end, val_end = int(unique_times[a - 1]), int(unique_times[b - 1])
            self.roles[self.times > train_end] = 1
            self.roles[self.times > val_end] = 2
            self.report["global_train_end"] = train_end
            self.report["global_validation_end"] = val_end
        short_users = 0
        for u, events in enumerate(self.by_user):
            if cfg.split == "leave_two_out":
                if len(events) < 4:
                    short_users += 1
                    continue  # context-only; no dishonest train/val/test overlap
                self.roles[events[-2]] = 1
                self.roles[events[-1]] = 2
            for position in range(1, len(events)):
                eid = int(events[position])
                role = int(self.roles[eid])
                name = ("train", "validation", "test")[role]
                self.examples[name].append(Example(u, int(events[position - 1]),
                                                   int(self.items[eid]), eid))
        for name in self.examples:
            self.examples[name].sort(key=lambda x: x.target_event)
        train_users = set(map(int, self.users[self.roles == 0]))
        train_items = set(map(int, self.items[self.roles == 0]))
        self.report.update({
            "events": len(self.users), "users": self.num_users, "items": self.num_items,
            "users_with_one_event": sum(len(v) == 1 for v in self.by_user),
            "context_only_short_users": short_users,
            "split": cfg.split, "graph_policy": cfg.graph_policy,
            "examples": {k: len(v) for k, v in self.examples.items()},
            "cold_target_counts": {
                s: {"users_not_in_train_events": sum(e.user not in train_users for e in self.examples[s]),
                    "items_not_in_train_events": sum(e.target not in train_items for e in self.examples[s])}
                for s in ("validation", "test")},
        })

    def require_training_examples(self) -> None:
        if not self.examples["train"]:
            raise ValueError(
                "No next-item training examples. One event per user cannot supervise a "
                "sequence predictor. leave_two_out needs at least four events for a "
                "supervised user (one train pair, one validation target, one test target). "
                "split='none' needs at least two, but provides no held-out evaluation. "
                "Collect real repeated histories; do not invent timestamps or labels.")

    def allowed_events(self, split: str, cfg: Config) -> np.ndarray:
        if split == "inference" or cfg.graph_policy == "paper_temporal":
            return np.ones(len(self.users), dtype=bool)
        if split == "train":
            return self.roles == 0
        if split == "validation":
            # Global-time validation is a rolling observed stream; each example
            # still has a strict prefix-event cutoff. Leave-two-out is train-only.
            return self.roles <= (1 if cfg.split == "global_time" else 0)
        if split == "test":
            return self.roles <= (2 if cfg.split == "global_time" else 1)
        raise ValueError(f"Unknown split: {split}")

    def excluded_items(self, example: Example, mode: str) -> set[int]:
        events = self.by_user[example.user]
        if mode == "prefix":
            events = events[:np.searchsorted(events, example.cutoff, side="right")]
        result = set(map(int, self.items[events]))
        result.add(example.target)
        return result

    def position_capacity(self, cfg: Config) -> int:
        user_max = min(cfg.recent_items, max(map(len, self.by_user)))
        item_max = max(map(len, self.by_item))
        if cfg.item_neighbor_limit:
            item_max = min(item_max, cfg.item_neighbor_limit)
        return max(1, user_max, item_max)

    def fingerprint(self) -> str:
        h = hashlib.sha256()
        for a in (self.users, self.items, self.times, self.row_ids, self.roles):
            h.update(a.tobytes())
        h.update(json.dumps([self.user_ids, self.item_ids], ensure_ascii=False).encode("utf-8"))
        return h.hexdigest()

    def save(self, directory: str | Path) -> None:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        arrays = {"users": self.users, "items": self.items, "times": self.times,
                  "row_ids": self.row_ids, "roles": self.roles}
        arrays.update({f"examples_{s}": np.asarray([e.as_list() for e in ex], dtype=np.int64).reshape(-1, 4)
                       for s, ex in self.examples.items()})
        np.savez_compressed(directory / "interactions.npz", **arrays)
        (directory / "id_maps.json").write_text(
            json.dumps({"user_ids": self.user_ids, "item_ids": self.item_ids}, ensure_ascii=False),
            encoding="utf-8")
        (directory / "data_report.json").write_text(json.dumps(self.report, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, directory: str | Path) -> "InteractionData":
        directory = Path(directory)
        maps = json.loads((directory / "id_maps.json").read_text(encoding="utf-8"))
        report = json.loads((directory / "data_report.json").read_text(encoding="utf-8"))
        with np.load(directory / "interactions.npz", allow_pickle=False) as a:
            data = cls(a["users"], a["items"], a["times"], a["row_ids"],
                       maps["user_ids"], maps["item_ids"], report)
            data.roles = a["roles"].copy()
            data.examples = {s: [Example(*map(int, row)) for row in a[f"examples_{s}"]]
                             for s in ("train", "validation", "test")}
        return data
