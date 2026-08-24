"""Write the published OpenAPI document to disk.

**Two applications, one document.** The control plane (`apps/control_api`) and
the data plane (`apps/inference`) are separate FastAPI apps on separate nodes,
but a customer integrating against this platform is integrating against one
API: they upload a catalogue on N1 and ask for recommendations on N3, with the
same credential model and the same error envelope. Publishing two documents
would make "which file is the contract?" a question, and the `/integration`
page — which documents both halves on one page — would have nothing single to
be checked against.

That check is `frontend/src/routes/integration/Integration.test.tsx`, and it is
why this generator exists in the form it does: the page and the document are the
same artefact by construction, and a row on the page that names a path this file
did not emit fails the frontend suite.

The console's `types.gen.ts` is generated from the output, so it is checked in
rather than fetched from a running server: a type definition that changes
depending on which branch happened to be deployed is not a contract.

Run after changing any router or schema:

    python scripts/gen_openapi.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "openapi.json"

# The two public ports of §9.1, as OpenAPI servers. Templated rather than
# hard-coded to a domain, because the domain is deployment configuration
# (`GRAPHREC_CONSOLE_DOMAIN`, `GRAPHREC_API_DOMAIN`) and a document that names
# one operator's hostname is a document every other operator has to edit.
#
# The data plane's `tenant` variable is not decoration: N3's edge routes on the
# hostname, never on the path or the credential (`deploy/n3/Caddyfile`), so a
# reader who takes the control plane's base URL and appends `/v1/recommendations`
# reaches a 404 and has no way to find out why from the document.
CONTROL_SERVER: dict[str, Any] = {
    "url": "https://{console_domain}",
    "description": "N1 — control plane, catalogue and ingestion.",
    "variables": {
        "console_domain": {
            "default": "api.graphrec.example",
            "description": "GRAPHREC_CONSOLE_DOMAIN.",
        }
    },
}
DATA_SERVER: dict[str, Any] = {
    "url": "https://{tenant}.{api_domain}",
    "description": "N3 — recommendations and feedback. The tenant is the hostname.",
    "variables": {
        "tenant": {
            "default": "your-tenant",
            "description": "Your tenant's subdomain. N3 routes on it.",
        },
        "api_domain": {
            "default": "serve.graphrec.example",
            "description": "GRAPHREC_API_DOMAIN.",
        },
    },
}

# Liveness and readiness are operational, not contractual: they are how systemd
# and Compose decide whether a container is up, and both applications answer
# them on the same two paths with *different* bodies. Publishing one app's shape
# for a path the other app also serves would be a documented lie, so neither is
# published. `docs/RUNBOOKS.md` is where an operator reads about them.
OPERATIONAL = frozenset({"/healthz", "/readyz"})


def _referenced_schemas(node: Any) -> Iterator[str]:
    """Every `#/components/schemas/X` reachable from `node`.

    Merging one app's paths without its schemas produces a document that
    validates as JSON and dangles as OpenAPI. Walking the tree is how the
    inference app's `RecommendationRequestBody` comes along and its
    `HealthResponse` — reachable only from the routes dropped above — does not.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            yield ref.rsplit("/", 1)[1]
        for value in node.values():
            yield from _referenced_schemas(value)
    elif isinstance(node, list):
        for value in node:
            yield from _referenced_schemas(value)


def _closure(schemas: dict[str, Any], roots: set[str]) -> set[str]:
    seen: set[str] = set()
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        pending.extend(_referenced_schemas(schemas[name]))
    return seen


def _merge(control: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    merged = json.loads(json.dumps(control))
    merged["servers"] = [CONTROL_SERVER, DATA_SERVER]
    merged["info"] = {
        **control["info"],
        "title": "GraphRec API",
        "description": (
            "The control plane and the data plane, published together because "
            "they are one integration. Operations are marked with the server "
            "that answers them; there are two, on two hosts."
        ),
    }

    # Every operation carries its own server, so "which host?" is answerable
    # from any single operation rather than only from the document as a whole.
    for path_item in merged["paths"].values():
        for operation in path_item.values():
            operation["servers"] = [CONTROL_SERVER]

    kept = {p: item for p, item in data["paths"].items() if p not in OPERATIONAL}

    collisions = sorted(set(kept) & set(merged["paths"]))
    if collisions:
        msg = (
            f"the control and data planes both serve {collisions}. One document "
            "cannot describe two different responses on one path — give the "
            "data-plane route its own path or add it to OPERATIONAL."
        )
        raise SystemExit(msg)

    for path, item in kept.items():
        for operation in item.values():
            operation["servers"] = [DATA_SERVER]
        merged["paths"][path] = item

    control_schemas = merged.setdefault("components", {}).setdefault("schemas", {})
    data_schemas = data.get("components", {}).get("schemas", {})
    roots = set(_referenced_schemas(kept))
    for name in sorted(_closure(data_schemas, roots)):
        existing = control_schemas.get(name)
        if existing is None:
            control_schemas[name] = data_schemas[name]
        elif existing != data_schemas[name]:
            # `ValidationError` and `HTTPValidationError` are FastAPI's own and
            # identical in both apps, which is why this is an error rather than
            # a last-writer-wins merge: a *differing* shared name means two
            # models with one title, and whichever one lands second silently
            # becomes the generated TypeScript type for both.
            msg = (
                f"schema {name!r} differs between the control and data planes. "
                "Rename one of the models; the generated client cannot have two."
            )
            raise SystemExit(msg)

    return merged


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from apps.control_api.main import create_app as create_control_app
    from apps.inference.main import create_app as create_inference_app
    from graphrec.common.config import Settings

    control = create_control_app(Settings(environment="ci")).openapi()
    # A tenant pin the inference app will never serve. `create_app` refuses to
    # start without one (SRS §6.4) and this generator only walks its routes, so
    # the nil UUID is the honest value: it names no tenant and reaches nothing.
    inference = create_inference_app(
        Settings(environment="ci", tenant_id=uuid.UUID(int=0))
    ).openapi()

    document = _merge(control, inference)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(document['paths'])} paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
