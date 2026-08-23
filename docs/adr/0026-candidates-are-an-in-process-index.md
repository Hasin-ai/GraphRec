# ADR 0026 — Candidates come from an in-process index, and Qdrant is deferred behind a port

**Status:** Accepted — confirmed by instruction to proceed
**Phase:** 10
**Date:** 2026-08-23

## Context

D4 asks where candidate retrieval happens. Two documents disagree, and this is
the sharpest documented conflict in the project.

**SRS §6.3 specifies a Qdrant vector store contract**: collections named
`graphrec__{tenant_id}__{version_id}`, mandatory `tenant_id` payload filters,
the collection deleted when a version is archived. `.env.example` carries
`QDRANT_URL`, `QDRANT_COLLECTION_PREFIX`, `QDRANT_EMBEDDING_DIM=128` and
`QDRANT_TOP_K=100`. The prototype's training rail has a distinct
`indexing_embeddings` stage, which is the visible trace of that step.

**`GraphRec_Ultimate_Architecture.md` §4 and §39 (SYSTEM_DESIGN D-5) specify the
opposite**: exact vectorised top-K in process, ANN deferred. The arithmetic it
gives is the reason — 50,000 items at 128 dimensions in `float32` is 25 MB, and
ASM-02 puts the platform at four tenants.

The SRS is the higher authority (BACKEND_PLAN §2), so this cannot be resolved by
picking the document one prefers. It has to be resolved on what the two are
actually claiming, and they are not claiming the same kind of thing: §6.3
specifies an *isolation contract* — per-tenant collections, mandatory filters,
deletion on archive — and D-5 specifies an *implementation*. The contract is
what protects a tenant; the implementation is what runs it.

## Decision

**Candidate retrieval is an exact top-K over an in-process matrix, behind a
`CandidateIndex` port.** One matrix multiply against the item embedding matrix
Phase 8's `DGSR.item_matrix()` already exports, then a partial sort.

**Qdrant is deferred, not rejected**, and the deferral is bounded by three
things that make it reversible:

1. **The port is the seam.** `CandidateIndex` has `build`, `search` and `drop`.
   Neither the serving path nor the training pipeline mentions a matrix, a
   collection or an HTTP client.
2. **§6.3's isolation contract is honoured by the in-process adapter, not
   waived.** An index is built per `(tenant_id, model_version_id)` and its
   manifest carries `tenant_id`; a search cannot be issued against an index
   belonging to another tenant, because the index is loaded from a bundle whose
   manifest is checked first. `drop` on archive is the collection deletion. The
   part of §6.3 that protects a tenant is implemented; the part that names a
   product is not.
3. **`CANDIDATE_INDEX=qdrant` fails at startup rather than falling back.** The
   `QDRANT_*` keys are in `Settings` and in `.env.example`, because
   BACKEND_PLAN L467 keeps them as the deferred adapter's configuration
   surface. Nothing reads them today, and that is the risk: a configuration key
   for a service nothing reads is a key an operator will set and then believe.
   So the selector is honest about it — `build_candidate_index` raises
   `NotImplementedError` on `qdrant` and names this ADR. An operator who asked
   for per-collection isolation against a real vector store gets a process that
   does not come up, rather than one that comes up serving from a matrix.

**Exactness is a property, not an accident.** The in-process adapter returns the
true top-K, so there is no recall/latency trade-off to tune and no approximation
error to attribute a bad recommendation to. When the catalogue outgrows it, the
ANN adapter's obligation is to *approach* what this one already does, and this
one remains available as the oracle its tests compare against.

## Consequences

The index lives in the inference process's memory and is rebuilt from the bundle
at load. Nothing is shared between tenants, because nothing is shared at all:
each inference process is pinned to one tenant by `GRAPHREC_TENANT_ID` (Phase
11). No vector database to run, secure, back up or upgrade.

Against that: memory is linear in catalogue size, and a tenant with two million
items would need the ANN adapter rather than a bigger machine. The search is
`O(items)` per request — at 50,000 items that is well inside NR-NF-04's 300 ms,
and at ten million it would not be.

**The SRS is now knowingly divergent on the name of one component.** This ADR is
the record of that, so it is a decision somebody made rather than a discrepancy
somebody will find. If Qdrant is later required as a deliverable rather than as
an implementation, the work is one adapter, and the tests that pin §6.3's
isolation contract are already written against the port.

## Related

- ADR 0024 — evaluation ranks the whole catalogue, for the same reason this
  ranks the whole catalogue: an exact answer needs no calibration.
- `GraphRec_Ultimate_Architecture.md` §4, §39 (D-5); SRS §6.3.
