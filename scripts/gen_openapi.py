"""Write the control API's OpenAPI document to disk.

The console's `types.gen.ts` is generated from this file, so it is checked in
rather than fetched from a running server: a type definition that changes
depending on which branch happened to be deployed is not a contract.

Run after changing any router or schema:

    python scripts/gen_openapi.py

The document is also what `/integration` documents and what Phase 16 publishes,
so the three are the same artefact by construction rather than by discipline.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "openapi.json"


def main() -> int:
    sys.path.insert(0, str(ROOT))
    from apps.control_api.main import create_app
    from graphrec.common.config import Settings

    app = create_app(Settings(environment="ci"))
    document = app.openapi()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(document['paths'])} paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
