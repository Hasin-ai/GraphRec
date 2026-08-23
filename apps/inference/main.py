"""The per-tenant inference process.

One tenant, one model version, one job: answer `POST /v1/recommendations` in
under 300 ms at P95 (NR-NF-04). Everything else about this process follows from
that number and from SRS §6.4's pin.

**It refuses to start without `GRAPHREC_TENANT_ID`.** A process with no pin
would resolve its tenant from whichever credential arrived, which is exactly the
per-request scope resolution the control plane does — and it would make tenant
isolation a property of a code path rather than of a process boundary. The
failure is loud and at start-up, where an operator is watching.

**Readiness is the deployment's control signal, not a formality.** `/readyz`
answers `true` only when a verified bundle for the bound version is resident in
the index. The Compose driver's healthcheck reads it, `observe` reports it as
`serving_replicas.ready`, and the reconciler swaps `active_version_id` only when
it sees a ready replica serving the *desired* version. A `/readyz` that returned
`200` for "the web server is up" would break load-before-swap at its first link
and would let a bundle that never loaded retire the version that was working.

**A refusal is recorded on a second session, after the first has rolled back.**
When nothing can answer and the caller declined the fallback, the `503` rolls
its transaction back — including any row written to explain itself. The refusal
is therefore written afterwards, on a fresh session, so `/service-status` shows
a serving path that failed rather than one that was never asked.

**Nothing here logs a `session_id`, a customer identifier or an item list.** The
identifiers are hashed on the way in, and the only trace of a request in the
logs is its reference and its outcome. dc.html L1842's rule about the console is
a rule about this process too: the results are the tenant's, not ours.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from redis.asyncio import ConnectionPool, Redis

from apps.inference.binding import BindingError, BundleBinder
from apps.inference.deps import RequireFeedback, RequireRecommendations
from apps.inference.schemas import (
    FeedbackRequestBody,
    FeedbackResponse,
    HealthResponse,
    ImpressionsRequestBody,
    ModelVersionBody,
    ReadyResponse,
    RecommendationRequestBody,
    RecommendationResponse,
    RecommendedItemBody,
    SessionRecommendationRequestBody,
)
from graphrec.common.config import Settings, get_settings
from graphrec.common.errors import UnavailableError
from graphrec.common.logging import configure_logging, get_logger
from graphrec.db.engine import create_app_engine, create_sessionmaker
from graphrec.db.tenant_context import bind_tenant
from graphrec.domain.metering.counters import RedisUsageCounters, ResilientUsageCounters
from graphrec.domain.serving.feedback import FeedbackItem, FeedbackService, ImpressionItem
from graphrec.domain.serving.recommend import (
    RecentEvent,
    RecommendationInput,
    RecommendationService,
)
from graphrec.http import (
    BodyLimitMiddleware,
    RequestContextMiddleware,
    install_error_handlers,
)
from graphrec.ml.index import build_candidate_index
from graphrec.serving.states import FeedbackType, ServingErrorClass
from graphrec.storage.factory import create_artifact_store

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from apps.inference.deps import DataPlanePrincipal
    from apps.inference.schemas import RecentEventBody
    from graphrec.domain.serving.feedback import FeedbackReceipt
    from graphrec.domain.serving.recommend import Recommendation

logger = get_logger(__name__)

API_PREFIX = "/v1"

router = APIRouter(prefix=API_PREFIX, tags=["data-plane"])
operational = APIRouter(tags=["health"])


class MissingTenantPinError(RuntimeError):
    """`GRAPHREC_TENANT_ID` was not set. SRS §6.4 requires it."""


# ---------------------------------------------------------------- lifecycle


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bind the bundle before the first request, and say so if it will not bind.

    A failure to bind is not a failure to start. The process comes up unready
    and keeps reporting why: the reconciler needs an unready replica it can
    observe and time out, and a process that exited would be restarted by
    Compose into an identical failure at a slower rate.
    """
    settings: Settings = app.state.settings
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    logger.info(
        "inference_starting",
        extra={
            "tenant_id": str(app.state.tenant_id),
            "candidate_index": settings.candidate_index.value,
            "pinned_version_id": (
                str(app.state.pinned_version_id) if app.state.pinned_version_id else None
            ),
        },
    )

    await _rebind(app)
    poller = asyncio.create_task(_poll(app), name="graphrec-binder-poll")
    app.state.poller = poller

    yield

    poller.cancel()
    with suppress(asyncio.CancelledError):
        await poller
    await app.state.engine.dispose()
    await app.state.redis.aclose()
    await app.state.redis_pool.disconnect()
    logger.info("inference_stopping")


