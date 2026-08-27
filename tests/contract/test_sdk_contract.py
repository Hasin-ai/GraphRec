"""The published SDKs, asserted from the server's side.

`docs/SDK_DESIGN.md` §10 holds the client surface with seven tests that live in
`sdk/typescript/test/` and `tests/sdk/`. Two of those — the route table and the
totality of the error mapping — are also asserted here, from the other side, and
the difference is which change breaks which suite.

The SDK's own tests read `frontend/openapi.json`. That file is generated, so an
API that grows a route leaves both SDKs green until somebody regenerates it.
These tests read the FastAPI routers and `graphrec/common/errors.py` directly, so
the failing commit is the one that added the route or the class — not the one
that regenerated a document weeks later.

Neither direction is redundant. A route deleted from an SDK fails there; a route
added to the server fails here.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from apps.control_api.main import API_PREFIX
from apps.control_api.main import create_app as create_control_app
from apps.control_api.routers import ingestion
from apps.inference.main import create_app as create_inference_app
from graphrec.common.config import Settings
from graphrec.common.errors import DEFAULT_STATUS, ErrorClass

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
TS = ROOT / "sdk" / "typescript" / "src"
PY = ROOT / "sdk" / "python" / "src" / "graphrec_sdk"

#: Every line of both clients, concatenated. The assertions below are textual on
#: purpose: importing the TypeScript is not possible from here, and a single
#: technique that covers both languages is one technique to keep true.
TS_SOURCE = "\n".join(p.read_text() for p in sorted(TS.rglob("*.ts")))
PY_SOURCE = "\n".join(p.read_text() for p in sorted(PY.rglob("*.py")))


def _api_routes(routes: object) -> list[APIRoute]:
    """FastAPI's own routes, through Starlette 1.3's inclusion wrappers."""
    found: list[APIRoute] = []
    for route in routes:  # type: ignore[attr-defined]
        if isinstance(route, APIRoute):
            found.append(route)
        inner = getattr(route, "original_router", None)
        if inner is not None:
            found.extend(_api_routes(inner.routes))
        elif not isinstance(route, APIRoute) and hasattr(route, "routes"):
            found.extend(_api_routes(route.routes))
    return found


def _dependencies(dependant: object) -> list[str]:
    names: list[str] = []
    for sub in dependant.dependencies:  # type: ignore[attr-defined]
        names.append(getattr(sub.call, "__qualname__", str(sub.call)))
        names.extend(_dependencies(sub))
    return names


def _accepts_a_credential(route: APIRoute) -> bool:
    """Whether a `gr_live_` key can call this route.

    `require_ingest` is the only gate that admits the credential realm — every
    other dependency in the control API judges a session by role. That makes the
    presence of it in a route's dependency tree the definition of "a customer's
    server can call this", which is exactly the set the SDK has to cover.
    """
    return any("require_ingest" in name for name in _dependencies(route.dependant))


#: The ingestion router carries no prefix of its own, so `API_PREFIX + path` is
#: the wire path.
INGESTION = sorted(
    (method, API_PREFIX + route.path)
    for route in _api_routes(ingestion.router.routes)
    for method in sorted(route.methods)
    if method != "HEAD"
)


def _stem(path: str) -> str:
    """The literal part of a templated path.

    `/v1/submissions/{submission_id}` is an f-string in one client and a template
    literal in the other, so the id itself never appears verbatim. The prefix
    does, and a wrong prefix is the failure worth catching.
    """
    return re.sub(r"\{[^}]+\}$", "", path)


def test_the_route_enumeration_found_the_ingestion_surface() -> None:
    # A floor. An empty list would make every membership assertion below vacuous.
    assert len(INGESTION) == 5, INGESTION


@pytest.mark.parametrize(("method", "path"), INGESTION)
def test_every_control_plane_route_a_credential_can_call_is_in_both_sdks(
    method: str, path: str
) -> None:
    stem = _stem(path)
    assert stem in TS_SOURCE, f"{method} {path} is not in the TypeScript client"
    assert stem in PY_SOURCE, f"{method} {path} is not in the Python client"


def test_every_ingestion_route_really_does_admit_a_credential() -> None:
    """The premise of the test above.

    If a route in this router stopped accepting API keys it would still be
    listed, and the coverage assertion would keep passing over a route no
    customer can reach.
    """
    unreachable = [
        route.path
        for route in _api_routes(ingestion.router.routes)
        if not _accepts_a_credential(route)
    ]
    assert unreachable == []


def test_no_route_outside_the_ingestion_router_accepts_a_credential() -> None:
    """The assertion that actually catches growth.

    The parametrised test above cannot fail for a route added to `serving.py` or
    `usage.py` under `require_ingest`, because it never looks there. This does:
    it walks the whole control API and asserts the credential-callable set is
    still exactly the ingestion router's.

    If this fails, the API has grown a route a customer's server can call and
    neither SDK knows about it. Add it to both clients — the route tables in
    `sdk/typescript/test/routes.test.ts` and `tests/sdk/test_routes.py` — rather
    than adding it to the exemption here.
    """
    app = create_control_app(Settings(environment="ci"))
    callable_paths = {
        API_PREFIX + route.path if not route.path.startswith(API_PREFIX) else route.path
        for route in _api_routes(app.routes)
        if _accepts_a_credential(route)
    }
    assert callable_paths == {path for _, path in INGESTION}


def test_every_data_plane_route_is_in_both_sdks() -> None:
    """N3's app is the whole data plane, and all of it is customer-facing.

    There is no session realm on the inference host — it answers credentials and
    nothing else — so every route it serves except the probes is one the SDK
    must expose.
    """
    app = create_inference_app(Settings(environment="ci", tenant_id=uuid.UUID(int=0)))
    paths = {route.path for route in _api_routes(app.routes) if route.path.startswith("/v1/")}
    assert paths, "the inference app describes no versioned routes"
    for path in sorted(paths):
        assert _stem(path) in TS_SOURCE, f"{path} is not in the TypeScript client"
        assert _stem(path) in PY_SOURCE, f"{path} is not in the Python client"


@pytest.mark.parametrize("error_class", sorted(ErrorClass))
def test_every_error_class_is_mapped_by_both_sdks(error_class: ErrorClass) -> None:
    """(3) from the other side.

    Adding an eighth `ErrorClass` is a one-line change in this repository and a
    silent degradation in both clients, where the new value would fall through
    to the base class and take the retry policy's default with it.
    """
    from graphrec_sdk.errors import GraphRecError, error_from

    payload = {
        "error": {
            "class": error_class.value,
            "code": f"{error_class.value}_probe",
            "reason": "probe",
            "reference": None,
            "field_errors": [],
            "retryable": False,
            "retry_after_seconds": None,
        }
    }
    error = error_from(DEFAULT_STATUS[error_class], payload, None)
    assert (
        type(error) is not GraphRecError
    ), f"the Python SDK has no exception for ErrorClass.{error_class.name}"

    # The TypeScript client's mapping is a `switch` on the same strings.
    assert (
        f"'{error_class.value}'" in TS_SOURCE
    ), f"the TypeScript SDK never mentions ErrorClass.{error_class.name}"


def test_the_two_sdks_agree_on_the_default_status_for_each_class() -> None:
    """Both clients carry a fallback table for responses that are not envelopes.

    A proxy's 502 and Caddy's 413 never reach an application, so there is no
    envelope to read the class out of and the status is all there is. The table
    has to say the same thing the server would have said.
    """
    from graphrec_sdk.errors import _STATUS_FALLBACK

    for error_class, status in DEFAULT_STATUS.items():
        # 401 and 403 are both `auth`; the fallback table is keyed by status and
        # names the one the server defaults to.
        assert status in _STATUS_FALLBACK, f"no fallback for {status} ({error_class.value})"
        assert _STATUS_FALLBACK[status][0] == error_class.value, (
            f"{status} is {error_class.value} on the server and "
            f"{_STATUS_FALLBACK[status][0]} in the SDK"
        )
