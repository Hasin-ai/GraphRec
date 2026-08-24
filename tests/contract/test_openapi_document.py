"""The OpenAPI document has to build, and nothing else asserts that it does.

Every other test in this repository exercises a route by calling it. None of
them asks FastAPI to *describe* the routes, which is a different operation with
its own failure mode: a dependency annotated with a string forward reference to
a name that exists only for the type checker imports fine, serves requests fine,
and makes `/openapi.json` raise. The console's types are generated from that
document and `/integration` renders it, so the failure surfaces two phases later
as "the code generator crashed" rather than as "this annotation is wrong".

Hence a test that does nothing but ask.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

from apps.control_api.main import create_app as create_control_app
from apps.inference.main import create_app as create_inference_app
from graphrec.common.config import Settings

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "frontend" / "openapi.json"

pytestmark = pytest.mark.contract


def test_the_openapi_document_builds(app) -> None:
    document = app.openapi()
    assert document["openapi"].startswith("3.")
    assert document["paths"], "an API with no described paths"


def test_the_document_is_served(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["paths"]


def test_every_path_is_under_a_version_prefix(app) -> None:
    """No route escapes `/v1` except the ones deliberately outside the API.

    The console builds its client from this document and prefixes nothing, so a
    path that arrived without its version would be requested at the root and
    404 in a way that looks like a routing bug in the front end.
    """
    unversioned = [
        path
        for path in app.openapi()["paths"]
        # `/healthz` and `/readyz` are probes an orchestrator calls, and the
        # JWKS document is consumed by the inference process rather than by a
        # client of the API. None of the three is versioned because none of them
        # is part of the tenant-facing contract that D6 versions.
        if not path.startswith("/v1/")
        and path not in {"/healthz", "/readyz", "/.well-known/jwks.json"}
    ]
    assert not unversioned, f"unversioned paths: {unversioned}"


def test_the_published_document_covers_both_planes() -> None:
    """`frontend/openapi.json` is the *published* contract, and it is not this app.

    The tests above ask the control API to describe itself. The document a
    customer reads is `scripts/gen_openapi.py`'s merge of the control API and
    the inference app, because those two are one integration from outside — and
    the merge is the part with a failure mode. Phase 16 found the previous
    generator emitting the control plane alone, which made `/v1/recommendations`
    absent from the published contract while `/integration` documented it.

    Checked-in rather than generated at test time, so this asserts the file on
    disk is what the code would produce today. A stale file is worse than a
    missing one: `Integration.test.tsx` validates the page against it, so a
    stale document makes a wrong page pass.
    """
    published = json.loads(PUBLISHED.read_text(encoding="utf-8"))
    paths = published["paths"]

    assert "/v1/tenants" in paths or any(p.startswith("/v1/") for p in paths)
    for path in ("/v1/recommendations", "/v1/feedback/clicks"):
        assert path in paths, f"the data plane's {path} is missing from the published document"

    # Every operation says which of the two public ports answers it. Without
    # this a reader has no way to tell N1's paths from N3's, and N3 routes on
    # the hostname.
    for path, item in paths.items():
        for method, operation in item.items():
            servers = operation.get("servers")
            assert servers, f"{method.upper()} {path} names no server"


def test_the_published_document_is_current() -> None:
    """Regenerating must be a no-op, byte for byte."""
    spec = importlib.util.spec_from_file_location(
        "gen_openapi", ROOT / "scripts" / "gen_openapi.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_openapi"] = module
    spec.loader.exec_module(module)

    control = create_control_app(Settings(environment="ci")).openapi()
    inference = create_inference_app(
        Settings(environment="ci", tenant_id=uuid.UUID(int=0))
    ).openapi()
    expected = json.dumps(module._merge(control, inference), indent=2, sort_keys=True) + "\n"

    assert expected == PUBLISHED.read_text(encoding="utf-8"), (
        "frontend/openapi.json is stale — run `python scripts/gen_openapi.py` "
        "(and `scripts/gen-client.sh`, which regenerates the console's types from it)"
    )
