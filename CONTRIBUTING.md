# Contributing to GraphRec

Thank you for your interest in contributing to GraphRec and ReelStore.

## Repository Layout

This repository contains two independent projects and a shared client SDK:

- `graphrec/` — Multi-tenant recommendation platform (FastAPI API, DGSR model engine, PostgreSQL/Qdrant/Redis stack, React operator console).
- `reelstore/` — Reference MovieLens film storefront (FastAPI + React) that integrates with GraphRec through the Python SDK.
- `sdks/python/` — Shared typed Python SDK (`graphrec-sdk`).

## Development Workflow

1. Create a feature branch from `main`.
2. Keep changes scoped to the relevant project (`graphrec/`, `reelstore/`, or `sdks/python/`).
3. If you change GraphRec's HTTP API, regenerate the OpenAPI schema and web wire types:
   ```bash
   cd graphrec
   python scripts/export_openapi.py web/openapi.json
   cd web && npm run gen:api
   ```
4. If you change the Python SDK public surface, regenerate the SDK docs reference:
   ```bash
   cd graphrec
   python scripts/build_sdk_docs.py
   python scripts/check_doc_sdk_calls.py
   ```
5. Run the relevant test suites before opening a pull request:
   - **GraphRec backend**: `cd graphrec && python -m pytest -q tests --ignore=tests/e2e`
   - **GraphRec console**: `cd graphrec/web && npm run check:api && npx tsc -b --noEmit && npx vitest run && npm run build`
   - **Python SDK**: `cd sdks/python && python -m pytest -q tests`
   - **ReelStore**: `cd reelstore && python -m pytest -q tests` and `cd reelstore/frontend && npm run check:api && npm run build`

## Code Quality & Conventions

- Follow the formatting rules in `.editorconfig`.
- Python code in `graphrec/` is linted with `ruff check apps graphrec_core scripts tests --select E9,F63,F7,F82,F401`.
- Never commit `.env` files, secrets, model weights (`*.pt`), or local build outputs.
- Keep `graphrec/VERSION`, `graphrec/web/package.json`, and `sdks/python/src/graphrec_sdk/_version.py` synchronized (`tests/test_version_sync.py` enforces this).
