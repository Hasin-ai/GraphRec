# GraphRec SDK

The official client library for the GraphRec API is the Python SDK in [`python/`](python/README.md):

| Package | Import | Runtime |
|---|---|---|
| `graphrec-sdk` | `import graphrec_sdk` | Python ≥ 3.9, `httpx`, `pydantic` 2 |

It covers every API route, grouped by audience (`client.storefront`, `client.tenant`, `client.platform`). The SDK is checked against the FastAPI source in this repository by `python/tests/test_contract.py`, and against the running app by `tests/integration/test_sdk_live.py`.

Design notes and the analysis of the API it targets are in [python/ANALYSIS.md](python/ANALYSIS.md).

## Verifying against a live stack

```bash
docker compose up --build -d
python sdks/python/examples/end_to_end_smoke.py --base-url http://localhost:8010
pytest tests/integration/test_sdk_live.py      # needs the Compose database and Qdrant
```
