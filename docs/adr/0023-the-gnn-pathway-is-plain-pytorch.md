# ADR 0023 — The GNN pathway is plain PyTorch, not PyTorch Geometric

**Status:** Accepted
**Phase:** 8
**Gate:** none. D4 (candidate index) is the next gate and is separate.

## Context

BACKEND_PLAN §8.4 names "PyTorch 2.x + PyTorch Geometric" as the modelling
stack. PyG's value is message passing over *ragged* neighbourhoods: it supplies
scatter/gather kernels and a `MessagePassing` base class so that a node with two
neighbours and a node with two hundred thousand can be aggregated in one call.

Phase 8 does not have ragged neighbourhoods. `graphrec/ml/graph/sample.py` bounds
the fan-out per hop, so a batch is always `(n, f1)` and `(n, f1, f2)` with a
boolean mask. Aggregation over that is a masked mean — one multiply, one sum,
one divide — repeated twice.

The cost side is concrete rather than stylistic. `torch-geometric` pulls
`torch-scatter` and `torch-sparse`, which are compiled extensions built against
a specific torch version and CUDA/CPU ABI. They would land in the inference
container, which Phase 11 has to keep small and start fast, and every torch
upgrade would become a coordinated rebuild of three wheels.

## Decision

The GNN pathway is implemented in plain PyTorch over the fixed-shape tensors the
bounded sampler produces. No PyTorch Geometric, no `torch-scatter`, no
`torch-sparse`.

The bounded sampler is what makes this available, so the two decisions travel
together: if the fan-out bound is ever removed, this ADR is void.

## Consequences

* The dependency surface is `torch`, `numpy` and `safetensors`. The inference
  image does not carry compiled graph kernels it would never call.
* `GraphPathway` is about forty lines and is directly testable — the padding
  behaviour (`test_an_empty_neighbourhood_gives_a_finite_representation`) is
  ours to assert rather than a library's to guarantee.
* Full-neighbourhood aggregation is not available. A future evaluation that
  wants to measure what the fan-out bound costs cannot simply raise it to
  infinity; it would need a different aggregation path.
* Very large fan-outs would be memory-inefficient here in a way PyG's sparse
  kernels are not, because padding is materialised. At `(10, 10)` this is a
  hundred `int64` per seed and irrelevant; at `(1000, 1000)` it would not be.
  The fan-out constant is therefore load-bearing and is documented as such.
