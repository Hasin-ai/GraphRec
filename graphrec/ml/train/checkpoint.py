"""Checkpoints, written in safetensors because `pickle` is a remote-code hole.

`torch.save` pickles. A checkpoint written by the training worker is read by a
different process, on a different host, out of object storage that several
components can write to — and unpickling is arbitrary code execution by
construction. BACKEND_PLAN §8.4 settles it in one line ("never `pickle`") and
this module is where the line is enforced: there is no `torch.save` in the
codebase and there must not be one.

That constraint shapes the format. safetensors stores a flat `str → Tensor` map
plus a `str → str` metadata header, so everything that is not a tensor —
configuration, epoch, step, the random state — is JSON in the header, and
everything that is a tensor is flattened into one namespace with a prefix.

**Resume must be exact, not approximate.** Phase 9's exit criterion is that a
crash mid-training resumes from the last checkpoint, and a resume that restores
weights but not the optimiser's moments or the RNG is a resume that produces a
different model from the uninterrupted run. So Adam's state and both random
generators travel with the weights.

**Writes are atomic.** A checkpoint is written to a temporary name in the same
directory and renamed over the target, because the crash a checkpoint exists to
survive can happen during the write that creates it, and a half-written
checkpoint that loads is worse than none.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import torch
from safetensors.torch import load_file, save_file

from graphrec.ml.model.dgsr import DGSRConfig

if TYPE_CHECKING:
    import numpy as np
    from torch import nn
    from torch.optim import Optimizer

#: Namespace prefixes inside the single flat tensor map.
MODEL_PREFIX = "model."
OPTIMIZER_PREFIX = "optimizer."
RNG_PREFIX = "rng."

#: The header key holding everything non-tensor, as a JSON document.
META_KEY = "graphrec"

#: Bumped when the layout of the file changes. A checkpoint from an older
#: version is refused rather than half-read: a silently ignored optimiser state
#: is a resume that quietly restarts Adam, which looks like a training
#: instability and is impossible to diagnose from the loss curve.
FORMAT_VERSION = 1


@dataclass(frozen=True, slots=True)
class TrainingState:
    """Everything a resume needs that is not a weight."""

    epoch: int
    step: int
    best_metric: float
    #: `numpy.random.Generator.bit_generator.state`, verbatim.
    numpy_state: dict[str, Any]


class CheckpointError(RuntimeError):
    """A checkpoint could not be read, or was not written by this code."""


def save_checkpoint(
    path: Path,
    model: nn.Module,
    optimizer: Optimizer,
    state: TrainingState,
    config: DGSRConfig,
) -> None:
    """Write weights, optimiser state and random state to one file, atomically."""
    tensors: dict[str, torch.Tensor] = {
        MODEL_PREFIX + name: value.detach().cpu().contiguous()
        for name, value in model.state_dict().items()
    }

    names = _parameter_names(model, optimizer)
    for index, group in enumerate(optimizer.state_dict()["state"].items()):
        slot, entries = group
        for key, value in entries.items():
            if isinstance(value, torch.Tensor):
                label = names.get(slot, f"slot{index}")
                tensors[f"{OPTIMIZER_PREFIX}{label}.{key}"] = value.detach().cpu().contiguous()

    tensors[RNG_PREFIX + "torch"] = torch.get_rng_state().contiguous()

    header = {
        META_KEY: json.dumps(
            {
                "format_version": FORMAT_VERSION,
                "config": dataclasses.asdict(config),
                "epoch": state.epoch,
                "step": state.step,
                "best_metric": state.best_metric,
                "numpy_state": state.numpy_state,
                "optimizer_scalars": _scalar_state(optimizer, names),
            }
        )
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".partial")
    os.close(handle)
    try:
        save_file(tensors, temporary, metadata=header)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def load_checkpoint(
    path: Path, model: nn.Module, optimizer: Optimizer | None = None
) -> tuple[TrainingState, DGSRConfig]:
    """Restore a checkpoint into an already-constructed model.

    The model must already exist and must already be the right shape — the
    config in the header is *checked* against it, not used to build it. Building
    from the header would let a file decide the shape of the object it is loaded
    into, which is the same trust boundary `pickle` fails at, one layer up.
    """
    try:
        tensors = load_file(str(path))
    except Exception as error:
        msg = f"{path.name} is not a readable safetensors file"
        raise CheckpointError(msg) from error

    header = _read_header(path)
    if header.get("format_version") != FORMAT_VERSION:
        msg = (
            f"{path.name} is checkpoint format {header.get('format_version')!r}, "
            f"and this build reads {FORMAT_VERSION}"
        )
        raise CheckpointError(msg)

    config = DGSRConfig(**header["config"])
    model_state = {
        name.removeprefix(MODEL_PREFIX): value
        for name, value in tensors.items()
        if name.startswith(MODEL_PREFIX)
    }
    missing, unexpected = model.load_state_dict(model_state, strict=False)
    if missing or unexpected:
        msg = f"{path.name} does not match the model: missing={missing}, unexpected={unexpected}"
        raise CheckpointError(msg)

    if optimizer is not None:
        _restore_optimizer(optimizer, model, tensors, header)

    if RNG_PREFIX + "torch" in tensors:
        torch.set_rng_state(tensors[RNG_PREFIX + "torch"].to(torch.uint8))

    return (
        TrainingState(
            epoch=int(header["epoch"]),
            step=int(header["step"]),
            best_metric=float(header["best_metric"]),
            numpy_state=header["numpy_state"],
        ),
        config,
    )


def restore_generator(rng: np.random.Generator, state: TrainingState) -> None:
    """Put a generator back where the checkpoint left it.

    Separate from `load_checkpoint` because the generator belongs to the caller
    — the training loop owns it, and a loader that reached into a global RNG
    would make two concurrent training jobs in one process interfere.
    """
    rng.bit_generator.state = state.numpy_state


def _read_header(path: Path) -> dict[str, Any]:
    """safetensors keeps metadata in the file header; read it without the
    tensors so a corrupt payload still reports a useful error."""
    from safetensors import safe_open

    with safe_open(str(path), framework="pt") as handle:
        metadata = handle.metadata() or {}
    raw = metadata.get(META_KEY)
    if raw is None:
        msg = f"{path.name} has no {META_KEY!r} header — it was not written by this code"
        raise CheckpointError(msg)
    parsed: dict[str, Any] = json.loads(raw)
    return parsed


def _parameter_names(model: nn.Module, optimizer: Optimizer) -> dict[int, str]:
    """Map the optimiser's positional parameter slots to parameter names.

    Optimiser state is keyed by position, and position depends on the order
    parameters were handed to the constructor. Saving under the *name* means a
    checkpoint survives a refactor that reorders a parameter group, which
    positional keys would silently mis-restore.
    """
    ordered = [parameter for group in optimizer.param_groups for parameter in group["params"]]
    by_id = {id(parameter): name for name, parameter in model.named_parameters()}
    return {
        slot: by_id[id(parameter)]
        for slot, parameter in enumerate(ordered)
        if id(parameter) in by_id
    }


def _scalar_state(optimizer: Optimizer, names: dict[int, str]) -> dict[str, dict[str, float]]:
    """Adam's `step` counter and anything else non-tensor, by parameter name."""
    out: dict[str, dict[str, float]] = {}
    for slot, entries in optimizer.state_dict()["state"].items():
        label = names.get(slot)
        if label is None:
            continue
        scalars = {
            key: float(value)
            for key, value in entries.items()
            if isinstance(value, int | float) and not isinstance(value, bool)
        }
        if scalars:
            out[label] = scalars
    return out


def _restore_optimizer(
    optimizer: Optimizer,
    model: nn.Module,
    tensors: dict[str, torch.Tensor],
    header: dict[str, Any],
) -> None:
    """Rebuild the optimiser's per-parameter state from the flat tensor map."""
    names = _parameter_names(model, optimizer)
    scalars: dict[str, dict[str, float]] = header.get("optimizer_scalars", {})

    state: dict[int, dict[str, Any]] = {}
    for slot, label in names.items():
        prefix = f"{OPTIMIZER_PREFIX}{label}."
        entries: dict[str, Any] = {
            name.removeprefix(prefix): value
            for name, value in tensors.items()
            if name.startswith(prefix)
        }
        entries.update(scalars.get(label, {}))
        if entries:
            state[slot] = entries

    if state:
        optimizer.load_state_dict(
            {"state": state, "param_groups": optimizer.state_dict()["param_groups"]}
        )


__all__ = [
    "FORMAT_VERSION",
    "META_KEY",
    "MODEL_PREFIX",
    "OPTIMIZER_PREFIX",
    "RNG_PREFIX",
    "CheckpointError",
    "TrainingState",
    "load_checkpoint",
    "restore_generator",
    "save_checkpoint",
]
