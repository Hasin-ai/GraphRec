"""Single source of truth for every GraphRec HTTP route the SDK calls.

Each resource method looks up its route here, and ``tests/test_contract.py``
compares this table with the FastAPI routers in ``apps/api/routes`` so SDK and
server cannot silently drift apart.

``required_scopes`` lists every scope the credential needs for the route (most
routes need exactly ``scope``; a dataset upload writes both the catalog and
events). ``scope_enforced`` is ``True`` where the server checks those scopes;
platform routes use the separate platform administrator token instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Literal, Mapping, Optional, Tuple
from urllib.parse import quote

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
#: ``none`` - never send credentials; ``optional`` - send them when configured;
#: ``any`` - an API key or bearer token is required; ``bearer`` - a user token is required.
AuthMode = Literal["none", "optional", "any", "bearer"]
BodyKind = Literal["none", "json", "multipart"]

_PARAM = re.compile(r"{([a-z_]+)}")


@dataclass(frozen=True)
class Route:
    key: str
    method: HttpMethod
    path: str
    auth: AuthMode = "any"
    scope: Optional[str] = None
    scope_enforced: bool = False
    #: Scopes required in addition to ``scope``.
    extra_scopes: Tuple[str, ...] = ()
    #: Safe to retry after an ambiguous failure (timeout, dropped connection).
    idempotent: bool = False
    body: BodyKind = "none"

    @property
    def required_scopes(self) -> Tuple[str, ...]:
        """Every scope a credential must carry to call this route."""

        return ((self.scope,) if self.scope else ()) + self.extra_scopes

    @property
    def params(self) -> tuple[str, ...]:
        return tuple(_PARAM.findall(self.path))

    def build_path(self, params: Optional[Mapping[str, object]] = None) -> str:
        values = dict(params or {})
        missing = [name for name in self.params if name not in values]
        if missing:
            raise ValueError(f"Missing path parameter(s) for {self.key}: {', '.join(missing)}")

        def substitute(match: re.Match[str]) -> str:
            raw = str(values[match.group(1)])
            if raw == "":
                raise ValueError(f"Path parameter {match.group(1)!r} must not be empty")
            return quote(raw, safe="")

        return _PARAM.sub(substitute, self.path)


def _r(route: Route) -> tuple[str, Route]:
    return route.key, route


# fmt: off
ROUTES: Dict[str, Route] = dict(
    [
        # -- health ------------------------------------------------------------------------
        _r(Route("health.check", "GET", "/healthz", auth="none", idempotent=True)),
        # -- tenants & authentication ------------------------------------------------------
        _r(Route("tenants.register", "POST", "/v1/tenants", auth="none", idempotent=True, body="json")),
        _r(Route("auth.login", "POST", "/v1/auth/login", auth="none", idempotent=True, body="json")),
        _r(Route("auth.setup_password", "POST", "/v1/auth/setup-password", auth="none", idempotent=True, body="json")),
        # -- API keys (bearer tokens only) -------------------------------------------------
        _r(Route("api_keys.list", "GET", "/v1/api-keys", auth="bearer", scope="keys:write", scope_enforced=True, idempotent=True)),
        _r(Route("api_keys.get", "GET", "/v1/api-keys/{key_id}", auth="bearer", scope="keys:write", scope_enforced=True, idempotent=True)),
        _r(Route("api_keys.create", "POST", "/v1/api-keys", auth="bearer", scope="keys:write", scope_enforced=True, body="json")),
        _r(Route("api_keys.rotate", "POST", "/v1/api-keys/{key_id}/rotate", auth="bearer", scope="keys:write", scope_enforced=True, body="json")),
        _r(Route("api_keys.revoke", "DELETE", "/v1/api-keys/{key_id}", auth="bearer", scope="keys:write", scope_enforced=True, idempotent=True)),
        # -- billing -----------------------------------------------------------------------
        _r(Route("subscription.get", "GET", "/v1/subscription", scope="billing:read", scope_enforced=True, idempotent=True)),
        _r(Route("usage.get", "GET", "/v1/usage", scope="usage:read", scope_enforced=True, idempotent=True)),
        # -- catalog -----------------------------------------------------------------------
        _r(Route("products.bulk_upsert", "POST", "/v1/products:bulk-upsert", scope="catalog:write", scope_enforced=True, idempotent=True, body="json")),
        _r(Route("products.list", "GET", "/v1/products", scope="catalog:read", scope_enforced=True, idempotent=True)),
        _r(Route("products.get", "GET", "/v1/products/{external_id}", scope="catalog:read", scope_enforced=True, idempotent=True)),
        _r(Route("products.upsert", "PUT", "/v1/products/{external_id}", scope="catalog:write", scope_enforced=True, idempotent=True, body="json")),
        _r(Route("products.update", "PATCH", "/v1/products/{external_id}", scope="catalog:write", scope_enforced=True, idempotent=True, body="json")),
        _r(Route("products.disable", "POST", "/v1/products/{external_id}:disable", scope="catalog:write", scope_enforced=True, idempotent=True)),
        # -- customer events ---------------------------------------------------------------
        _r(Route("events.create", "POST", "/v1/events", scope="events:write", scope_enforced=True, idempotent=True, body="json")),
        _r(Route("events.create_batch", "POST", "/v1/events/batches", scope="events:write", scope_enforced=True, idempotent=True, body="json")),
        _r(Route("events.list_batches", "GET", "/v1/events/batches", scope="events:read", scope_enforced=True, idempotent=True)),
        _r(Route("events.get_batch", "GET", "/v1/events/batches/{batch_id}", scope="events:read", scope_enforced=True, idempotent=True)),
        # -- datasets ----------------------------------------------------------------------
        _r(Route("datasets.upload", "POST", "/v1/datasets/upload", scope="catalog:write", scope_enforced=True, extra_scopes=("events:write",), body="multipart")),
        _r(Route("datasets.create_snapshot", "POST", "/v1/datasets/snapshots", scope="training:write", scope_enforced=True, body="json")),
        _r(Route("datasets.list_snapshots", "GET", "/v1/datasets/snapshots", scope="training:read", scope_enforced=True, idempotent=True)),
        _r(Route("datasets.get_snapshot", "GET", "/v1/datasets/snapshots/{snapshot_id}", scope="training:read", scope_enforced=True, idempotent=True)),
        # -- model registry & training -----------------------------------------------------
        _r(Route("model_versions.create", "POST", "/v1/model-versions", scope="models:write", scope_enforced=True, body="json")),
        _r(Route("model_versions.list", "GET", "/v1/model-versions", scope="models:read", scope_enforced=True, idempotent=True)),
        _r(Route("model_versions.get", "GET", "/v1/model-versions/{version_id}", scope="models:read", scope_enforced=True, idempotent=True)),
        _r(Route("model_versions.activate", "POST", "/v1/model-versions/{version_id}:activate", scope="models:deploy", scope_enforced=True, idempotent=True)),
        _r(Route("model_versions.archive", "POST", "/v1/model-versions/{version_id}:archive", scope="models:write", scope_enforced=True, idempotent=True)),
        _r(Route("model_versions.rollback", "POST", "/v1/models/{model_id}:rollback", scope="models:deploy", scope_enforced=True, idempotent=True)),
        _r(Route("training_jobs.create", "POST", "/v1/training-jobs", scope="training:write", scope_enforced=True, body="json")),
        _r(Route("training_jobs.list", "GET", "/v1/training-jobs", scope="training:read", scope_enforced=True, idempotent=True)),
        # -- serving status ----------------------------------------------------------------
        _r(Route("deployment.get", "GET", "/v1/deployment", scope="deployments:read", scope_enforced=True, idempotent=True)),
        _r(Route("deployment.replicas", "GET", "/v1/deployment/replicas", scope="deployments:read", scope_enforced=True, idempotent=True)),
        _r(Route("deployment.autoscaling", "GET", "/v1/deployment/autoscaling", scope="deployments:read", scope_enforced=True, idempotent=True)),
        _r(Route("metrics.summary", "GET", "/v1/metrics/summary", scope="metrics:read", scope_enforced=True, idempotent=True)),
        # -- recommendations & feedback ----------------------------------------------------
        _r(Route("recommendations.get", "POST", "/v1/recommendations", scope="recommendations:read", scope_enforced=True, idempotent=True, body="json")),
        _r(Route("recommendations.for_session", "POST", "/v1/recommendations/session", scope="recommendations:read", scope_enforced=True, idempotent=True, body="json")),
        _r(Route("feedback.impression", "POST", "/v1/feedback/impressions", scope="events:write", scope_enforced=True, idempotent=True, body="json")),
        _r(Route("feedback.click", "POST", "/v1/feedback/clicks", scope="events:write", scope_enforced=True, idempotent=True, body="json")),
        _r(Route("feedback.conversion", "POST", "/v1/feedback/conversions", scope="events:write", scope_enforced=True, idempotent=True, body="json")),
        # -- platform administration (PLATFORM_ADMIN_TOKEN bearer) -------------------------
        _r(Route("platform.list_tenants", "GET", "/v1/platform/tenants", auth="bearer", scope="platform:admin", idempotent=True)),
        _r(Route("platform.get_tenant", "GET", "/v1/platform/tenants/{tenant_id}", auth="bearer", scope="platform:admin", idempotent=True)),
        _r(Route("platform.set_tenant_status", "POST", "/v1/platform/tenants/{tenant_id}/status", auth="bearer", scope="platform:admin", idempotent=True, body="json")),
        _r(Route("platform.list_plans", "GET", "/v1/platform/plans", auth="bearer", scope="platform:admin", idempotent=True)),
        _r(Route("platform.set_quota_override", "POST", "/v1/platform/tenants/{tenant_id}/quotas", auth="bearer", scope="platform:admin", idempotent=True, body="json")),
        _r(Route("platform.list_failures", "GET", "/v1/platform/failures", auth="bearer", scope="platform:admin", idempotent=True)),
        _r(Route("platform.list_audit_logs", "GET", "/v1/platform/audit", auth="bearer", scope="platform:admin", idempotent=True)),
        _r(Route("platform.status", "GET", "/v1/platform/status", auth="bearer", scope="platform:admin", idempotent=True)),
    ]
)
# fmt: on


def route(key: str) -> Route:
    try:
        return ROUTES[key]
    except KeyError:  # pragma: no cover - programming error
        raise KeyError(f"Unknown GraphRec route {key!r}") from None
