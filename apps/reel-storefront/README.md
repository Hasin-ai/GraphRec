# Reel — a MovieLens film store for the GraphRec demo

A small storefront (FastAPI + React) that uses GraphRec the way a tenant's shop would:
the browser talks only to this server, the server holds the storefront API key and
calls GraphRec through the Python SDK. A right-hand **Insight** drawer shows what
GraphRec did for each click: the 20-film window DGSR reads, GraphRec's event
receipts, the before/after list diff, the raw request/response, and the model card.

```
browser -> /api/reel/* (this server, :5290) -> Python SDK -> GraphRec /v1/* (:8010) -> DGSR (in-process)
```

Data is real throughout: the 7,951 films are the DGSR vocabulary with MovieLens
titles and genres; the three shoppers are real training users with their real
histories. No prices, carts or invented metadata. Posters are genre-coloured tiles
unless `build_data.py --posters` is given a verified `{movieId: url}` file.

## Run

```bash
# 0. GraphRec stack (repository root). The API mounts model_artifacts/ at /artifacts.
docker compose up -d --build

# 1. server deps (Python 3.10+)
cd apps/reel-storefront
python -m venv .venv && .venv/Scripts/activate      # or: source .venv/bin/activate
pip install -e ".[dev]" -e ../../sdks/python

# 2. local data (already committed; rebuild after changing personas)
python scripts/build_data.py

# 3. tenant, catalogue, persona histories, imported checkpoint, activation -> .env
python scripts/bootstrap_reel.py --platform-token <PLATFORM_ADMIN_TOKEN>

# 4. frontend + server
cd frontend && npm install && npm run build && cd ..
uvicorn app.main:app --port 5290          # http://localhost:5290
# (dev: npm run dev in frontend/ -> http://localhost:5291, proxying /api/reel)
```

**Reset the demo** by re-running `bootstrap_reel.py`: it creates a fresh tenant.
Events are permanent and idempotent by design, so a shopper's live history cannot
be rolled back inside one tenant. Persona user ids must stay the real MovieLens ids
(the model only knows those users), so a renamed "fresh" persona would fall back to
the session approximation.

**Rehearse without Docker:** `python -m uvicorn scripts.offline_standin:app --port 5290`
(needs `torch`). It calls the same DGSR serving code on the real checkpoint but is
**not GraphRec** — no tenancy, persistence or eligibility filter. Never present it.

## Run with Docker (separate from the GraphRec stack)

Reel has its own compose project (`apps/reel-storefront/docker-compose.yml`) that joins the
running GraphRec network and calls the API as `http://api:8000`. From the repository root:

```bash
docker compose up -d --build                                    # GraphRec stack
docker compose -f apps/reel-storefront/docker-compose.yml --env-file .env run --rm reel-bootstrap
docker compose -f apps/reel-storefront/docker-compose.yml up -d --build reel
# -> http://localhost:5290        logs: docker compose -f apps/reel-storefront/docker-compose.yml logs -f reel
```

* `reel-bootstrap` (profile `setup`, one-off) reads `PLATFORM_ADMIN_TOKEN` from the root `.env`
  and writes `apps/reel-storefront/.env`. Re-run it to reset the demo (fresh tenant), then
  `up -d reel` again so the new key is picked up.
* Stop or rebuild Reel without touching GraphRec: `docker compose -f apps/reel-storefront/docker-compose.yml down`.
* Different port: `REEL_PORT=8080`. Different GraphRec project name: `GRAPHREC_NETWORK=<name>_default`.
* The `.env` written this way points at `http://api:8000`; for a host-run `uvicorn`, change
  `GRAPHREC_BASE_URL` to `http://localhost:8010`.

## Demo script (measured)

The lists below were produced by `graphrec_core.dgsr.serving` on the real checkpoint
(encode paths and seen-item exclusion as in `apps/api/routes/recommendations.py`).
The live API should return the same order; confirm in a dry run.

| Act | Do | GraphRec strategy | What the measured run showed |
|---|---|---|---|
| 1 | Anonymous home | `popular_fallback` | "Popular right now" (fallback) |
| 1 | Watch *Tarzan* and *The Emperor's New Groove*, press **Update recommendations** | `session` | All 10 animation: *Prince of Egypt, Hercules, 101 Dalmatians, Mulan…* |
| 2 | Switch to **Maya** (carries the two session films into her history) | `personalized` | *Hercules, Prince of Egypt, The Rescuers, Anastasia, Fantasia 2000…* (10/10 animation/children) |
| 3 | Watch *Gattaca*, *Contact*, *Dark City*, then **Update** | `personalized` | 8 of 10 new: *Galaxy Quest, Men in Black, The Fifth Element, Ghost in the Shell, X2, Star Trek: First Contact…* — Sci-Fi share 0% → 50–60% |
| 3 (control) | Instead watch one more animation (*The Lion King*) | `personalized` | 3 of 10 change, still 100% animation |
| 4 | Click a recommended film, press **Watched it** | — | click + conversion feedback linked to the request id |
| 5 | Insight → Sequence → **Replay last event** | — | GraphRec answers `duplicate`; window unchanged |
| 5 | Console: disable a recommended film / roll back the version | `popular_fallback` after rollback | film disappears; shelf shows fallback |

Avoid famous blockbusters for Act 3 (*The Matrix* etc.): they move the list toward
other bestsellers, because most of this model's score is a shared popularity term.
Avoid Horror and Documentary scenarios (the model barely learned them).

What to say: "the event changed the model's input history; the weights are
unchanged and the active version re-ranked." Not: "the model learned".

## What is real here

| Real | Not real / simplified |
|---|---|
| DGSR checkpoint and inference inside GraphRec | Training: the version is an imported offline checkpoint |
| Event ingestion, idempotency (`duplicate`) | "Watched it" = one rating event; the model ignores event type and value |
| Seen-item exclusion, eligibility filter, fallback | Anonymous shoppers use the mean user vector (approximation) |
| Impression / click / conversion feedback | Posters (placeholders), prices (none) |
| Tenant isolation via the API key | Load-tested latency |

## Layout

```
app/            FastAPI server: routes/{session,films,events,recommendations,insight}.py
data/           films.json, personas.json, model_card.json (scripts/build_data.py)
scripts/        build_data.py, bootstrap_reel.py, offline_standin.py (rehearsal only)
frontend/       React 19 + Vite: pages Home / Browse / Film, Insight drawer
tests/          contract tests with a fake GraphRec client
state/          live_events.jsonl (what this storefront sent; feeds the Sequence tab)
```
