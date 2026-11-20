"""Export the API's OpenAPI schema, or check that a committed copy is current.

The FastAPI schema is the single source of truth for the HTTP contract. The web
console's wire types are generated from the committed copy, so CI fails when the
API changes without regenerating it:

    python scripts/export_openapi.py web/openapi.json           # write
    python scripts/export_openapi.py --check web/openapi.json   # CI gate
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def render() -> str:
    # The schema does not depend on secrets, but settings validate on import.
    os.environ.setdefault("JWT_SIGNING_SECRET", "openapi-export-" + "x" * 32)
    from apps.api.main import app

    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true", help="fail if the file differs from the live schema")
    args = parser.parse_args()
    current = render()
    if args.check:
        if not args.path.is_file() or args.path.read_text(encoding="utf-8") != current:
            print(f"{args.path} is out of date. Run: python scripts/export_openapi.py {args.path} "
                  "and regenerate the web types (npm run gen:api in web).", file=sys.stderr)
            return 1
        print(f"{args.path} matches the API schema.")
        return 0
    args.path.write_text(current, encoding="utf-8")
    print(f"Wrote {args.path}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
