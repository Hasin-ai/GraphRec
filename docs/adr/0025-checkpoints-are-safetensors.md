# ADR 0025 — Checkpoints are safetensors, and there is no `torch.save`

**Status:** Accepted
**Phase:** 8
**Gate:** none.

## Context

`torch.save` writes a pickle. Loading one executes whatever the file says to
execute, and `weights_only=True` narrows that without closing it.

A GraphRec checkpoint crosses a real trust boundary: it is written by the
training worker, stored in object storage that several components can reach, and
read by the inference process, which Phase 11 pins to a single tenant. A tenant
who could influence the bytes of a checkpoint an inference container loads would
have code execution inside that container.

BACKEND_PLAN §8.4 already says "never `pickle`" for model bundles. Checkpoints
are the same artifact one stage earlier, and were not explicitly covered.

## Decision

Checkpoints are safetensors files. `graphrec/ml/train/checkpoint.py` is the only
module that writes one, and `torch.save` appears nowhere in the codebase.

Consequences of the format are absorbed rather than worked around:

* everything non-tensor — the `DGSRConfig`, epoch, step, best metric, the numpy
  bit-generator state — is JSON in the safetensors metadata header under one key,
  `graphrec`;
* optimiser state is flattened into the single tensor namespace under
  `optimizer.<parameter name>.<key>`, keyed by parameter *name* rather than by
  the optimiser's positional slot;
* a file with no `graphrec` header, or a header declaring a different
  `FORMAT_VERSION`, is refused rather than partially read.

Writes go to a temporary file in the target directory and are renamed over the
target, so an interrupted write cannot replace a good checkpoint.

## Consequences

* A resume is exact: weights, Adam's moments and both random generators are
  restored, so an interrupted run and an uninterrupted one produce the same
  model. This is Phase 9's exit criterion and it is already testable.
* Keying optimiser state by parameter name means a refactor that reorders a
  parameter group does not silently mis-restore Adam's moments — which would
  look like a training instability and be undiagnosable from the loss curve.
* A checkpoint cannot hold arbitrary Python. Anything a future stage wants to
  carry must be a tensor or JSON-serialisable, which is a real constraint and
  the intended one.
* Phase 10's bundle export inherits the format and the manifest discipline, and
  the `tenant_id` check it adds is a header field rather than a new mechanism.
