# GraphRec SDKs

Official client libraries for the GraphRec API. Both SDKs encode the same route table, error codes, retry rules, body-size splitting and deterministic event identifiers, and both are checked against the FastAPI source in this repository by their contract tests.

| SDK | Package | Runtime | Docs |
|---|---|---|---|
| Python | `graphrec-sdk` (`import graphrec_sdk`) | Python ≥ 3.9, `httpx`, `pydantic` 2 | [python/README.md](python/README.md) |
| TypeScript / JavaScript | `@graphrec/sdk` | Node ≥ 18.17 (global `fetch`), no dependencies | [typescript/README.md](typescript/README.md) |

Design notes and the analysis of the API they target are in [python/ANALYSIS.md](python/ANALYSIS.md).

## Verifying against a live stack

```bash
docker compose up --build -d
python sdks/python/examples/end_to_end_smoke.py --base-url http://localhost:8010
cd sdks/typescript && npm install && npm run smoke -- --base-url http://localhost:8010
```