async def _poll(app: FastAPI) -> None:
    """Follow desired state on a timer.

    A pinned process still polls, because the *epoch* moves under it: a rollback
    to the version it is already serving is a new epoch on the same version, and
    a replica that never re-read it would report itself as serving something
    nobody currently wants. It is one indexed read of one row per interval.

    Cancellation is the shutdown path and is not an error. Everything else is
    logged and slept off — a poller that died on a transient database blip would
    leave the process permanently pinned to whatever it last loaded, and nothing
    would say so.
    """
    interval = app.state.settings.inference_poll_seconds
    while True:
        await asyncio.sleep(interval)
        await _rebind(app)


async def _rebind(app: FastAPI) -> None:
    """One refresh attempt, with every failure kept inside it.

    `BindingError` is expected and already recorded on the binder, where
    `/readyz` reports it; re-raising would only take down the poller that has to
    keep observing it.
    """
    binder: BundleBinder = app.state.binder
    try:
        async with _tenant_session(app) as session:
            await binder.refresh(session)
    except BindingError as error:
        logger.error("inference_unbound", extra={"detail": str(error)})
    except asyncio.CancelledError:
        raise
    except Exception:  # the poller outlives its failures
        logger.warning("binder_refresh_failed", exc_info=True)


@asynccontextmanager
async def _tenant_session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    """A session bound to this process's tenant.

    The binder and the refusal recorder both need one outside a request, where
    there is no credential to resolve. The tenant comes from the pin, which is
    the only identifier in this process that was not supplied by a caller.
    """
    sessionmaker = app.state.sessionmaker
    async with sessionmaker() as session, session.begin():
        await bind_tenant(session, app.state.tenant_id)
        yield session


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.tenant_id is None:
        msg = (
            "GRAPHREC_TENANT_ID is required: an inference process serves exactly "
            "one tenant (SRS §6.4)"
        )
        raise MissingTenantPinError(msg)

    app = FastAPI(
        title="GraphRec inference",
        version="0.1.0",
        description=(
            "Per-tenant recommendation serving. The tenant is pinned by "
            "GRAPHREC_TENANT_ID; a credential belonging to anyone else is refused."
        ),
        lifespan=lifespan,
        redirect_slashes=False,
        openapi_url="/openapi.json",
        docs_url="/docs",
    )

    app.state.settings = settings
    app.state.tenant_id = settings.tenant_id
    # Handed over by the `ServingDriver` when this container was started. Absent
    # in shared-process development, where the binder follows desired state in
    # the database instead.
    app.state.pinned_version_id = _pinned_version_id(settings)

    app.add_middleware(
        BodyLimitMiddleware,
        default_limit=settings.max_request_body_bytes,
        bulk_limit=settings.max_bulk_body_bytes,
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    # The tenant role, never the platform one. This process has no legitimate
    # reason to read across tenants and the connection it holds cannot.
    app.state.engine = create_app_engine(settings)
    app.state.sessionmaker = create_sessionmaker(app.state.engine)

    # The pool is held too: `aclose()` does not disconnect a pool the client was
    # handed, and shutdown has to reach it (see `apps/control_api/main.py`).
    app.state.redis_pool = ConnectionPool.from_url(str(settings.redis_url))
    app.state.redis = Redis(connection_pool=app.state.redis_pool)
    # Wrapped: a recommendation must not fail because a cache is down. The
    # fallback costs a ledger query, which is slower and still correct.
    app.state.usage_counters = ResilientUsageCounters(RedisUsageCounters(app.state.redis))

    app.state.candidate_index = build_candidate_index(settings.candidate_index)
    app.state.artifact_store = create_artifact_store(settings)
    app.state.binder = BundleBinder(
        index=app.state.candidate_index,
        store=app.state.artifact_store,
        tenant_id=settings.tenant_id,
        pinned_version_id=app.state.pinned_version_id,
    )

    app.include_router(operational)
    app.include_router(router)
    return app


def _pinned_version_id(settings: Settings) -> uuid.UUID | None:
    """`GRAPHREC_MODEL_VERSION_ID`, read through the environment the driver set.

    Not a `Settings` field: it is per-*container* rather than per-deployment,
    the reconciler writes it, and a value in `.env` would silently pin a
    development process to a version somebody activated last month.
    """
    raw = os.environ.get("GRAPHREC_MODEL_VERSION_ID")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        logger.error("invalid_pinned_version", extra={"value": raw})
        return None


# -------------------------------------------------------------- health


@operational.get("/healthz", response_model=HealthResponse, summary="The process is up")
async def healthz() -> HealthResponse:
    """Liveness. Deliberately says nothing about the model.

    A process whose bundle will not load is alive and should not be restarted —
    restarting it would lose the failure detail `/readyz` is reporting.
    """
    return HealthResponse(status="ok")


@operational.get("/readyz", response_model=ReadyResponse, summary="A model is resident")
async def readyz(request: Request) -> ReadyResponse:
    """Readiness, and the deployment's control signal.

    Answers `200` in both cases — readiness is a field, not a status code —
    because the driver reads the body to learn *which version* is ready, and a
    `503` would collapse "not ready yet" and "the endpoint is broken".
    """
    binder: BundleBinder = request.app.state.binder
    binding = binder.binding
    return ReadyResponse(
        ready=binder.is_ready(),
        tenant_id=request.app.state.tenant_id,
        model_version=(
            ModelVersionBody(
                version_id=binding.model_version_id, version_number=binding.version_number
            )
            if binding is not None
            else None
        ),
        epoch=binding.epoch if binding is not None else None,
        detail=binder.failure,
    )


# ------------------------------------------------------- recommendations


def _service(request: Request) -> RecommendationService:
    """A service bound to what this process actually has resident.

    `pinned_version_id` is the *binding's* version, not the configured one:
    during an activation those differ for as long as it takes the new bundle to
    load, and answering from the row rather than from memory would mean serving
    fallback through the whole of a successful deployment.
    """
    binder: BundleBinder = request.app.state.binder
    binding = binder.binding
    return RecommendationService(
        index=request.app.state.candidate_index,
        pinned_version_id=binding.model_version_id if binding is not None else None,
    )


def _feedback() -> FeedbackService:
    return FeedbackService()


Recommendations = Annotated[RecommendationService, Depends(_service)]
Feedback = Annotated[FeedbackService, Depends(_feedback)]


@router.post(
    "/recommendations",
    response_model=RecommendationResponse,
    summary="Recommend items for a customer or a session",
)
async def recommend(
    body: RecommendationRequestBody,
    request: Request,
    principal: RequireRecommendations,
    service: Recommendations,
) -> RecommendationResponse:
    """ER-F-05: `model_version` and `strategy` in every response, always.

    A `400` when neither `customer_id` nor `session_id` is present: a request
    identifying nobody is not a cold-start request, it is a request whose
    feedback can never be attributed to anything.
    """
    payload = RecommendationInput(
        external_request_id=body.request_id,
        top_n=body.top_n,
        external_customer_id=body.customer_id,
        session_id=body.session_id,
        recent_events=_recent(body.recent_events),
        exclude_product_ids=tuple(body.exclude_product_ids),
        allow_fallback=body.allow_fallback,
        context=dict(body.context),
    )
    return _rendered(await _answer(request, principal, service, payload))


@router.post(
    "/recommendations/session",
    response_model=RecommendationResponse,
    summary="Recommend items for an anonymous session",
)
async def recommend_session(
    body: SessionRecommendationRequestBody,
    request: Request,
    principal: RequireRecommendations,
    service: Recommendations,
) -> RecommendationResponse:
    """XR-F-09. The same funnel with no customer to look up.

    `strategy` comes back as `session` when the caller supplied recent events
    and `cold_start` when they did not — the two are different answers to
    different situations and the tenant needs to tell them apart.
    """
    payload = RecommendationInput(
        external_request_id=body.request_id,
        top_n=body.top_n,
        external_customer_id=None,
        session_id=body.session_id,
        recent_events=_recent(body.recent_events),
        exclude_product_ids=tuple(body.exclude_product_ids),
        allow_fallback=body.allow_fallback,
        context=dict(body.context),
    )
    return _rendered(await _answer(request, principal, service, payload))


async def _answer(
    request: Request,
    principal: DataPlanePrincipal,
    service: RecommendationService,
    payload: RecommendationInput,
) -> Recommendation:
    """Run the funnel, and record the refusal if there is one.

    The `except` re-raises. Recording is a side effect on the way past, on a
    session of its own, because the one the request holds is about to be rolled
    back with the error.
    """
    try:
        return await service.recommend(
            principal.session,
            tenant_id=principal.tenant_id,
            request=payload,
            counters=request.app.state.usage_counters,
        )
    except UnavailableError:
        await _record_refusal(request, service, payload)
        raise


async def _record_refusal(
    request: Request, service: RecommendationService, payload: RecommendationInput
) -> None:
    """Best effort, and never the reason a `503` becomes a `500`."""
    try:
        async with _tenant_session(request.app) as session:
            await service.record_refusal(
                session,
                tenant_id=request.app.state.tenant_id,
                request=payload,
                error_class=ServingErrorClass.UNAVAILABLE,
                reason_key="model_not_ready",
            )
    except Exception:  # a metrics row is not worth a second failure
        logger.warning("refusal_not_recorded", exc_info=True)


def _recent(events: Sequence[RecentEventBody]) -> tuple[RecentEvent, ...]:
    return tuple(
        RecentEvent(
            external_product_id=event.external_product_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
        )
        for event in events
    )


def _rendered(answer: Recommendation) -> RecommendationResponse:
    return RecommendationResponse(
        request_id=answer.external_request_id,
        model_version=(
            ModelVersionBody(
                version_id=answer.model_version_id, version_number=answer.model_version_number
            )
            if answer.model_version_id is not None and answer.model_version_number is not None
            else None
        ),
        strategy=answer.strategy.value,
        fallback_applied=answer.fallback_applied,
        items=[
            RecommendedItemBody(
                external_product_id=item.external_product_id,
                rank=item.rank,
                score=item.score,
                candidate_source=item.candidate_source.value,
            )
            for item in answer.items
        ],
        ordering_policy_version=answer.ordering_policy_version,
        latency_ms=answer.latency_ms,
    )


# ------------------------------------------------------------- feedback


@router.post(
    "/feedback/impressions",
    response_model=FeedbackResponse,
    summary="Report the items that were shown",
)
async def report_impressions(
    body: ImpressionsRequestBody, principal: RequireFeedback, service: Feedback
) -> FeedbackResponse:
    """A repeat is a success (`duplicate_confirmed`), not a conflict.

    ASM-05: nothing recorded here influences a model or activates anything. The
    module that writes it imports nothing that could.
    """
    receipt = await service.record_impressions(
        principal.session,
        tenant_id=principal.tenant_id,
        external_request_id=body.request_id,
        items=[
            ImpressionItem(
                external_event_id=item.event_id,
                external_product_id=item.external_product_id,
                position=item.position,
            )
            for item in body.impressions
        ],
    )
    return _receipt(body.request_id, receipt)


@router.post("/feedback/clicks", response_model=FeedbackResponse, summary="Report clicked items")
async def report_clicks(
    body: FeedbackRequestBody, principal: RequireFeedback, service: Feedback
) -> FeedbackResponse:
    return _receipt(
        body.request_id,
        await service.record_feedback(
            principal.session,
            tenant_id=principal.tenant_id,
            external_request_id=body.request_id,
            feedback_type=FeedbackType.CLICK,
            items=_items(body),
        ),
    )


@router.post("/feedback/conversions", response_model=FeedbackResponse, summary="Report conversions")
async def report_conversions(
    body: FeedbackRequestBody, principal: RequireFeedback, service: Feedback
) -> FeedbackResponse:
    """`value` is recorded here and ignored on clicks — a conversion has an
    amount and a click does not."""
    return _receipt(
        body.request_id,
        await service.record_feedback(
            principal.session,
            tenant_id=principal.tenant_id,
            external_request_id=body.request_id,
            feedback_type=FeedbackType.CONVERSION,
            items=_items(body),
        ),
    )


def _items(body: FeedbackRequestBody) -> list[FeedbackItem]:
    return [
        FeedbackItem(
            external_feedback_id=item.event_id,
            external_product_id=item.external_product_id,
            value=item.value,
        )
        for item in body.events
    ]


def _receipt(request_id: str, receipt: FeedbackReceipt) -> FeedbackResponse:
    return FeedbackResponse(
        request_id=request_id,
        received=receipt.received,
        accepted=receipt.accepted,
        duplicates=receipt.duplicates,
        unknown_products=list(receipt.unknown_products),
    )


def build() -> FastAPI:
    """Entry point for the process manager.

    A function rather than a module-level `app`, because `create_app` raises
    without a tenant pin and a module-level call would make importing this
    module for any reason — a test, a CLI, `--help` — depend on the environment
    already being a deployment.
    """
    return create_app()


__all__ = ["MissingTenantPinError", "build", "create_app", "create_app_factory"]


#: What the process manager points at: `uvicorn apps.inference.main:create_app_factory`
#: with `--factory`. Named separately from `build` so the ASGI entry point is a
#: stable string in the Compose file rather than something a refactor can rename.
create_app_factory = build
