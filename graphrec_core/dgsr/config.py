"""Configuration for an independent implementation of arXiv:2104.07368v2."""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields
import json
from pathlib import Path
from typing import Any


@dataclass
class Config:
    # Sections 4.3-4.4. The default complete model is DGSR-DA.
    embedding_dim: int = 50
    layers: int = 3
    long_term: str = "dat"          # dat, gcn, gru, none
    short_term: str = "attention"  # attention, last, none
    position_sharing: str = "global"  # global or layer; paper has no layer index
    # Section 4.2. Zero item limit means ALL eligible item neighbors.
    recent_items: int = 50
    sampling_order: int = 4
    item_neighbor_limit: int = 0
    max_sample_nodes: int = 100_000   # fail loudly; never silently truncate
    max_sample_edges: int = 1_000_000
    graph_cache_size: int = 256
    # Data. Paper's 5-core filtering is available in configs/paper.json.
    min_user_interactions: int = 1
    min_item_interactions: int = 1
    duplicates: str = "keep"         # keep, drop, error
    split: str = "leave_two_out"     # leave_two_out, global_time, none
    train_fraction: float = 0.8
    validation_fraction: float = 0.1
    graph_policy: str = "split_safe" # split_safe, paper_temporal
    # Eq. 20 is NOT ordinary categorical cross entropy as printed.
    loss: str = "eq20"               # eq20 or cross_entropy
    loss_reduction: str = "mean"     # mean or sum over examples
    regularizer: str = "l2_norm"     # l2_norm (printed), l2_squared, none
    regularization: float = 1e-4
    learning_rate: float = 0.01
    batch_size: int = 50
    epochs: int = 100
    patience: int = 10
    gradient_clip: float = 0.0       # optional extension, disabled by default
    num_workers: int = 0
    torch_threads: int = 1
    # Evaluation. Negative sampling is evaluation-only, NOT training BPR.
    evaluation: str = "sampled"      # sampled or full
    negative_items: int = 100
    negative_exclusion: str = "all"  # all interactions, or observed prefix
    strict_negative_count: bool = False
    metric_k: int = 10
    score_chunk_size: int = 4096
    exclude_same_time_positives: bool = False
    evaluation_seed: int = 2026
    sample_cache_dir: str = ""
    sample_cache_bytes: int = 512 * 1024**2
    sample_cache_train: bool = False
    seed: int = 42
    device: str = "auto"

    def validate(self) -> "Config":
        allowed = {
            "long_term": {"dat", "gcn", "gru", "none"},
            "short_term": {"attention", "last", "none"},
            "position_sharing": {"global", "layer"},
            "duplicates": {"keep", "drop", "error"},
            "split": {"leave_two_out", "global_time", "none"},
            "graph_policy": {"split_safe", "paper_temporal"},
            "loss": {"eq20", "cross_entropy"},
            "loss_reduction": {"mean", "sum"},
            "regularizer": {"l2_norm", "l2_squared", "none"},
            "evaluation": {"sampled", "full"},
            "negative_exclusion": {"all", "prefix"},
        }
        for name, values in allowed.items():
            if getattr(self, name) not in values:
                raise ValueError(f"{name} must be one of {sorted(values)}")
        if self.long_term == "none" and self.short_term == "none":
            raise ValueError("At least one message encoder must be enabled.")
        for name in ("embedding_dim", "layers", "recent_items", "batch_size", "epochs",
                     "metric_k", "score_chunk_size", "torch_threads"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be positive")
        for name in ("sampling_order", "item_neighbor_limit", "max_sample_nodes",
                     "max_sample_edges", "graph_cache_size", "num_workers", "patience",
                     "negative_items", "regularization", "gradient_clip"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.min_user_interactions < 1 or self.min_item_interactions < 1:
            raise ValueError("Interaction thresholds must be at least 1")
        if not 0 < self.train_fraction < 1 or not 0 < self.validation_fraction < 1:
            raise ValueError("Split fractions must be in (0, 1)")
        if self.train_fraction + self.validation_fraction >= 1:
            raise ValueError("Train and validation fractions must leave a test interval")
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        if self.evaluation == "sampled" and self.negative_items < 1:
            raise ValueError("Sampled evaluation needs at least one negative")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")
        if self.evaluation_seed < 0 or self.sample_cache_bytes < 0:
            raise ValueError("Evaluation seed and cache quota must be nonnegative")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Config":
        unknown = set(value) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown configuration fields: {sorted(unknown)}")
        return cls(**value).validate()

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")


VARIANTS = {
    "G": ("gcn", "none"), "R": ("gru", "none"), "D": ("dat", "none"),
    "L": ("none", "last"), "A": ("none", "attention"),
    "GL": ("gcn", "last"), "RL": ("gru", "last"), "DL": ("dat", "last"),
    "GA": ("gcn", "attention"), "RA": ("gru", "attention"),
    "DA": ("dat", "attention"),
}
