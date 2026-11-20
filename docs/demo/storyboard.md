# GraphRec + ReelStore Product Demonstration Storyboard

- **Format:** 16:9 live browser recording (`1280×720` H.264 MP4 master at 24 fps, `3.47 MB`; `800×450` GitHub-optimized GIF at 10 fps, `6.84 MB`)
- **Duration:** `29.0 s`
- **Environment:** Live Docker Compose instances of GraphRec (`http://localhost:5180`, API `:8010`) and ReelStore (`http://localhost:5290`, 7,951 films with 7,047 live posters)

## Scene-by-Scene Timeline

| Scene | Time | Visual Content | What Is Demonstrated |
|---|---|---|---|
| **1. Intro Card** | `0:00 – 0:02` | Branded dark-slate intro card | Introduces **GraphRec + ReelStore** and the core stack (`FastAPI`, `PyTorch DGSR`, `Qdrant ANN`, `PostgreSQL RLS`, `React 19`, `Python SDK`). |
| **2. ReelStore Live Walkthrough** | `0:02 – 0:16` | Continuous Playwright recording of ReelStore: homepage posters → Browse scrolling → Film detail page + live watch event → Maya persona switch with live rank-delta badges (`↑5`, `↑1`, `↓4`) and `67 ms · trace` → Insight drawer (`Proof` tab running the live 19-check Capability Proof Battery) | Real storefront browsing, idempotent watch-event ingestion, immediate sequential re-ranking, and glass-box transparency. |
| **3. GraphRec Tenant Console** | `0:16 – 0:20` | Live recording of Tenant Admin workspace (`/models` showing active `v1 DGSR` → `/overview` showing 24h request volume, p95 latency, `7,951` catalog products, and healthy serving/event pipelines) | Tenant-scoped model lifecycle management and live serving telemetry. |
| **4. GraphRec Platform Console** | `0:20 – 0:24` | Live recording of Platform Operator `/admin/tenants` scrolling across isolated tenants | Multi-tenant isolation enforced by PostgreSQL Row-Level Security (RLS) and per-tenant quotas. |
| **5. System Architecture** | `0:24 – 0:27` | Clean vector architecture diagram (`architecture.svg`) | Complete request lifecycle from ReelStore through `graphrec-sdk` and GraphRec API into DGSR, Qdrant, PostgreSQL 17, and Redis 7. |
| **6. Brand Outro** | `0:27 – 0:29` | Closing brand card | Repository structure (`graphrec/`, `reelstore/`, `sdks/python/`) and GitHub URL. |
