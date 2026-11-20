# GraphRec + ReelStore Product Demonstration Storyboard

- **Format:** 16:9 (`1280×720` MP4 master at 24 fps; `960×540` optimized GIF at 12 fps for GitHub README)
- **Target Duration:** ~36 seconds
- **Data & Environment:** Live Docker Compose instances of GraphRec (`http://localhost:5180`, API `:8010`) and ReelStore (`http://localhost:5290`, backed by the MovieLens-32M DGSR checkpoint and 7,047 live movie posters)

## Scene-by-Scene Breakdown

| Scene | Time | Duration | Visual Content | On-Screen Story |
|---|---|---|---|---|
| **1. Title & Hero** | `0:00 – 0:04` | 4.0s | Branded dark-slate intro card cross-fading into the live GraphRec landing page (`/`) | Introduce **GraphRec + ReelStore** — multi-tenant graph-based sequential recommendations powered by DGSR. |
| **2. ReelStore Storefront & Browsing** | `0:04 – 0:10` | 6.0s | Live ReelStore homepage with real posters → Browse page with genre/tag filters → Film detail page showing metadata, tags, and `"More like this"` shelf | Show the real e-commerce storefront experience across 7,951 MovieLens films. |
| **3. Live Personalized Re-Ranking** | `0:10 – 0:17` | 7.0s | Switch shopper to **Maya** (animation history → animation Top-10) → record watches on Sci-Fi films (`Gattaca`, `Contact`, `Dark City`) → click **Update picks** → live shelf shifts to Sci-Fi recommendations | Prove real-time sequential personalization: new interactions immediately shift DGSR's ranking without retraining weights. |
| **4. Glass-Box Insight & Capability Proofs** | `0:17 – 0:23` | 6.0s | Open ReelStore's **Insight** drawer → **Sequence** tab (20-film DGSR window & event receipts) → **Proof** tab showing the live **Capability Proof Battery** results against GraphRec | Show transparent request tracing, idempotency, and verified end-to-end GraphRec + DGSR behavior. |
| **5. Multi-Tenant Operator Console** | `0:23 – 0:29` | 6.0s | Live GraphRec Operator Console (`/models` as tenant admin showing active DGSR checkpoint & metrics → `/admin/tenants` as platform operator showing isolated tenants & statuses) | Demonstrate multi-tenant isolation, forced PostgreSQL Row-Level Security (RLS), and per-tenant model lifecycle management. |
| **6. Technical Architecture** | `0:29 – 0:34` | 5.0s | Clean vector architecture diagram (`architecture.svg`) with animated lifecycle highlight bar | Explain the complete request path: ReelStore → Python SDK → GraphRec API → DGSR + Qdrant + PostgreSQL 17 (RLS) + Redis. |
| **7. Finale & Outro** | `0:34 – 0:38` | 4.0s | Return to the live personalized ReelStore showcase → smooth cross-fade to closing brand card | Reinforce GraphRec + ReelStore identity and repository tagline. |
