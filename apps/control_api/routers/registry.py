"""The model registry — what was trained, how good it is, and what may be done.

Four routes. Two more, `:activate` and `:rollback`, are Phase 11's: they change
what serves traffic, and what serves traffic is a deployment rather than a row.
Their *preconditions* are already here, in the `actions` block, because the
console disables those buttons before either route exists and a button whose
reason arrives a phase later is a button with no reason at all.

**Every read carries its own preconditions.** Gate 5 (BUILD_PROMPT §gate-5): the
console must disable a control with a stated reason and without a second round
trip. The prototype computes `canActivate`, `canRollback` and `canArchive`
client-side from its whole store (L1747-1749); a real client cannot hold the
whole store, so the server answers instead — from `graphrec.domain.registry.
lifecycle`, which is also what `:archive` refuses from. One function, two
surfaces, no drift.

**The list and the detail are different shapes on purpose.** `/models` draws six
columns and the detail page draws a three-way comparison across four measures.
Returning the detail shape per row would cost two extra reads per version for
columns the table does not have.

Everything here is session-only. The registry is a `[DEV]`/`[ADM]` surface and
no credential scope names it, so an API credential is refused by `CurrentTenant`
before a route is reached.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, Query, Request

from apps.control_api.deps import CurrentTenant
from apps.control_api.schemas import (
    ArchiveVersionRequest,
    ModelVersionListItem,
    ModelVersionListResponse,
    ModelVersionResponse,
    ModelVersionSummaryResponse,
)
from graphrec.common.enums import ModelVersionStatus
from graphrec.domain.registry import lifecycle
from graphrec.domain.registry.service import RegistryService

if TYPE_CHECKING:
    from graphrec.db.models import ModelVersion

router = APIRouter(prefix="/model-versions", tags=["registry"])


def _service(request: Request) -> RegistryService:
    """The store and the index come from app state when they are there.

    A control-plane process configured without an artifact store can still read
    the registry; it just cannot delete bytes, and `archive` says so rather than
    pretending. Phase 11 populates both.
    """
    state = request.app.state
    return RegistryService(
        store=getattr(state, "artifact_store", None),
        index=getattr(state, "candidate_index", None),
    )


Service = Annotated[RegistryService, Depends(_service)]


# ----------------------------------------------------------------- rendering


def _row(
    version: ModelVersion, model_type: str, context: lifecycle.VersionContext
) -> ModelVersionListItem:
    activate = lifecycle.can_activate(version.version_status)
    return ModelVersionListItem(
        version_id=version.model_version_id,
        version_number=version.version_number,
        model_type=model_type,
        status=version.status,
        created_at=version.created_at,
        metrics=_measures(version.metrics),
        eligible=version.is_eligible(),
        # L1733's last column: "serving" against the active version, an em-dash
        # against every other. A boolean here rather than the string, because
        # the em-dash is a rendering and this is an API.
        serving=version.is_active(),
        can_activate=activate.allowed,
        blocked_reason=activate.reason,
    )


def _measures(values: dict[str, object]) -> dict[str, float | None]:
    """The denormalised headline copy, coerced and with absences kept."""
    return {
        name: (float(value) if isinstance(value, int | float) else None)
        for name, value in (
            (metric, values.get(metric))
            for metric in ("recall_at_10", "hit_rate_at_10", "ndcg_at_10", "coverage")
        )
    }


# -------------------------------------------------------------------- reads


@router.get(
    "/summary",
    response_model=ModelVersionSummaryResponse,
    summary="The five stat cards above the model list",
)
async def model_version_summary(
    principal: CurrentTenant, service: Service
) -> ModelVersionSummaryResponse:
    """Declared above `/{version_id}` on purpose.

    FastAPI matches in declaration order, and `summary` is not a UUID — so the
    mismatch would be a `422` rather than a wrong handler. Relying on that is
    relying on the parameter's type never widening, which is not a thing to rely
    on.
    """
    counts = await service.summary(principal.session)
    return ModelVersionSummaryResponse.model_validate(counts.as_dict())


@router.get("", response_model=ModelVersionListResponse, summary="A tenant's model versions")
async def list_model_versions(
    principal: CurrentTenant,
    service: Service,
    status: ModelVersionStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ModelVersionListResponse:
    """The table at L1726, newest version first.

    The gate-5 context is read once for the whole page rather than per row.
    Per row it would be one query per version for two facts that cannot change
    between rows of the same response — and if they could, a table whose rows
    disagreed about which version is active would be worse than a stale one.
    """
    versions = await service.list_versions(principal.session, status=status, limit=limit)
    context = await service.context(principal.session)
    types = {
        version.model_id: await service.model_type(principal.session, model_id=version.model_id)
        for version in versions
    }
    return ModelVersionListResponse(
        versions=[_row(version, types[version.model_id], context) for version in versions]
    )


@router.get(
    "/{version_id}",
    response_model=ModelVersionResponse,
    summary="One version, against the baseline and the active version",
)
async def get_model_version(
    version_id: uuid.UUID, principal: CurrentTenant, service: Service
) -> ModelVersionResponse:
    """XR-F-10 and UC-17: the comparison is the input to the activation
    decision, so it arrives with the version rather than being assembled by a
    client from three requests it would have to keep consistent."""
    detail = await service.detail(principal.session, version_id=version_id)
    return ModelVersionResponse.model_validate(detail)


# -------------------------------------------------------------------- writes


@router.post(
    "/{version_id}:archive",
    response_model=ModelVersionResponse,
    summary="Archive a version, keeping its record",
)
async def archive_model_version(
    version_id: uuid.UUID,
    body: ArchiveVersionRequest,
    principal: CurrentTenant,
    service: Service,
) -> ModelVersionResponse:
    """L1799: "retained for audit but can no longer be activated or used as a
    roll-back target."

    `409` on every refusal, never `422`: the request is well formed in each
    case, and what forbids it is the state of the registry. The reason returned
    is the same sentence the disabled button carries, because both come from
    `can_archive`.
    """
    await service.archive(
        principal.session,
        tenant_id=principal.tenant_id,
        version_id=version_id,
        reason=body.reason,
    )
    detail = await service.detail(principal.session, version_id=version_id)
    return ModelVersionResponse.model_validate(detail)
