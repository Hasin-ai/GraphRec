<div align="center">

# GraphRec

**A graph-based, multi-tenant recommendation engine for e-commerce**

Plug personalized, session-aware recommendations into any storefront through a simple REST API or Python SDK, powered by Dynamic Graph Neural Networks (DGSR).


[Features](#features) · [Architecture](#architecture) · [Quick start](#quick-start) · [SDK](#python-sdk) · [API](#api-overview) · [Model](#the-model-dgsr)

</div>

---

## Overview

Most small and mid-sized online stores can't afford to build a recommendation system. GraphRec offers one as a service: each store (tenant) sends its catalog and user interactions, and GraphRec returns ranked recommendations that account for **what a user did and when they did it**.

Under the hood, user–item interactions are modeled as a **dynamic graph**, and a reimplementation of **DGSR** (*Dynamic Graph Neural Networks for Sequential Recommendation*, TKDE 2022) learns embeddings that capture both long-term preferences and short-term intent. Embeddings are served from **Qdrant** for fast similarity retrieval.

> Developed as the Software Project Lab III (SPL-3) project at the Institute of Information Technology (IIT), University of Dhaka.

## Features

- **Multi-tenant by design** — isolated data, API keys and models per store
- **Sequential, time-aware recommendations** — powered by a dynamic graph neural network
- **Three access levels** — storefront integration, tenant admin, and platform admin, each with scoped permissions
- **Python SDK** — typed client covering the entire API
- **Vector search** — item/user embeddings stored and queried in Qdrant
- **Admin dashboard** — React UI for managing tenants, catalogs and monitoring
- **Demo storefront** — end-to-end e-commerce demo built on the MovieLens dataset
- **One-command setup** — full stack runs via Docker Compose

## Architecture

```
            ┌──────────────────┐       ┌──────────────────┐
            │  Storefront /    │       │  React Admin     │
            │  Python SDK      │       │  Dashboard       │
            └────────┬─────────┘       └────────┬─────────┘
                     │   REST (API key / JWT)   │
                     └────────────┬─────────────┘
                                  ▼
                      ┌──────────────────────┐
                      │   FastAPI backend    │
                      │  auth · tenants ·    │
                      │  events · recs       │
                      └───┬──────────────┬───┘
                          │              │
                ┌─────────▼───┐   ┌──────▼────────┐
                │ PostgreSQL  │   │    Qdrant     │
                │ tenants,    │   │  embeddings,  │
                │ items,      │   │  ANN search   │
                │ interactions│   └──────▲────────┘
                └─────────┬───┘          │
                          │       ┌──────┴────────┐
                          └──────►│  DGSR model   │
                                  │ (train/infer) │
                                  └───────────────┘
```

## Tech stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI, Python |
| Frontend | React |
| Database | PostgreSQL |
| Vector store | Qdrant |
| Model | DGSR (PyTorch) |
| Deployment | Docker Compose |

## Quick start

### Prerequisites

- Docker and Docker Compose
- Git

### Run the stack

```bash
git clone https://github.com/<your-username>/GraphRec.git
cd GraphRec
cp .env.example .env        # edit secrets and ports as needed
docker compose up -d --build
```

Once running:

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Interactive API docs | http://localhost:8000/docs |
| Admin dashboard | http://localhost:<frontend-port> |
| Qdrant | http://localhost:6333 |

### Environment variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `QDRANT_URL` | Qdrant endpoint |
| `JWT_SECRET` | Secret used to sign admin tokens |
| `<...>` | `<add remaining variables from .env.example>` |

## Python SDK

```bash
pip install -e ./sdk
```

```python
from graphrec import GraphRecClient

client = GraphRecClient(base_url="http://localhost:8000", api_key="YOUR_TENANT_KEY")

# Send an interaction
client.events.track(user_id="u_42", item_id="movie_318", event="view")

# Get recommendations
recs = client.recommendations.for_user("u_42", k=10)
for r in recs:
    print(r.item_id, r.score)
```

The SDK covers all three API surfaces:

- **Storefront** — track events, fetch recommendations
- **Tenant admin** — manage catalog, API keys, training
- **Platform admin** — manage tenants and users

## API overview

| Area | Example endpoints | Auth |
|---|---|---|
| Storefront | `POST /events`, `GET /recommendations/{user_id}` | Tenant API key |
| Tenant admin | `/tenant/items`, `/tenant/keys`, `/tenant/train` | Tenant admin JWT |
| Platform admin | `/admin/tenants`, `/admin/users` | Platform admin JWT |

Full, always-current reference: **`/docs`** (Swagger UI) on a running instance.

## The model: DGSR

GraphRec uses a from-scratch reimplementation of **DGSR**:

1. Interactions become a **dynamic user–item graph**, where every edge carries its timestamp/order.
2. For each user, a sub-graph of their recent history and related items is sampled.
3. **Dynamic graph recurrent layers** propagate information along time-ordered edges, capturing both long-term taste and short-term intent.
4. The resulting embeddings score candidate items; top-K are returned, with Qdrant handling fast retrieval.

The demo is trained on **MovieLens**.

## Project structure

```
GraphRec/
├── backend/          # FastAPI app (routes, services, models)
├── frontend/         # React admin dashboard
├── sdk/              # Python SDK
├── model/            # DGSR training & inference
├── demo/             # E-commerce storefront demo
├── docker-compose.yml
└── README.md
```

## Roadmap

- [ ] Real-time incremental model updates
- [ ] A/B testing for recommendation strategies
- [ ] More recommendation surfaces (similar items, trending)
- [ ] Published SDK on PyPI

## Acknowledgements

- Supervisor: **Dr. Rezvi Shahariar**, Associate Professor, IIT, University of Dhaka
- DGSR: Zhang et al., *Dynamic Graph Neural Networks for Sequential Recommendation*, IEEE TKDE 2022
- Dataset: [MovieLens](https://grouplens.org/datasets/movielens/) by GroupLens Research

## Author

**Hasin Ahmed** — BSSE, IIT, University of Dhaka
## License

`<MIT / your choice>` — see [LICENSE](LICENSE).
