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

import pytest

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
