# GraphRec: Multi-Tenant Recommendation Platform as a Service

**Final consolidated architecture and implementation guide**  
**Revision:** 1.1 — 2026-08-01  
**Architecture target:** university semester project, one student, CPU-first, Docker Compose locally, optional three-node k3s demonstration.

This document reconciles the submitted architecture alternatives and supersedes earlier drafts. Where the drafts conflicted, the selected decision favors tenant safety, deterministic behavior, and semester feasibility.

**Revision 1.1 research synthesis:** the provided recommendation-system podcast and Aman.ai RecSys design notes reinforce an explicit offline/online boundary and a funnel of **candidate retrieval -> eligibility filtering -> DGSR scoring -> deterministic ordering**. This revision keeps DGSR as the only learned personalized model in the MVP, adds multi-source candidate retrieval, versioned feature contracts, stage-specific evaluation and observability, selective precomputation, and stable re-ranking rules. It deliberately does **not** add a dedicated feature-store service, a second learned ranker, online training, or mandatory ANN infrastructure.

---

## 1. Executive summary

GraphRec is a small multi-tenant SaaS platform that lets independent e-commerce businesses ingest customer-product interactions, train isolated recommendation models, activate or roll back model versions, and request real-time Top-N recommendations through a Python SDK.

The semester MVP uses a **modular FastAPI backend**, **PostgreSQL shared schema with `tenant_id` and forced Row-Level Security**, **RabbitMQ with Celery** for asynchronous workloads, **Redis** only for fast ephemeral state such as caching, rate limits, semaphores, and distributed locks, **RustFS** for model artifacts, and **PyTorch plus PyTorch Geometric** for recommendation models. PostgreSQL is the durable control plane: API state changes and asynchronous work are coupled through a transactional outbox so a committed job cannot be silently lost when the broker is unavailable.

For serving, the MVP selects **one Kubernetes Deployment and Service per active tenant**. Each deployment is pinned to exactly one tenant and one active model version. This is less resource-efficient than a shared multi-model pool, but it is the most understandable and defensible way to demonstrate runtime tenant isolation, independent model versioning, and Tenant A scaling from one replica to two while Tenant B remains at one replica.

A lightweight **Model Deployment Controller** reconciles PostgreSQL deployment state with Kubernetes Deployments, Services, Secrets, and HPAs. Kubernetes HPA is the sole normal writer of `Deployment.spec.replicas`; the controller never runs a competing replica loop. The required MVP scale demonstration uses CPU utilization as the dependable metric and may add one per-pod in-flight custom metric only after the CPU path is stable. An init container downloads a tenant-scoped artifact, validates its checksum, and exposes it to the inference process through an `emptyDir` volume. Readiness is reported only after deserialization, warm-up inference, and tenant/version verification.

Online recommendation requests remain synchronous. Redis-backed per-tenant admission, bounded local inference waiters, strict timeouts, and safe fallbacks absorb only short bursts while new replicas start. Slow work such as event processing, dataset preparation, graph construction, training, evaluation, deployment reconciliation, usage aggregation, and housekeeping runs through Celery queues.

The recommendation path is explicitly split into offline and online responsibilities. Offline jobs build the tenant snapshot, DGSR weights, user/item mappings, item embeddings, bounded item-neighbor artifacts, popularity/category lists, and a versioned feature schema. Online requests assemble the current user/session representation, retrieve a broad candidate union, filter ineligible products, batch-score the survivors with the **same DGSR model**, and apply a deterministic ordering policy for diversity, freshness, exclusions, and stable tie-breaking. Retrieval-source scores are never treated as final comparable ranks.

The MVP should be presented as a **limited-capacity educational system**, not an enterprise high-availability platform. On three small nodes it can realistically demonstrate two to four active tenants, one training job at a time, and roughly four to six total inference replicas, subject to measured model memory and node capacity.

---

## 2. Source-derived project requirements

The design must demonstrate all of the following without becoming an oversized enterprise platform:

- Multiple e-commerce tenants with isolated administrators, credentials, users, products, events, jobs, datasets, graph data, models, deployments, metrics, quotas, usage, and audit history.
- Tenant-specific model training and tenant-specific model artifacts, even when model architecture is shared.
- A simplified DGSR-inspired graph and sequential recommendation model using user nodes, item nodes, typed time-ordered interaction edges, bounded graph sampling, and next-item link prediction.
- Model registration, activation, rolling deployment, rollback, and independent replica scaling.
- Runtime scaling based on measurable demand such as CPU, request rate, concurrent requests, bounded queue depth, latency, and timeouts; never merely on registered-user count.
- Queue-based asynchronous processing with retries, idempotency, dead-letter handling, per-tenant fairness, and global training limits.
- Real-time synchronous recommendation inference with bounded burst buffering, backpressure, timeouts, 429/503 responses, and safe fallback behavior.
- PostgreSQL shared-schema multi-tenancy with `tenant_id`, RLS, practical DDL, constraints, indexes, and tenant-isolation tests.
- CPU-first Docker Compose and an optional k3s deployment limited to three small nodes.
- Prometheus/Grafana observability, quotas, mocked pricing plans, usage metering, a Python SDK, testing, and a twelve-week implementation plan.

Hard technology constraints are FastAPI, PostgreSQL, Redis, Redis or RabbitMQ as broker, PyTorch, PyTorch Geometric or DGL, S3-compatible object storage, Docker, Docker Compose, and at most three Kubernetes nodes. Real-time online training, Kafka, Spark, Flink, Kubeflow, full KServe, namespace-per-tenant, database-per-tenant, graph databases, and dozens of microservices are outside the MVP.

---

## 3. Assumptions and scope boundaries

### Assumptions

1. The demonstration begins with two tenants and may grow to at most four active tenants on the three-node cluster.
2. Each active model is intentionally bounded and is expected to fit within an inference pod request of roughly 768 MiB; the actual loaded footprint and cold-start time are measured before setting cluster limits. No fixed model-size claim is treated as guaranteed.
3. Product catalogs and event volumes are educational-scale. The online path always uses a four-stage funnel. For small catalogs, candidate retrieval uses exact batched dot products over DGSR item embeddings; for larger demo catalogs it uses precomputed DGSR item-neighbor lists and bounded source quotas. A FAISS/HNSW-style ANN index is an optional future optimization, not a semester dependency.
4. Training is batch or scheduled and CPU-only. Only one global training task executes at a time in the MVP.
5. Each active tenant keeps at least one warm inference replica. Scale-to-zero is future work.
6. PostgreSQL, RabbitMQ, Redis, and RustFS may run inside the demo cluster, but this is explicitly not production-grade availability.
7. External customer and product identifiers are tenant-local strings; internal primary keys are UUIDs.
8. All timestamps use `TIMESTAMPTZ` in UTC.
9. The inference API target is a demonstrable service objective, for example P95 below 300 ms at supported load, not a contractual SLA.
10. Model quality is evaluated offline. Online CTR and conversion are informational and are not used for automatic activation in the MVP.
11. GraphRec does not deploy a separate feature-store product. Training and serving share one versioned `FeatureBuilder` library and `feature_schema.json`; durable features live in PostgreSQL/RustFS and short-lived counters or session context live in Redis/request payloads.

### Explicitly out of scope for the semester MVP

- Multi-region deployment, managed databases, production billing, GPU scheduling, streaming online learning, automatic feature stores, advanced canary analysis, service mesh, distributed tracing, predictive autoscaling, and full disaster recovery.
- Arbitrary customer-supplied model code or pickle artifacts.
- Hundreds of simultaneously active tenant deployments.
- Strong high availability after loss of a stateful node.

---

## 4. Final recommended architecture

### Architectural style

Use a **modular monolith plus specialized processes** from one repository and mostly one shared Python package:

- `api`: FastAPI public/admin API and synchronous inference gateway.
- `worker-general`: Celery worker for event processing, data preparation, evaluation, usage, and housekeeping.
- `worker-training`: Celery worker with concurrency 1 for graph construction and training.
- `scheduler-outbox`: a small database-backed scheduler that publishes transactional-outbox rows and emits scheduled retraining, usage, and cleanup tasks. It is not dependent on an in-memory API background task.
- `deployment-controller`: periodic reconciler using the Kubernetes Python client.
- `inference`: a tenant-pinned FastAPI process deployed separately for each active tenant.

This avoids dozens of independently deployed microservices while keeping failure domains and resource-heavy workloads separate.

### Storage and infrastructure

- **PostgreSQL:** system of record, RLS enforcement, model registry, deployment state, usage ledger, audit records, task records, and transactional outbox.
- **RabbitMQ:** Celery broker for small control messages, queue routing, publisher confirms, consumer acknowledgements, retry/dead-letter mechanics, and bounded priorities. The single-broker demo is durable but not highly available.
- **Redis:** API rate counters, bounded distributed semaphores, caching, idempotency fast path, training locks, short-lived deployment locks.
- **RustFS:** dataset snapshots, model weights, mappings, manifests, and archived artifacts.
- **Prometheus/Grafana:** operational and tenant-level monitoring.

### Serving strategy decision

| Strategy | Strength | Weakness | MVP decision |
|---|---|---|---|
| Dedicated Deployment per tenant | Strong runtime separation; independent HPA; simple version pinning | More pods and Kubernetes objects | **Selected** |
| Shared multi-model pool | Better utilization | Complex cache isolation, placement, eviction, and independent scaling | Future |
| Hybrid | Best long-term trade-off | Requires promotion/demotion controller and two serving paths | Future production |

The dedicated design is feasible because the MVP supports only a small number of active tenants. It gives the cleanest demonstration that Tenant A may have two replicas of Model A v1 while Tenant B retains one replica of Model B v3.

### Offline/online boundary and recommendation funnel

The system follows a batch-first, real-time-serving design. "Batch-first" does not mean the public recommendation call is asynchronous; it means all expensive graph construction, model training, embedding export, candidate-index construction, and bulk feature computation happen offline. The online pod performs only bounded work with immutable versioned artifacts.

| Stage | Offline responsibility | Online responsibility | MVP implementation |
|---|---|---|---|
| Retrieval | Export DGSR item embeddings, exact-scan matrix, item-neighbor lists, popularity/category/content lists | Build current user/session query vector and retrieve a broad union | Exact vectorized top-K plus bounded precomputed sources; ANN is future |
| Filtering | Define/version eligibility schema | Remove wrong-tenant, disabled, unavailable, excluded, recently purchased/impressed items | In-memory/Redis tenant active-catalog bitmap and request constraints; fail closed |
| Scoring | Train DGSR next-item objective and store feature schema | Batch-score the filtered candidates with DGSR | One learned scorer only; source scores are features/debug data, never final ranks |
| Ordering | Version business policy and defaults | Select final Top-N with stable tie-breaks, diversity/category caps, optional bounded freshness/seasonality boosts | Deterministic Python policy; no learned re-ranker in MVP |

Candidate retrieval merges several independent sources because no single source handles every case:

1. DGSR personalized vector retrieval from the current long/short user representation.
2. DGSR item-to-item neighbors seeded by the user's most recent products.
3. Tenant recent-popular and category-popular lists.
4. Optional metadata/content candidates for new items when category, brand, tags, or text attributes exist.
5. Explicit merchandising candidates only when the tenant enables a bounded, audited rule.

Each source has a fixed quota and emits internal product IDs plus source metadata. The union is deduplicated and capped, initially around 100-300 candidates. Candidate-source scores are not numerically comparable; the DGSR scoring stage assigns the common relevance score.

### Feature consistency without a feature-store service

A shared `graphrec_core.features.FeatureBuilder` is called by snapshot generation, evaluation replay, and inference. Every artifact records the feature schema version, normalization statistics, vocabulary/mapping checksums, missing-value policy, and code Git SHA. CI runs train/serve parity fixtures to prevent training-serving skew. PostgreSQL, RustFS, Redis, and request context provide storage; they do not constitute a separately operated feature-store platform.

### Queue decision

| Option | Benefits | Limitations | Decision |
|---|---|---|---|
| Redis + Celery | Few components; simple local setup | Shared memory pressure with cache/locks; weaker broker semantics for a teaching demo | Not selected |
| RabbitMQ + Celery | Separate failure domain from Redis; mature routing, publisher confirms, consumer acknowledgements, priorities, dead-letter exchanges, and worker controls | Adds one service and must be operated explicitly | **Selected** |
| Redis + RQ/Dramatiq | Simple APIs | Less convenient workflow composition and operational tooling for this pipeline | Not selected |

Redis remains required, but RabbitMQ is the task broker so broker memory is not shared with rate limits, caches, and locks.

### Autoscaling decision

- The deployment controller creates a separate `autoscaling/v2` HPA for each tenant Deployment.
- **MVP authority:** HPA is the only normal writer of `Deployment.spec.replicas`. The controller writes model/version templates and HPA policy, but not the live replica count.
- **Required demonstration metric:** CPU utilization, initially 65%, with CPU requests set on every inference container and Metrics Server enabled.
- **Optional extension:** one per-pod custom metric such as `graphrec_inference_inflight`. Add it only after a Prometheus Adapter path is working and tested; HPA will choose the largest replica recommendation across configured metrics.
- P95/P99 latency, queue wait, timeout rate, and request rate remain mandatory monitoring and load-test signals. They are not required active scaling inputs for the semester demonstration.
- Never run an independent custom scaler against the same Deployment while HPA is enabled.

---

## 5. Why this architecture is feasible for a semester project

1. **One repository and shared domain model:** API, workers, controller, and inference images reuse Pydantic models, SQLAlchemy repositories, security code, and observability helpers.
2. **Few infrastructure products:** PostgreSQL, RabbitMQ, Redis, RustFS, Prometheus, and Grafana are enough. No Kafka, separate feature-store service, service mesh, Kubeflow, or graph database is required.
3. **Batch graph generation:** Graphs are created from PostgreSQL snapshots during training; no real-time graph database or streaming graph mutation is needed.
4. **Bounded recommendation model:** A one- or two-layer PyG model, recent-neighbor sampling, and CPU inference are implementable by one student.
5. **Dedicated tenant deployments are explicit:** They consume more pods, but avoid writing a sophisticated multi-model cache scheduler.
6. **Kubernetes is an optional final phase:** Most business logic works in Docker Compose. k3s is used to demonstrate placement, readiness, rolling updates, and HPA.
7. **Limited concurrency:** One global training worker and small replica caps protect the cluster and reduce orchestration complexity.
8. **Progressive delivery:** Popularity first, BPR second, simplified DGSR third. The platform remains demonstrable even if the GNN underperforms.

Practical capacity is not a fixed tenant count. With three nodes of roughly 4 vCPU and 8 GiB RAM each, the project should reserve capacity for stateful services and expect approximately two to four active tenants with one warm replica each, plus one temporary scale-out replica and one constrained training worker. Load tests and measured model size determine the actual cap.

---

## 6. System context diagram

```mermaid
flowchart LR
    TA[Tenant A e-commerce app]
    TB[Tenant B e-commerce app]
    ADM[Tenant administrators]
    SDK[GraphRec Python SDK]
    GR[GraphRec SaaS]
    OBJ[(RustFS / S3 storage)]
    PG[(PostgreSQL)]
    MQ[(RabbitMQ)]
    RD[(Redis)]
    OBS[Prometheus and Grafana]
    K8S[k3s cluster]

    TA --> SDK
    TB --> SDK
    SDK -->|products, events, training, recommendations| GR
    ADM -->|admin API and dashboard| GR
    GR --> PG
    GR --> MQ
    GR --> RD
    GR --> OBJ
    GR --> K8S
    K8S --> OBS
    GR --> OBS
```

The SDK authenticates with a tenant API key. GraphRec derives the tenant from the credential; the caller never selects an arbitrary tenant identifier.

---

## 7. Component diagram

```mermaid
flowchart TB
    subgraph Public
        SDK[Python SDK]
        ADMIN[Admin client]
    end

    subgraph Platform[GraphRec platform namespace]
        API[FastAPI API and inference gateway]
        GEN[General Celery worker]
        TRAIN[Training Celery worker concurrency 1]
        BEAT[Scheduler and outbox publisher]
        CTRL[Model Deployment Controller]
        RABBIT[(RabbitMQ)]
        REDIS[(Redis)]
        POSTGRES[(PostgreSQL with RLS)]
        RUSTFS[(RustFS)]
        PROM[Prometheus]
        GRAF[Grafana]
    end

    subgraph TenantA[Tenant A serving]
        SVA[Service tenant-a]
        A1[Replica A1 Model A v1<br/>retrieve-filter-score-order]
        A2[Replica A2 Model A v1<br/>retrieve-filter-score-order]
    end

    subgraph TenantB[Tenant B serving]
        SVB[Service tenant-b]
        B1[Replica B1 Model B v3<br/>retrieve-filter-score-order]
    end

    SDK --> API
    ADMIN --> API
    API --> POSTGRES
    API --> REDIS
    API --> SVA
    API --> SVB
    RABBIT --> GEN
    RABBIT --> TRAIN
    BEAT --> POSTGRES
    BEAT --> RABBIT
    GEN --> POSTGRES
    GEN --> RUSTFS
    TRAIN --> POSTGRES
    TRAIN --> RUSTFS
    CTRL --> POSTGRES
    CTRL --> RUSTFS
    CTRL --> SVA
    CTRL --> SVB
    SVA --> A1
    SVA --> A2
    SVB --> B1
    PROM --> API
    PROM --> GEN
    PROM --> TRAIN
    PROM --> A1
    PROM --> A2
    PROM --> B1
    GRAF --> PROM
```

---

## 8. Component responsibility table

| Component | Main responsibility | Persistent state | Scaling approach |
|---|---|---|---|
| FastAPI API/gateway | Authentication, tenant resolution, CRUD, quota checks, synchronous recommendation routing | None beyond DB/Redis | 1-2 replicas |
| General Celery worker | Event normalization, snapshot preparation, evaluation, registration, usage, cleanup | Task records in PostgreSQL | Fixed 1 for MVP |
| Training Celery worker | Graph construction, DGSR training, embedding export, item-neighbor/precomputed candidate artifacts | Checkpoints/artifacts in RustFS | Fixed concurrency 1 |
| Scheduler/outbox publisher | Publish committed outbox rows; scheduled retraining, usage aggregation, cleanup | Outbox and schedule metadata in PostgreSQL | Single replica with advisory/Redis leader lease |
| Deployment controller | Reconcile active model into Deployment, Service, HPA; record rollout state | Deployment tables in PostgreSQL | Single leader with Redis lock |
| Tenant inference pod | Load one tenant/version; assemble context; retrieve, filter, DGSR-score in a batch, and deterministically order Top-N | Read-only artifact copy in `emptyDir`; short-lived caches only | Per-tenant HPA |
| PostgreSQL | Durable source of truth and RLS enforcement | All relational data | Single instance for demo |
| RabbitMQ | Asynchronous task delivery and dead-lettering | Durable queues | Single instance for demo |
| Redis | Cache, locks, rate counters, semaphores, idempotency fast path | Ephemeral with optional AOF | Single instance for demo |
| RustFS | Model and snapshot object storage | Persistent volumes | Single instance for demo |
| Prometheus/Grafana | Metrics, dashboards, alerts | Prometheus volume | Single instance each |

---

## 9. End-to-end data flow

### Product and event flow

1. Tenant backend initializes `GraphRecClient` with its API key.
2. API hashes and resolves the key to one tenant and constructs an authenticated tenant context.
3. API starts a database transaction and executes `SET LOCAL app.current_tenant_id = '<uuid>'`.
4. Product upserts are written synchronously with tenant-local unique constraints.
5. Interaction events are validated, deduplicated by `(tenant_id, event_id)`, and stored append-only. The same transaction inserts `task_records` and an `outbox_events` row.
6. The API commits before returning `202`. A standalone outbox publisher sends the small task reference to RabbitMQ with publisher confirmation and then records `published_at`; large payloads remain in PostgreSQL or RustFS.
7. Workers re-load the task record, atomically claim it, verify the envelope tenant matches the durable task tenant, set their own RLS context, and process the event.

### SDK event-ingestion sequence diagram

```mermaid
sequenceDiagram
    participant Shop as Tenant e-commerce backend
    participant SDK as GraphRec SDK
    participant API as FastAPI API
    participant Redis
    participant PG as PostgreSQL RLS
    participant Outbox as Outbox publisher
    participant MQ as RabbitMQ
    participant Worker as Event worker

    Shop->>SDK: track_events(batch, idempotency_key)
    SDK->>API: POST /v1/events/batches + API key
    API->>API: Resolve tenant from API key
    API->>Redis: Rate and quota pre-check
    API->>PG: BEGIN; SET LOCAL tenant; insert batch/events/task/outbox
    PG-->>API: COMMIT accepted and duplicate counts
    API-->>SDK: 202 batch status
    Outbox->>PG: Claim unpublished row with SKIP LOCKED
    Outbox->>MQ: Publish tenant-scoped task reference
    MQ-->>Outbox: Publisher confirm
    Outbox->>PG: Set published_at
    MQ->>Worker: Deliver task
    Worker->>PG: Verify task tenant; SET LOCAL tenant
    Worker->>PG: normalize and mark processed
    Worker-->>MQ: ACK
```

### Training and serving flow

1. A permitted tenant administrator requests training.
2. The API enforces the monthly job quota and, in one transaction, creates `training_jobs`, `task_records`, and an outbox row.
3. The scheduler/outbox publisher admits the next plan-fair job and publishes it. Celery stages prepare an immutable dataset snapshot, construct a bounded graph, train DGSR, evaluate it, and export one immutable serving bundle.
4. The serving bundle contains the DGSR weights, feature contract, mappings, item embeddings, item-neighbor lists, popularity/category candidates, optional content features, and versioned ordering policy. For small demo users it may also contain or seed a last-known-good precomputed Top-N cache.
5. The administrator activates an eligible model version.
6. The deployment controller creates or updates the tenant Deployment pinned to the chosen version.
7. An init container downloads and verifies every required artifact. The inference process loads the model and retrieval data, validates the embedded tenant/version/feature schema, warms up an end-to-end funnel request, and becomes ready.
8. Recommendation requests are routed by authenticated tenant context to that tenant's Kubernetes Service. The API resolves the external user to an internal tenant-scoped user ID and passes normalized session/context data in a signed internal request.
9. The pod executes retrieval -> filtering -> batched DGSR scoring -> deterministic ordering and returns Top-N plus the pinned model version and strategy metadata.
10. Results and impression/click/purchase feedback record model version, position, candidate source, and request context needed for offline replay and future position-bias analysis.

---

## 10. Tenant-isolation architecture

### Isolation principles

- The tenant identity is derived only from an API key, access token, or signed internal service token.
- Public request bodies and paths do not contain a trusted `tenant_id` selector.
- Every tenant-owned database row contains `tenant_id`, and RLS is enabled and forced on application roles.
- Each task message contains tenant metadata, but the worker treats PostgreSQL `task_records` as authoritative and rejects mismatches.
- Each inference Deployment contains immutable `GRAPHREC_TENANT_ID`, `MODEL_VERSION_ID`, and checksum values controlled by the deployment controller.
- Object paths are generated from UUIDs already loaded under RLS. Raw caller-provided paths are never accepted.
- Metrics may use internal `tenant_id` because the MVP has low tenant cardinality; external user, product, session, and request IDs are never metric labels.
- Logs include internal tenant ID and correlation ID, but redact API keys, tokens, external PII, and full event payloads.

### Complete authenticated request path

`API key -> hashed-key lookup -> tenant resolution -> authenticated tenant context -> permission check -> database transaction -> SET LOCAL app.current_tenant_id -> RLS -> tenant-scoped repository operation`

### Tenant-isolation diagram

```mermaid
flowchart LR
    Caller[SDK request with API key]
    Auth[Credential verifier]
    Ctx[Authenticated TenantContext]
    Authz[RBAC permission]
    Tx[DB transaction and SET LOCAL]
    RLS[PostgreSQL RLS]
    Svc[Tenant-scoped service]
    Obj[Validated tenant object prefix]
    Task[Verified tenant task context]
    Deploy[Tenant-pinned deployment]

    Caller --> Auth
    Auth -->|tenant_id from credential| Ctx
    Ctx --> Authz
    Authz --> Tx
    Tx --> RLS
    RLS --> Svc
    Svc --> Obj
    Svc --> Task
    Svc --> Deploy
```

### PostgreSQL tenancy approach comparison

| Approach | Isolation | Operational cost | Semester suitability |
|---|---|---|---|
| Database per tenant | Strongest database boundary | Migrations, connections, backups, and provisioning multiply | Poor |
| Schema per tenant | Moderate boundary | Dynamic schemas and migrations are still complex | Poor-to-moderate |
| Shared schema + `tenant_id` + RLS | Efficient and centrally migrated; defense in depth | Requires disciplined context setting and tests | **Selected** |

A namespace per tenant is also rejected for the MVP. The shared namespace uses application quotas, per-pod requests/limits, priority classes, replica caps, and controller-enforced policies.


---

## 11. Tenant-isolation matrix

The following matrix is the primary implementation and security-test checklist.

### Tenant-isolation matrix

| Layer | Tenant-owned resource | Isolation method | Enforcement location | Failure risk | Test method |
|---|---|---|---|---|---|
| Authentication | API keys and tokens | Hashed key resolves one tenant | API middleware | Key mapped to wrong tenant | Credential fixture tests |
| Authorization | Roles and permissions | Tenant-scoped RBAC | FastAPI dependency | Cross-tenant admin action | Permission integration tests |
| PostgreSQL | All tenant rows | `tenant_id`, RLS `USING` and `WITH CHECK` | PostgreSQL | Missing policy or leaked session context | Two-tenant RLS suite |
| Catalog | Users/products | Tenant-local unique constraints | PostgreSQL | External ID collision | Constraint tests |
| Events | Interaction rows | Append-only tenant rows and event idempotency | API and PostgreSQL | Duplicate or foreign event | Duplicate and injection tests |
| Queues | Task references | Message tenant matched to durable task tenant | Worker bootstrap | Forged tenant metadata | Mismatch rejection test |
| Worker | Execution context | Set RLS transaction context before access | Worker task wrapper | Context omitted or reused | Task-without-context test |
| Snapshots | Dataset files | Generated tenant prefix and manifest | Snapshot worker/RustFS policy | Cross-prefix read | Signed-path and bucket tests |
| Registry | Model/version records | RLS and tenant-local version constraints | PostgreSQL | Activate foreign model | Activation isolation test |
| Artifacts | Model weights/config/mappings | Generated `tenants/{tenant_id}/...` path, checksum, manifest identity, per-tenant read-only inference credential | RustFS IAM, controller, and loader | Path traversal or wrong tenant | Prefix-policy and malicious-path tests |
| Deployments | Deployment/Service/HPA | Controller-generated tenant labels and immutable env | Kubernetes/controller | Wrong model in pod | Pod manifest and runtime identity tests |
| Model cache | Loaded tensors | One tenant/version per pod | Inference startup | Cache key collision | Startup identity assertion |
| Recommendations | Requests/results | Tenant context and deployment routing | API, Service, PostgreSQL | Route to wrong service | End-to-end two-tenant test |
| Metrics | Tenant metrics | Internal tenant label only on bounded series | Application exporters | High cardinality or disclosure | Label whitelist tests |
| Quotas | Counters and plan limits | Redis atomic checks plus durable reconciliation | API, worker, PostgreSQL | Race or counter drift | Concurrency and reconciliation tests |
| Logs/audit | Audit events | Tenant ID plus redaction | Logging middleware | PII/key leakage | Log scanning tests |
| Secrets | Tenant credentials | Hashed keys; K8s Secrets for internal credentials | API and Kubernetes RBAC | Secret exposure | RBAC and secret-redaction tests |

The matrix is made enforceable by the following rules:

1. A repository method never accepts `tenant_id` from an HTTP request. It receives a `TenantContext` created by authentication middleware.
2. Every database access occurs inside a transaction-scoped tenant context. A connection returned to the pool has no persistent tenant setting because `SET LOCAL` ends with the transaction.
3. Tenant-owned foreign keys use composite protection where practical. For example, a recommendation result references `(tenant_id, recommendation_request_id)` rather than only a globally unique request ID.
4. Background tasks fail closed when `tenant_id`, `task_id`, internal token claims, and the durable task record disagree.
5. The deployment controller validates that `model_versions.tenant_id`, `model_deployments.tenant_id`, and artifact manifest tenant all match before creating a rollout.
6. Inference startup aborts if the artifact manifest is for another tenant or version.
7. Cross-tenant security tests run in CI with two simultaneously populated tenants and intentionally reused external IDs.

### Explicit Tenant A versus Tenant B security test

For each protected table and endpoint, execute the request under Tenant A's credentials while referencing a valid Tenant B internal or external identifier. The expected result is either `404`, `403` for an explicitly authorized administrative boundary, or an empty query result. Never return the existence of Tenant B's products, events, training jobs, model versions, artifact metadata, deployment state, or recommendation history.

---

## 12. Queue and load-handling design

### Queue topology

RabbitMQ exchanges and Celery routing keys create these durable logical queues. The three-node demo uses a single RabbitMQ instance with durable **classic** queues, persistent messages, publisher confirms, consumer acknowledgements, and dead-letter exchange policies. It does not claim quorum-queue high availability because one broker cannot provide a quorum.

| Queue | Work | Consumers | Priority/cap |
|---|---|---|---|
| `events.default` | Normalize event batches and update counters | General worker | Fair per-tenant admission |
| `dataset.prepare` | Create snapshot manifest and files | General worker | One active preparation per tenant |
| `graph.build` | Construct PyG graph and samples | Training worker | Global concurrency 1 |
| `training.free` | Free-plan training | Training worker | Lowest priority |
| `training.basic` | Basic-plan training | Training worker | Medium priority |
| `training.pro` | Pro-plan training | Training worker | Highest priority, but bounded |
| `evaluation` | Calculate offline metrics and compare baseline | General or training worker | Follows training |
| `artifact.registration` | Validate checksum and register metadata | General worker | Idempotent |
| `deployment` | Trigger controller reconciliation | General worker/controller | Serialized per tenant |
| `usage` | Aggregate and reconcile usage | General worker | Scheduled |
| `housekeeping` | Retention, tombstones, stale locks | General worker | Low priority |
| `dead-letter` | Poison-message inspection | No automatic consumer by default | Manual/replay tool |

The plan queues express entitlement, but RabbitMQ priority alone is not treated as fair scheduling because a continuous Pro stream can starve lower plans. The database scheduler selects the next runnable training job with weighted deficit round robin (Pro 3, Basic 2, Free 1), skips tenants already holding the training lock, and publishes at most one job to the global execution slot. The MVP training worker therefore remains `--concurrency=1`.

### Message envelope

```json
{
  "message_id": "uuid",
  "tenant_id": "uuid",
  "job_id": "uuid",
  "task_type": "training.build_graph",
  "retry_count": 0,
  "created_at": "2026-08-01T00:00:00Z",
  "idempotency_key": "tenant/job/stage",
  "correlation_id": "uuid",
  "payload_ref": {"table": "task_records", "id": "uuid"},
  "schema_version": 1
}
```

Only small control messages are placed on the broker. Event batches, datasets, logs, and model artifacts remain in PostgreSQL or RustFS. Publication is driven by `outbox_events`, so the API never performs an unsafe database-then-broker dual write.

### Worker tenant-context establishment

1. Parse and schema-validate the message.
2. Call a narrowly scoped, audited task-claim function using the globally unique task ID and envelope tenant. The function has a fixed `search_path`, verifies the tenant match, obtains a fencing/lease token, and exposes no arbitrary cross-tenant query capability.
3. Compare envelope tenant, claimed task tenant, job tenant, schema version, and expected task type.
4. Begin a normal application transaction and set `SET LOCAL app.current_tenant_id`.
5. Re-load tenant-owned records under RLS.
6. Acquire stage idempotency record or lock.
7. Execute, persist stage output, commit, then acknowledge the RabbitMQ message.

A worker never processes a message that lacks a valid tenant context.

### Retries, duplicates, and poison messages

- Use Celery late acknowledgement only for idempotent stages and acknowledge after durable stage completion. Worker-loss redelivery is enabled selectively; repeated crashes must be capped to prevent poison-message loops.
- Retry transient network/database/object-store errors with exponential backoff plus jitter, for example 10 s, 30 s, 2 min, 10 min, capped at five attempts.
- Do not retry deterministic validation, tenant mismatch, unsupported schema, checksum failure after re-download, or invalid model configuration without operator action.
- Every stage has a unique idempotency key such as `(tenant_id, job_id, stage_name, input_version)` stored in `idempotency_keys` or `task_records`.
- Stage writes use `INSERT ... ON CONFLICT` or compare-and-set status transitions.
- After the retry limit, publish a sanitized envelope to a dead-letter exchange, mark the task/job failed, record `failure_reason`, and raise an alert.
- A replay command creates a new message ID while retaining the original correlation ID and requiring an administrator audit record.

### Noisy-neighbor queue protection

- API admission limits queued messages per tenant and per plan using Redis atomic counters.
- A tenant batch has maximum events and maximum payload bytes.
- Queue messages point to durable rows, preventing huge broker payloads.
- Scheduler round-robin admission prevents one tenant from dispatching all waiting jobs.
- One training lock per tenant plus a unique partial database index prevents simultaneous duplicate training.
- Training worker concurrency is globally one; inference never shares its process or priority class.
- If queue age exceeds an objective, new low-priority training may be rejected or left in `waiting_for_resources` rather than expanding unboundedly.

### Online inference queueing

Recommendation requests normally remain synchronous:

- API applies a Redis-backed tenant rate limit and a per-tenant distributed in-flight semaphore.
- Each inference pod enforces its own bounded local semaphore/wait queue; no recommendation request is written to Redis or Celery as a job.
- Suggested initial values: 4 in-flight model executions per pod, at most 16 local waiters per pod, maximum local wait 100 ms, and an 800 ms end-to-end upstream timeout. These values are replaced by load-test measurements.
- Quota excess returns `429 Too Many Requests` with `Retry-After`.
- Runtime capacity exhaustion, no ready replica, or queue timeout returns `503 Service Unavailable` with short randomized retry guidance.
- A circuit breaker opens after repeated tenant-service failures and optionally returns tenant popular products when the caller allowed fallback.
- A background Celery queue is never used for ordinary Top-N requests.

### Queue-processing sequence diagram

```mermaid
sequenceDiagram
    participant API
    participant PG as PostgreSQL
    participant O as Scheduler / outbox publisher
    participant MQ as RabbitMQ
    participant W as Celery worker
    participant Redis
    participant DLQ as Dead-letter exchange

    API->>PG: Transaction: business row + task_record + outbox_event
    PG-->>API: Commit
    API-->>API: Return 202 or domain response
    O->>PG: Claim ready outbox row with SKIP LOCKED
    O->>MQ: Publish small tenant-scoped envelope
    MQ-->>O: Publisher confirm
    O->>PG: Mark outbox row published
    MQ->>W: Deliver
    W->>PG: Claim task and compare tenant metadata
    W->>Redis: Acquire idempotency/tenant lock
    alt first valid attempt
        W->>PG: SET LOCAL tenant and process
        W->>PG: Persist result and succeeded state
        W-->>MQ: ACK
    else transient failure
        W->>PG: Record failed attempt
        W->>MQ: Retry with backoff
    else poison or retry exhausted
        W->>PG: Mark failed
        W->>DLQ: Publish sanitized envelope
        W-->>MQ: ACK original
    end
```

---

## 13. Tenant-specific training pipeline

### Pipeline stages

1. `POST /v1/training-jobs` verifies permission, plan, event minimum, cooldown, and no active job.
2. Insert `training_jobs(status='queued')`, `task_records`, and `outbox_events` in one PostgreSQL transaction.
3. The scheduler applies weighted fair admission and the outbox publisher sends the admitted task when the global execution slot is available.
4. Worker acquires `train:{tenant_id}` Redis lock with heartbeat and verifies the partial unique index.
5. Create an immutable dataset snapshot with event cutoff timestamp and query definition.
6. Read only tenant-scoped events under RLS, validate, deduplicate, sort, and filter.
7. Write snapshot data and manifest to `tenants/{tenant_id}/datasets/{snapshot_id}/`.
8. Build user/item mappings, ordered edges, bounded graph tensors, and prefix-next-item samples.
9. Train the chosen baseline or simplified DGSR model with deterministic seeds where supported.
10. Checkpoint periodically to the tenant/job path.
11. Evaluate Hit@10, NDCG@10, loss, coverage, and optional diversity/novelty.
12. Compare against the current model or popularity baseline.
13. Serialize weights safely, create config/mapping/metric manifests, calculate SHA-256, and upload.
14. Register a new immutable model version in PostgreSQL.
15. Mark the job succeeded. Activation is a separate explicit action.
16. Release the lock in `finally`; stale locks expire and are reconciled.

### Training sequence diagram

```mermaid
sequenceDiagram
    participant Admin as Tenant admin
    participant API
    participant PG as PostgreSQL RLS
    participant Outbox as Scheduler / outbox publisher
    participant MQ as RabbitMQ
    participant Redis
    participant Train as Training worker
    participant RustFS

    Admin->>API: POST /v1/training-jobs
    API->>PG: Transaction: create queued job, task, outbox row
    API-->>Admin: 202 job_id
    Outbox->>PG: Select next job with weighted fairness
    Outbox->>MQ: Publish admitted tenant job reference
    MQ->>Train: Deliver admitted training task
    Train->>Redis: Acquire per-tenant training lock
    Train->>PG: SET LOCAL tenant; create snapshot
    Train->>RustFS: Upload snapshot manifest/data
    Train->>PG: status building_graph
    Train->>Train: Build bounded dynamic graph
    Train->>PG: status training
    Train->>RustFS: Periodic checkpoints
    Train->>Train: Evaluate metrics
    Train->>RustFS: Upload final weights/config/mappings
    Train->>PG: Register model version; mark succeeded
    Train->>Redis: Release lock
```

### Training job state diagram

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> waiting_for_resources
    queued --> preparing_data
    waiting_for_resources --> preparing_data
    preparing_data --> building_graph
    building_graph --> training
    training --> evaluating
    evaluating --> registering
    registering --> deploying: optional auto-deploy disabled by default
    registering --> succeeded
    deploying --> succeeded
    queued --> cancelling
    waiting_for_resources --> cancelling
    preparing_data --> cancelling
    building_graph --> cancelling
    training --> cancelling
    evaluating --> cancelling
    cancelling --> cancelled
    queued --> failed
    preparing_data --> failed
    building_graph --> failed
    training --> failed
    evaluating --> failed
    registering --> failed
    deploying --> failed
    succeeded --> [*]
    failed --> [*]
    cancelled --> [*]
```

### Resource, cancellation, and recovery policy

- **Per-tenant lock:** Redis `SET NX PX` plus heartbeat. Database partial unique index is the durable second line of defense.
- **Global concurrency:** training worker starts with `--concurrency=1`; only one CPU-heavy job runs cluster-wide.
- **Resources:** initial request 1 CPU/2 GiB, limit 2 CPU/4 GiB; tune with profiling.
- **Maximum duration:** Free 30 min, Basic 60 min, Pro 120 min in the demo. Worker checks deadline between epochs and stages.
- **Cancellation:** API sets `cancellation_requested_at`; worker checks cooperatively, writes a final safe checkpoint, then transitions through `cancelling` to `cancelled`.
- **Retries:** preparation and upload stages retry. Training resumes from a verified checkpoint for worker crash; deterministic configuration errors fail immediately.
- **Checkpointing:** save every N epochs or 10 minutes under job attempt path. Retain latest two successful checkpoints until final registration.
- **Reproducibility:** store random seed, Python/PyTorch/PyG versions, code Git SHA, config, cutoff, snapshot checksum, mapping checksum, and environment summary.
- **Training logs:** structured logs go to stdout; a compact log reference and selected progress events are stored in PostgreSQL. Full logs may be uploaded to RustFS.
- **Retraining triggers:** manual request, schedule, or event-count threshold. All obey a cooldown and one-active-job constraint.

---

## 14. Simplified DGSR-inspired model

The conceptual basis is DGSR: connect user sequences through a dynamic user-item graph, encode time/order information, and treat next-item recommendation as user-to-item link prediction. The semester version preserves this idea while replacing expensive dynamic subgraph extraction and complex attention blocks with bounded, reproducible operations.

### Data representation

- User node: tenant-local internal user index.
- Item node: tenant-local internal product index.
- Edge: one validated interaction event.
- Edge attributes: event type, configurable weight, UTC timestamp, per-user sequence position, relative time bucket, and optionally per-item user-order position.
- Supported types and starting weights:
  - `product_view = 1`
  - `product_click = 2`
  - `add_to_cart = 3`
  - `purchase = 5`
  - `rating = normalized rating in [-1, 5]` or mapped to `[0, 5]`
  - `remove_from_cart = 0` initially, optionally a small negative value after evaluation

Manual weights are explainable but not learned, can encode incorrect business assumptions, vary by domain, and may overvalue frequent low-intent behavior. They must be tenant-configurable and compared against unweighted/learned-edge baselines.

### Data preparation

1. Validate event schema and membership of referenced product/user in the same tenant.
2. Deduplicate using unique `(tenant_id, event_id)`.
3. Filter disabled/deleted products and tenant-external catalog records.
4. Sort by `(occurred_at, received_at, event_id)` for deterministic order.
5. Truncate each user to a configurable recent sequence, initially 50-100 events.
6. Build prefix-to-next-item examples; require at least three interactions for sequence training.
7. Use temporal train/validation/test split by event time, never random edge splitting.
8. Build mappings using only information available at the corresponding cutoff to avoid future leakage.
9. Cold users use popularity, category-popular, or session-only recent events and transition to personalized retrieval after a minimum interaction threshold.
10. Cold items are never assigned a misleading random personalized score. They may enter a bounded content/category candidate source using normalized metadata, then receive conservative ordering exposure until a retraining snapshot adds them to the DGSR mapping. A learned inductive metadata encoder is future work.

### Bounded graph sampling

For each target user and training example:

1. Select the target user's most recent `N=20` products before the prediction timestamp.
2. For each product, select at most `M=10` recent connected users whose relevant interactions also precede the target timestamp.
3. Optionally select at most `K=5` recent products for each sampled neighbor user.
4. Deduplicate nodes and enforce hard caps, for example 128 users, 256 items, and 1,024 edges.
5. Apply one or two message-passing layers. Never perform unbounded traversal.
6. Precompute training subgraph indices or neighbor lists for the snapshot when memory permits.

### Model architecture

- Trainable tenant-local user and item embeddings.
- Long-term representation from a bounded **edge-aware GraphSAGE-style** message-passing block. A lightweight edge MLP projects interaction type, weight, relative time, and sequence-order features into each message before mean aggregation; one layer is the default and two is the maximum for the MVP.
- Short-term representation from the most recent item embeddings plus relative-time/order embeddings, aggregated with a small GRU or attention-pooling block.
- Gated fusion: `h_user = gate * h_short + (1-gate) * h_long`.
- Shared item representation used by both retrieval and final scoring. The serving bundle exports the item embedding matrix from the activated DGSR version.
- Final relevance score: dot product or small MLP between the fused user representation and each candidate item representation.
- Training objective: sampled softmax or BPR loss for next-item link prediction with negative sampling from the tenant catalog.
- All candidates for one request are scored in one vectorized batch. The MVP does not invoke the model once per item and does not add a second learned ranker.

### Four-stage serving contract for the same DGSR model

#### 1. Candidate retrieval

The online pod first creates a query representation from the persistent DGSR user state and caller-supplied recent session events. It then retrieves a capped union:

- `dgsr_personalized`: exact batched dot-product top-K over active DGSR item embeddings for catalogs below the configured exact-scan threshold.
- `dgsr_recent_neighbors`: precomputed nearest items for the last few interacted products.
- `recent_popular` and `category_popular`: offline/periodically refreshed tenant lists.
- `content_cold_start`: bounded metadata similarity for products not yet in the DGSR mapping.
- `tenant_rule`: optional explicit tenant merchandising IDs, separately labeled and capped.

A default demo budget is 200 unique candidates, with per-source quotas and a hard maximum of 300. If the active catalog exceeds the load-tested exact-scan limit, use the precomputed neighbor sources for the MVP; a versioned FAISS/HNSW artifact is the production evolution path.

#### 2. Eligibility filtering

Before expensive scoring, remove candidates that fail any mandatory rule:

- Tenant/product identity mismatch.
- Disabled, deleted, unavailable, out-of-stock, or region-ineligible product when the tenant supplies that field.
- Caller exclusions.
- Optional already-purchased or recently-impressed suppression.
- Missing active-catalog membership or stale eligibility state when the configured policy is fail-closed.

Filtering is deterministic and separately observable. The model is not expected to learn catalog or legal eligibility rules.

#### 3. DGSR scoring

The same activated DGSR model batch-scores all remaining mapped items using the fused long-term and current-session representation. Candidate-source identity and coarse retrieval scores may be included as bounded auxiliary features only if they were present in the versioned training feature contract; otherwise they remain debug metadata. Scores from different candidate generators are never compared directly.

Content-only cold-start items that lack a DGSR item mapping cannot receive a fake DGSR score. They are either omitted from personalized scoring or passed to a conservative rule-based cold-start lane with a capped exposure position.

#### 4. Deterministic ordering/re-ranking

The orderer starts from the DGSR score and applies a versioned, bounded policy:

- Stable tie-break using internal product ID so identical inputs do not oscillate.
- Maximum items per category/brand in the Top-N.
- Optional maximal-marginal-relevance-style diversity using item embeddings.
- Small, capped freshness or seasonality boost when configured by the tenant.
- Final exclusion and duplicate check.
- No hidden sponsored placement in the semester MVP.

Store `raw_model_score`, `final_order_score`, candidate source, filter reason, and final position in debug/audit records where retention permits. The public response exposes only the final list and safe strategy metadata.

### Feature contract and online freshness

Training and inference call the same feature builder and normalization code. The bundle stores `feature_schema_version`, vocabularies, scaling statistics, missing-value defaults, and checksums. The persistent long-term graph is as fresh as the active training snapshot, while the short-term encoder consumes recent session events supplied in the request, providing mission-level real-time relevance without online training.

### Selective precomputation and fallback

At activation or on a schedule, GraphRec may precompute Top-N lists for a bounded set of recently active demo users. These lists are versioned by model and catalog version, filtered again at serve time, and used only as a last-known-good fallback or cache. The platform never computes recommendations for every registered user merely because they exist.

### Retained, simplified, approximated, omitted

| DGSR concept | MVP treatment |
|---|---|
| Dynamic collaborative graph across sequences | **Retained** through timestamped user-item graph snapshots |
| Time and order on edges | **Retained** with sequence index and relative-time embeddings |
| Next-item as link prediction | **Retained** |
| Dynamic high-order subgraph extraction | **Simplified** to bounded recent two-hop sampling |
| Sophisticated dynamic graph attention | **Approximated** with one edge-aware GraphSAGE-style aggregation block plus long/short gating |
| Per-event continuously changing online graph | **Omitted**; rebuilt per training snapshot, so persistent-user recommendations are only as fresh as the active snapshot |
| Deep multi-layer propagation | **Omitted**; one or two layers |
| Large-scale approximate-nearest-neighbor serving | **Deferred**; MVP uses exact batched retrieval plus versioned item-neighbor artifacts. ANN is a compatible future replacement behind the retrieval interface |

### Baselines and activation rule

Every tenant independently trains and stores:

1. Popular-products model by weighted recent events.
2. BPR or implicit matrix factorization baseline.
3. Optional GRU/session sequence baseline.
4. Simplified DGSR model when data volume is sufficient.

A new model becomes **eligible**, not automatically active, when training completes, metric values are finite, artifact checksums pass, the complete four-stage smoke test succeeds, retrieval Recall@K exceeds the baseline threshold, catalog coverage and intra-list diversity exceed minimums, and NDCG@10 is no worse than the active model by more than a configured tolerance such as 2%. A top-list churn/Jaccard guard flags unexpectedly oscillating recommendations for manual review. A tenant admin activates the eligible version. Events received after the snapshot do not change the persistent long-term graph until retraining; the session endpoint incorporates caller-supplied recent items for short-term freshness.

---

## 15. Model registry and artifact storage

### Artifact bundle

Each immutable model version contains:

```text
tenants/{tenant_id}/models/{model_id}/{version}/
  manifest.json
  weights.safetensors
  model_config.json
  feature_schema.json
  user_mapping.parquet
  item_mapping.parquet
  item_embeddings.safetensors
  item_neighbors.parquet
  candidate_sources.json
  ordering_policy.json
  metrics.json
  environment.json
  popular_and_category_lists.json
  optional_content_features.parquet
  optional_precomputed_topn.parquet
```

For a pure PyTorch fallback, store a `state_dict` only and load with a controlled architecture and weights-only loading. Never accept arbitrary tenant-uploaded Python pickle or model code.

### Registry metadata

`model_versions` records tenant, model, monotonic version, status, framework/version, code version, config, hyperparameters, snapshot, training job, cutoff, URI, checksum, bytes, metrics, timestamps, creator, parent, rollback target, and active/retired state. Metric detail may also be normalized in `model_evaluation_metrics`.

### Object-storage controls

- The application generates object keys from UUIDs and integer versions; callers never submit a storage URI.
- The training worker is a trusted platform writer but still generates keys from durable tenant records. For inference, the controller provisions a per-tenant read-only RustFS access key with an inline policy restricted to `graphrec/tenants/{tenant_id}/models/*`, stores it in a tenant-specific Kubernetes Secret, and rotates/revokes it when the deployment or tenant is retired.
- Upload to a temporary key, calculate checksum, then atomically register/finalize.
- Loader downloads only the URI stored in a tenant-scoped row, validates normalized prefix, file sizes, checksums, manifest schema, tenant, model ID, version, framework allowlist, code compatibility, feature schema, item-embedding dimensions, candidate artifact mappings, and ordering-policy bounds.
- Path segments reject `..`, slashes in identifiers, URI schemes from input, and encoded traversal.
- Retention: keep active, rollback target, and latest two successful versions; archive older eligible versions according to plan.
- Tenant deletion is asynchronous: revoke credentials, stop deployments, tombstone tenant, delete tenant objects, then hard-delete or anonymize according to policy and audit completion.

### Model lifecycle state diagram

```mermaid
stateDiagram-v2
    [*] --> training
    training --> failed
    training --> registered
    registered --> eligible: metrics and smoke tests pass
    registered --> rejected: validation fails
    eligible --> active: tenant activation
    active --> retired: newer version activated
    active --> failed_deployment: rollout fails
    failed_deployment --> active: rollback to previous revision
    retired --> active: explicit rollback
    retired --> archived
    rejected --> archived
    archived --> deleted: retention or tenant deletion
```

---

## 16. Model deployment controller

### Controller form

Implement a lightweight Python reconciler, not a full custom-resource operator. It runs every 10-15 seconds and on `deployment` queue notifications, holds a Redis leader lock, reads desired deployment rows, and uses the Kubernetes Python client.

### Responsibilities

- Resolve the deployment's single desired model version and the currently active version. During rollout these may differ; only the finalized active version is exposed as stable.
- Validate tenant/version/artifact/checksum consistency.
- Create/update tenant Deployment, ClusterIP Service, HPA, labels, probes, resources, service account, and tenant-scoped artifact-read Secret.
- Pin the Deployment template to immutable desired model version ID, artifact URI, and checksum. Scale-out of that template always creates replicas of the same version.
- Record desired, available, and ready replicas plus rollout conditions.
- Support rolling update and rollback to a prior deployment revision.
- Retire old ReplicaSets after the configured history limit.
- Prevent concurrent active versions by a transaction-level advisory lock, partial unique constraints, and serialized reconciliation. The activation transaction updates the target version, `model_deployments.desired_model_version_id`, activation history, and an outbox event atomically.

### Pod startup choice

**Selected: init container download into `emptyDir`.**

- Better than main-process lazy download because the application starts only after artifact preparation.
- Better than shared mounted storage because it avoids cross-tenant shared-path mistakes and network reads during inference.
- Easier to observe and retry than embedding download logic deeply in the server.

The init container uses the tenant-scoped read-only RustFS credential, downloads only the URI recorded in the deployment revision, verifies file-count and size limits, checksum, manifest schema, tenant ID, model ID, version, and code compatibility, writes an identity file, and makes the directory read-only to the main container where feasible.

### Model activation sequence diagram

```mermaid
sequenceDiagram
    participant Admin as Tenant admin
    participant API
    participant PG as PostgreSQL
    participant Ctrl as Deployment controller
    participant K8s as Kubernetes API
    participant Init as Init container
    participant RustFS
    participant Pod as Inference pod

    Admin->>API: Activate eligible Model A v2
    API->>PG: Transaction: desired=v2, active remains v1, revision pending, outbox row
    API-->>Admin: 202 deployment revision
    Ctrl->>PG: Read desired v2, active v1, checksum
    Ctrl->>K8s: Patch Deployment template to v2
    K8s->>Init: Start new pod
    Init->>RustFS: Download tenant A v2 bundle
    Init->>Init: Validate path, manifest, SHA-256
    Init-->>Pod: Verified artifact volume
    Pod->>Pod: Load, tenant/version assertion, warm-up
    Pod-->>K8s: Readiness true
    K8s->>K8s: Add new pod to Service endpoints
    K8s->>K8s: Terminate old v1 pod after readiness
    Ctrl->>PG: Finalize atomically: v2 active, v1 retired, deployment available
```

### Activation consistency model

- **Ordinary scale-out:** HPA copies one immutable Deployment template, so every added replica loads the exact same tenant and model version.
- **Model activation:** a rolling update intentionally allows a short transition where ready old-version and new-version pods may both receive traffic. Every response reports the version that served it. The database still distinguishes `active_model_version_id` from `desired_model_version_id` until rollout completion.
- **Finalization:** only after all required new pods are ready and old pods are drained does the controller atomically mark the new version active and the previous version retired.
- **Failure:** if the new revision misses its progress deadline or fails identity/checksum/warm-up, the old version remains active and the desired version is marked failed or reverted.

### Rolling, blue-green, and canary comparison

| Method | Safety | Resource cost | MVP |
|---|---|---|---|
| Rolling update | Old pod remains until new ready; simple rollback | One surge pod | **Selected** |
| Blue-green | Very clear switch and rollback | Doubles replicas during rollout | Future |
| Canary | Limits blast radius and measures live behavior | Requires traffic splitting and analysis | Future |

Use `maxUnavailable: 0`, `maxSurge: 1`, readiness gates, progress deadline, and revision history 3. If v2 never becomes ready, v1 continues serving and the controller marks the revision failed. Rollback patches the template back to the prior immutable version.

### Deployment and replica state diagram

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> creating
    creating --> initializing
    initializing --> loading_model
    loading_model --> warming
    warming --> ready
    ready --> draining
    draining --> terminated
    initializing --> failed
    loading_model --> failed
    warming --> failed
    failed --> creating: retry/reconcile

    state Deployment {
      [*] --> desired
      desired --> progressing
      progressing --> available
      progressing --> degraded
      degraded --> rolling_back
      rolling_back --> available
    }
```

---

## 17. Tenant-specific replication and autoscaling

### Per-tenant HPA policy

Initial values for active tenants:

```yaml
minReplicas: 1
maxReplicas: 2   # Free=1, Basic=2, Pro=3, also limited globally
cpuTargetAverageUtilization: 65
scaleUp:
  stabilizationWindowSeconds: 0
  maxIncrease: 1 pod per 30 seconds
scaleDown:
  stabilizationWindowSeconds: 300
  maxDecrease: 1 pod per 60 seconds
```

The required MVP demo scales on CPU. After that path is proven, add at most one per-pod custom metric—prefer average in-flight requests per ready pod, target initially 4. P95 latency, queue wait, request rate, and timeout rate remain Prometheus signals and acceptance criteria. They are not additional replica writers.

### Minimal HPA manifest

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: infer-tenant-a
  labels:
    graphrec.io/tenant-id: "<tenant-a-uuid>"
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: infer-tenant-a
  minReplicas: 1
  maxReplicas: 2
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 65
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
```

Every inference container must define a CPU request; otherwise CPU utilization is undefined for HPA. The cluster must run Metrics Server. If the optional in-flight metric is later added, use `autoscaling/v2` and let the same HPA evaluate both metrics; do not introduce a second scaler.

### Placement and limits

- Pod anti-affinity prefers different hostnames for replicas of the same tenant, but is `preferred`, not required, because a three-node demo may lack capacity.
- Resource requests let the scheduler make realistic decisions. Limits prevent a model or tenant from exhausting a node.
- A global controller configuration caps total inference replicas, for example six, and per-tenant replicas by plan.
- Inference has a higher PriorityClass than training.
- Training has node affinity away from currently dense inference nodes where possible.
- PodDisruptionBudget may preserve one ready pod per active tenant during voluntary disruption, but does not create high availability when a node or stateful dependency fails.

### When no cluster capacity remains

1. Keep existing ready replicas serving.
2. HPA remains unable to schedule the pending replica; controller records `capacity_blocked`.
3. Gateway admits only the bounded queue and applies tenant concurrency limits.
4. Return 429 for plan/rate excess and 503 for platform capacity/timeouts.
5. Use popular-products fallback only when explicitly allowed and available.
6. Alert the administrator and expose desired versus ready replica mismatch.
7. Pause new training admission until online pressure recovers.

Exact thresholds must be established with load testing because model latency, Python concurrency, node CPU, and startup time determine the real capacity.

---

## 18. Exact Tenant A and Tenant B scaling scenario

### Initial state

- Tenant A: active Model A v1, Deployment `infer-a`, Service `infer-a`, HPA min 1/max 2, Replica A1 ready on Node 1.
- Tenant B: active Model B v3, Deployment `infer-b`, Service `infer-b`, HPA min 1/max 2, Replica B1 ready on Node 2.
- Node 3: platform services and spare schedulable inference capacity.

Scaling is based on measured demand, not the number of registered customers. A load generator increases Tenant A from roughly 10 to 20 concurrent requests. Tenant A's CPU stays above the HPA target long enough to scale; the dashboard simultaneously shows rising request rate, in-flight work, queue wait, and P95 latency. If the optional in-flight metric is enabled, HPA uses the larger replica recommendation. Tenant B's metrics remain below target.

### Tenant A scale-out sequence diagram

```mermaid
sequenceDiagram
    participant ReqA as Tenant A requests
    participant GW as API / inference gateway
    participant SvcA as Tenant A Service
    participant A1 as Replica A1 - Model A v1
    participant Metrics as Prometheus metrics
    participant HPA as Tenant A HPA
    participant K8s as Kubernetes scheduler
    participant A2Init as Replica A2 init
    participant RustFS
    participant A2 as Replica A2 - Model A v1
    participant B1 as Tenant B Replica B1 - Model B v3

    ReqA->>GW: Workload rises from about 10 to 20 concurrent
    GW->>SvcA: Authenticated Tenant A routing
    SvcA->>A1: Requests
    A1->>Metrics: CPU plus request/inflight/latency signals rise
    Metrics->>HPA: CPU target exceeded (optional inflight metric also evaluated)
    HPA->>K8s: Desired replicas 1 -> 2
    K8s->>A2Init: Schedule new Tenant A pod on available node
    A2Init->>RustFS: Download tenants/A/models/A/v1
    A2Init->>A2Init: Verify SHA-256 and manifest tenant=A, version=v1
    A2Init-->>A2: Start inference process
    A2->>A2: Load Model A v1 and warm-up
    A2-->>K8s: Readiness succeeds
    K8s->>SvcA: Add A2 endpoint
    SvcA->>A1: Load-balanced requests
    SvcA->>A2: Load-balanced requests
    Note over B1: Tenant B remains one replica and serves only Model B v3
```

During A2 startup, A1 continues serving. The bounded gateway queue absorbs only a short burst. Traffic reaches A2 only after readiness succeeds.

### Tenant A scale-down sequence diagram

```mermaid
sequenceDiagram
    participant ReqA as Tenant A requests
    participant Metrics as Prometheus metrics
    participant HPA as Tenant A HPA
    participant SvcA as Tenant A Service
    participant A1 as Replica A1
    participant A2 as Replica A2
    participant B1 as Tenant B Replica B1

    ReqA->>Metrics: Traffic and inflight fall below target
    Metrics->>HPA: Low load sustained through cooldown
    HPA->>HPA: Apply 300-second stabilization window
    HPA->>SvcA: Desired replicas 2 -> 1
    SvcA->>A2: Remove endpoint and begin drain
    A2->>A2: Finish accepted requests within grace period
    A2-->>HPA: Terminated
    Note over A1: A1 continues serving Model A v1
    Note over B1: B1 remains unchanged on Model B v3
```

### Three-node scenario deployment diagram

```mermaid
flowchart TB
    subgraph N1[Node 1]
        API1[FastAPI API]
        A1[Replica A1 - Tenant A - Model A v1]
        EXP1[Metrics exporter]
    end
    subgraph N2[Node 2]
        B1[Replica B1 - Tenant B - Model B v3]
        TW[Training worker - limited]
        RMQ[RabbitMQ]
    end
    subgraph N3[Node 3]
        PG[PostgreSQL]
        RUSTFS[RustFS]
        CTRL[Deployment controller]
        A2[Replica A2 - Tenant A - Model A v1 after scale-out]
    end
    SVA[Tenant A Service] --> A1
    SVA --> A2
    SVB[Tenant B Service] --> B1
```

### Version-consistency proof

HPA scales the existing Deployment template. That template contains immutable `tenant_id=A`, `model_version=A-v1`, artifact URI, and checksum. It cannot independently choose another model. A2 therefore loads exactly the same Model A v1 bundle as A1. Tenant B's Service selector matches only labels for Tenant B's deployment revision, and B1's startup identity check rejects any Model A artifact.

---

## 19. Recommendation-serving flow

### Synchronous serving path

1. SDK sends API key, stable `request_id`, external user ID or anonymous session context, recent events, `limit`, exclusions, page/context fields, and optional fallback permission.
2. API resolves tenant, checks `recommendations:read`, resolves the external user to an internal tenant-scoped user ID under RLS, and normalizes the request. The public caller never supplies an internal user or tenant ID.
3. Redis Lua script enforces monthly/short-window quota and acquires a per-tenant in-flight slot.
4. API looks up the cached active deployment route, model version, catalog version, and feature schema, with PostgreSQL as source of truth.
5. API sends a signed internal request to the tenant's ClusterIP Service. The internal token includes tenant, deployment revision, model version, feature schema, audience, and short expiry.
6. Inference pod verifies token claims against immutable startup identity and confirms that all retrieval/scoring/order artifacts belong to the pinned version.
7. **Retrieval:** build the current query representation and merge bounded candidates from DGSR exact/vector retrieval, recent-item neighbors, popularity/category lists, and optional cold-start content candidates.
8. **Filtering:** remove products failing tenant, active-catalog, availability, region, exclusion, purchase/impression, or freshness rules before model scoring.
9. **DGSR scoring:** batch-score mapped candidates with the same activated DGSR model; content-only unknown items remain in a separately capped cold-start lane rather than receiving fabricated model scores.
10. **Ordering:** deterministically select Top-N with stable tie-breaks, category/brand caps, optional bounded diversity/freshness/seasonality, and a final eligibility check.
11. API records a compact request/result record or enqueues it, releases the semaphore, and returns model version, strategy, fallback tier, and final products.
12. Impression/click/purchase feedback is sent separately with idempotent event IDs and includes displayed position so future offline evaluation can account for exposure bias.

### Recommendation-serving sequence diagram

```mermaid
sequenceDiagram
    participant Shop as E-commerce backend
    participant SDK
    participant API as GraphRec gateway
    participant Redis
    participant PG as PostgreSQL
    participant Svc as Tenant-specific Service
    participant Pod as Ready inference replica

    Shop->>SDK: get_recommendations(user_id, top_n=10)
    SDK->>API: POST /v1/recommendations + API key
    API->>API: Resolve tenant; authorize
    API->>Redis: Rate limit and acquire inflight slot
    API->>PG: Resolve user and active deployment/version/schema under RLS
    API->>Svc: Signed normalized tenant/version/context request
    Svc->>Pod: Load-balanced request
    Pod->>Pod: Verify pinned tenant/version/schema
    Pod->>Pod: Retrieve candidate union
    Pod->>Pod: Filter eligibility and exclusions
    Pod->>Pod: Batch-score candidates with DGSR
    Pod->>Pod: Deterministically order/re-rank Top-N
    Pod-->>API: Top-N, model version, stage latency metadata
    API->>PG: Record request/result or enqueue compact record
    API->>Redis: Release inflight slot; increment usage
    API-->>SDK: 200 recommendations
```

### Fallback order

1. Active personalized four-stage DGSR path.
2. Version-matched last-known-good personalized Top-N for that user/session cohort, produced at activation or cached from a recent successful request, with a short TTL and a fresh active-catalog filter.
3. Tenant/category popular products stored in Redis/PostgreSQL and filtered for current eligibility.
4. Optional BPR baseline only when it is packaged, versioned, warmed, and explicitly configured as a serving fallback; BPR remains mandatory as an evaluation baseline, not a required live dependency.
5. `503` when no safe result exists.

The response includes `model_version`, `strategy`, and `fallback_used` for auditability, without exposing another tenant's identifiers.

---

## 20. Resource quota design

### Demonstration plan limits

| Limit | Free | Basic | Pro |
|---|---:|---:|---:|
| Accepted events/month | 50,000 | 500,000 | 2,000,000 |
| Recommendations/month | 20,000 | 250,000 | 1,000,000 |
| Requests/minute | 60 | 300 | 1,000 |
| Concurrent recommendation requests | 4 | 12 | 30 |
| Queued messages | 500 | 5,000 | 20,000 |
| Stored products | 5,000 | 25,000 | 100,000 |
| Training jobs/month | 1 | 4 | 12 |
| Concurrent training jobs/tenant | 1 | 1 | 1 |
| Maximum training duration | 30 min | 60 min | 120 min |
| Active model versions | 2 | 5 | 10 |
| Maximum inference replicas | 1 | 2 | 3 |
| Artifact storage | 1 GiB | 5 GiB | 20 GiB |

These are project defaults, not validated commercial pricing.

### Enforcement layers

- **API rate limits:** Redis token bucket or sliding-window Lua script keyed by internal tenant UUID and endpoint class.
- **Concurrent inference:** Redis distributed semaphore plus local pod semaphore.
- **Events/month and recommendations/month:** Redis fast counters checked in real time, followed by idempotent durable usage events and reconciliation.
- **Queue quotas:** admission counter increments only after durable task creation; terminal tasks decrement queue occupancy.
- **Products/storage/model counts:** PostgreSQL transactional checks and controller validation.
- **Training:** partial unique index, tenant Redis lock, monthly quota, global concurrency 1, deadline.
- **Replicas:** plan cap in HPA/controller plus global cluster cap.
- **CPU/memory:** per-pod Kubernetes requests/limits. Shared namespace is acceptable because application/controller quotas provide the tenant dimension that namespace ResourceQuota cannot.
- **Emergency limits:** global maximum request rate, queue age, total replicas, total concurrent model loads, and training pause switch.

Quota failures are explicit and auditable. API responses provide limit name, current usage when safe, reset time, and upgrade guidance; they do not silently drop accepted events.


---

## 21. Monitoring and observability design

### Lightweight stack

- Prometheus scrapes FastAPI, inference, worker, RabbitMQ, Redis, PostgreSQL, kube-state-metrics, and node/container metrics.
- Grafana provides administrator and tenant-filtered dashboards.
- Structured JSON logs use correlation ID, internal tenant ID, service, task/job ID, model version, severity, and error code.
- Celery task events are optional; durable job and attempt tables remain authoritative.

### Metric design

Platform metrics:

- API request rate, error rate, P50/P95/P99 latency, active connections, request body rejection.
- Accepted/rejected event rate, event batch duration.
- RabbitMQ queue depth, unacknowledged messages, oldest message age, retry and dead-letter counts.
- Worker busy slots, task duration, training duration/failure, checkpoint age.
- Inference request duration, in-flight count, local queue depth, timeout rate, fallback count.
- Funnel metrics by tenant/model: retrieval latency, candidates per source, union/deduplicated candidate count, filter drop count by bounded reason, scoring batch size/latency, ordering latency, final candidate count, precomputed-cache hit, and fallback tier.
- Model download, checksum, load, and warm-up duration.
- Desired/current/ready replicas, pending pods, HPA changes, unschedulable status.
- PostgreSQL connections/query latency/deadlocks; Redis memory/evictions; RustFS errors.
- Node CPU/memory/disk; pod restarts, OOM kills, and persistent-volume usage.

Tenant metrics use a bounded internal `tenant_id` label for the small MVP:

- request/event rate, rejected events, quota violations, attributed queued tasks, training jobs/failures, active version, desired/ready replicas, usage, storage, retrieval Recall@K, Hit@10, NDCG@10, catalog coverage, intra-list diversity, Top-N churn/Jaccard, observed CTR and conversion.

Do not label metrics with external user IDs, product IDs, session IDs, event IDs, request IDs, job IDs, or model artifact paths. Use logs/traces or PostgreSQL for high-cardinality investigation.

### Suggested dashboards

1. **Platform overview:** availability, API latency/errors, queue age, worker state, node saturation, stateful dependencies.
2. **Tenant operations:** selected tenant request/event rates, quotas, active version, model quality, desired/ready replicas, fallback rate.
3. **Training:** queued/running jobs, stage duration, failures, CPU/memory, checkpoint and artifact status.
4. **Serving/autoscaling:** per-deployment request/in-flight/CPU/latency, retrieval-filter-score-order stage timings/counts, candidate-source contribution, fallback tiers, HPA target, pending pods, startup phases.
5. **Data and storage:** PostgreSQL, Redis, RabbitMQ, RustFS, persistent volumes, artifact bytes.
6. **Security/audit:** failed auth, rate-limit events, tenant mismatch rejections, artifact validation failures.

### Alerts and example thresholds

| Severity | Alert | Initial threshold |
|---|---|---|
| Critical | API unavailable | No successful scrape/health for 2 min |
| Critical | PostgreSQL unavailable | Connection checks fail for 1 min |
| Critical | Cross-tenant validation failure | Any occurrence |
| Critical | Active tenant has zero ready replicas | 1 min |
| Warning | P95 inference latency high | >300 ms for 5 min at meaningful traffic |
| Warning | Error/timeout rate | >2% for 5 min |
| Warning | Queue oldest age | events >2 min or training >30 min |
| Warning | Desired > ready replicas | >3 min |
| Warning | Pod OOM/restart loop | 2 restarts in 10 min |
| Info | Model rollout started/completed | State transition |
| Info | HPA scale event | Replica count changes |

Thresholds are placeholders and must be load-tested.

### Visibility of Tenant A scenario

The serving dashboard must show: Tenant A request rise, A1 CPU/in-flight/latency rise, local queue growth, HPA desired replicas 1 to 2, A2 pending/init/model-download/warm-up/readiness, ready replicas reaching 2, queue and latency recovery, and later desired replicas returning to 1 after cooldown. Tenant B's panel remains at one desired/ready replica.

---

## 22. Pricing and usage metering

### Plans

Use the Free, Basic, and Pro limits from Section 20. Subscriptions are mocked records with start/end dates and no payment provider.

### Metered dimensions

- Accepted interaction events.
- Recommendation requests, including whether fallback was used.
- Training jobs and training CPU seconds.
- Stored products.
- Model artifact bytes.
- Active replica count and optional replica runtime minutes.

### Metering architecture

1. API/worker writes an idempotent `usage_events` row for billable actions. Each event has a stable source idempotency key such as `request:{request_id}:recommendation`.
2. Redis counters provide low-latency quota checks but are not the financial source of truth.
3. A scheduled Celery task aggregates durable usage events into `monthly_usage_aggregates` using upserts.
4. Reconciliation compares Redis counters, raw usage ledger, aggregate rows, and current storage/replica observations.
5. Billing periods are UTC calendar months for the demo.
6. Plan upgrades apply immediately to future quota checks. Downgrades are scheduled for next period unless current usage already fits the lower plan.
7. Counter updates use atomic Redis Lua scripts; durable inserts use unique idempotency constraints.
8. If Redis is unavailable, fail closed for expensive operations or use conservative PostgreSQL quota checks. Accepted usage must still be durable.

No real charge is calculated. A demo invoice endpoint may multiply measured units by mock prices and clearly label the result as non-payable.

---

## 23. PostgreSQL ER diagram

```mermaid
erDiagram
    TENANTS ||--o{ TENANT_USERS : has
    TENANTS ||--o{ API_KEYS : owns
    TENANTS ||--|| TENANT_SUBSCRIPTIONS : subscribes
    PRICING_PLANS ||--o{ TENANT_SUBSCRIPTIONS : defines
    TENANTS ||--|| TENANT_RESOURCE_QUOTAS : limits

    TENANTS ||--o{ EXTERNAL_USERS : owns
    TENANTS ||--o{ PRODUCTS : owns
    PRODUCTS ||--o{ PRODUCT_CATEGORY_ASSIGNMENTS : assigned
    PRODUCT_CATEGORIES ||--o{ PRODUCT_CATEGORY_ASSIGNMENTS : contains
    EXTERNAL_USERS ||--o{ INTERACTION_EVENTS : performs
    PRODUCTS ||--o{ INTERACTION_EVENTS : receives
    TENANTS ||--o{ EVENT_INGESTION_BATCHES : submits

    TENANTS ||--o{ DATASET_SNAPSHOTS : creates
    TENANTS ||--o{ TRAINING_JOBS : requests
    TRAINING_JOBS ||--o{ TRAINING_JOB_ATTEMPTS : retries
    TRAINING_JOBS ||--o{ TRAINING_METRICS : reports
    DATASET_SNAPSHOTS ||--o{ TRAINING_JOBS : used_by

    TENANTS ||--o{ MODELS : owns
    MODELS ||--o{ MODEL_VERSIONS : versions
    TRAINING_JOBS ||--o| MODEL_VERSIONS : produces
    MODEL_VERSIONS ||--o{ MODEL_EVALUATION_METRICS : measures
    MODEL_VERSIONS ||--o{ MODEL_DEPLOYMENTS : deploys
    MODEL_DEPLOYMENTS ||--o{ MODEL_DEPLOYMENT_REVISIONS : revisions
    MODEL_DEPLOYMENTS ||--o{ SERVING_REPLICAS : has
    MODEL_VERSIONS ||--o{ MODEL_ACTIVATION_HISTORY : activated

    TENANTS ||--o{ RECOMMENDATION_REQUESTS : requests
    RECOMMENDATION_REQUESTS ||--o{ RECOMMENDATION_RESULTS : returns
    RECOMMENDATION_REQUESTS ||--o{ RECOMMENDATION_IMPRESSIONS : displays
    RECOMMENDATION_IMPRESSIONS ||--o{ RECOMMENDATION_FEEDBACK : receives

    TENANTS ||--o{ TASK_RECORDS : owns
    TASK_RECORDS ||--o{ TASK_ATTEMPTS : attempts
    TASK_RECORDS ||--o{ OUTBOX_EVENTS : publishes
    TENANTS ||--o{ IDEMPOTENCY_KEYS : scopes
    TENANTS ||--o{ USAGE_EVENTS : meters
    TENANTS ||--o{ MONTHLY_USAGE_AGGREGATES : aggregates
    TENANTS ||--o{ AUDIT_LOGS : audits
    TENANTS ||--o{ SECURITY_EVENTS : records
```

The diagram omits some role/junction and operational relationships to remain readable. All tenant-owned tables still carry `tenant_id` even when it is derivable through another foreign key; this supports direct RLS and safer composite constraints.

---

## 24. Detailed table design

### Global tables without `tenant_id`

- `roles`: fixed permission role catalog.
- `pricing_plans`: global plan definitions.
- Optional `schema_migrations` and static `permissions` tables.

All other business/operational tables are tenant-owned or include tenant context for audit and RLS.

### Identity and tenancy

| Table | Key columns and types | Constraints/indexes | Delete and RLS |
|---|---|---|---|
| `tenants` | `id uuid PK`, `slug text`, `name text`, `status text`, `created_at timestamptz` | unique slug; status check | Soft-delete/tombstone; platform-admin policy |
| `tenant_users` | `id uuid PK`, `tenant_id uuid FK`, `email citext`, `password_hash text`, `status text` | unique `(tenant_id,email)`; index tenant/status | Cascade after retention; tenant RLS |
| `roles` | `id smallserial PK`, `name text`, `permissions jsonb` | unique name | Restrict delete; global read |
| `tenant_user_roles` | `tenant_id`, `tenant_user_id`, `role_id`, composite PK | FK tenant/user consistency | Cascade user; tenant RLS |
| `api_keys` | `id uuid`, `tenant_id`, `name`, `key_prefix`, versioned current/predecessor HMAC hashes, `scopes jsonb`, expiry/use/revocation/grace timestamps | unique tenant/name and current hash; tenant/time plus verifier lookup indexes | Revoke then retain audit; forced tenant RLS; no runtime delete |
| `service_credentials` | `id`, `tenant_id nullable for platform`, `name`, `secret_hash`, `audience`, expiry | unique active name per tenant | Revoke; restricted service policy |
| `pricing_plans` | `id`, `code`, `limits jsonb`, `is_active` | unique code | Restrict when referenced |
| `tenant_subscriptions` | `id`, `tenant_id`, `plan_id`, period dates, status | one current subscription partial unique | Retain billing history; tenant RLS |
| `tenant_resource_quotas` | `tenant_id PK`, numeric quota columns, `overrides jsonb` | non-negative checks | Cascade tenant; tenant RLS |

### Catalog and customers

| Table | Key columns and types | Constraints/indexes | Delete and RLS |
|---|---|---|---|
| `external_users` | `id uuid`, `tenant_id`, `external_user_id text`, attributes jsonb, `deleted_at` | unique `(tenant_id,external_user_id)` | Tombstone/anonymize; tenant RLS |
| `products` | `id uuid`, `tenant_id`, `external_product_id text`, title, price numeric, active bool, attributes jsonb | unique `(tenant_id,external_product_id)`; active index | Disable before delete; tenant RLS |
| `product_categories` | `id`, `tenant_id`, `external_category_id`, name | unique tenant/external category | Restrict/cascade assignments; tenant RLS |
| `product_category_assignments` | `tenant_id`, `product_id`, `category_id`, composite PK | composite tenant-consistent FKs | Cascade relation; tenant RLS |

### Interactions

| Table | Key columns and types | Constraints/indexes | Delete and RLS |
|---|---|---|---|
| `interaction_events` | `id uuid`, `tenant_id`, `event_id text`, user/product IDs, `event_type`, rating, weight, `occurred_at`, `received_at`, metadata jsonb | unique `(tenant_id,event_id)`; user/time, product/time, tenant/time indexes | Append-only; tombstone/anonymize corrections; tenant RLS |
| `event_ingestion_batches` | `id`, `tenant_id`, idempotency key, counts, status, timestamps | unique tenant/idempotency; status index | Retain operational period; tenant RLS |
| `event_processing_failures` | `id`, `tenant_id`, event/batch ref, error code, sanitized detail | tenant/time index | Retention policy; tenant RLS |

### Training

| Table | Key columns and types | Constraints/indexes | Delete and RLS |
|---|---|---|---|
| `dataset_snapshots` | `id`, `tenant_id`, cutoff, URI, checksum, counts, query/config jsonb | unique tenant/checksum when useful | Restrict while model references; tenant RLS |
| `training_jobs` | `id`, `tenant_id`, model ID, snapshot ID, status, config, deadline, cancellation flag, timestamps | status check; index tenant/status/created; partial unique active job per tenant | Retain history; tenant RLS |
| `training_job_attempts` | `id`, `tenant_id`, job ID, attempt no., worker, start/end, failure | unique job/attempt | Cascade only with job retention; tenant RLS |
| `training_metrics` | `id`, `tenant_id`, job ID, epoch, name, value double precision, recorded_at | unique job/epoch/name | Cascade job; tenant RLS |
| `training_log_references` | `id`, `tenant_id`, job ID, URI or log range, checksum | job/time index | Retention; tenant RLS |

### Models and deployments

| Table | Key columns and types | Constraints/indexes | Delete and RLS |
|---|---|---|---|
| `models` | `id`, `tenant_id`, name, type, default config, created_at | unique tenant/name | Restrict while versions exist; tenant RLS |
| `model_versions` | `id`, `tenant_id`, model ID, version int, status, framework fields, config, snapshot/job, artifact fields, metrics, timestamps, `is_active` | unique `(tenant_id,model_id,version)`; one active partial unique; checksum unique per tenant as appropriate | Archive before delete; tenant RLS |
| `model_evaluation_metrics` | `id`, `tenant_id`, version ID, split, metric, value | unique version/split/metric | Cascade version; tenant RLS |
| `model_deployments` | `id`, `tenant_id`, model ID, desired version ID, active version ID, status, desired/current/ready replicas, K8s names | one deployment row per tenant/model; non-negative counts | Stop before delete; tenant RLS |
| `model_deployment_revisions` | `id`, `tenant_id`, deployment ID, revision, version ID, status, manifest jsonb | unique deployment/revision | Retain rollback history; tenant RLS |
| `serving_replicas` | `id`, `tenant_id`, deployment ID, pod UID/name, node, version ID, status, readiness, start/end | unique pod UID; index tenant/deployment/status | Historical rows retained; tenant RLS |
| `model_activation_history` | `id`, `tenant_id`, model ID, from/to versions, actor, reason, timestamp | model/time index | Immutable audit; tenant RLS |

### Recommendations

| Table | Key columns and types | Constraints/indexes | Delete and RLS |
|---|---|---|---|
| `recommendation_requests` | `id`, `tenant_id`, external user/session hash, version ID, strategy, limit, requested_at, latency, status | tenant/requested desc index | Short retention/anonymization; tenant RLS |
| `recommendation_results` | `tenant_id`, request ID, rank, product ID, raw model score, final order score, candidate source, strategy | PK request/rank; product FK | Cascade request; tenant RLS; debug fields retention-bounded |
| `recommendation_impressions` | `id`, `tenant_id`, request ID, product ID, position, occurred_at, event ID | unique tenant/event ID | Append-only; tenant RLS |
| `recommendation_feedback` | `id`, `tenant_id`, impression/request, type, value, occurred_at, event ID | unique tenant/event ID | Append-only; tenant RLS |

### Queues and operations

| Table | Key columns and types | Constraints/indexes | Delete and RLS |
|---|---|---|---|
| `task_records` | `id`, `tenant_id`, job ID nullable, task type, status, idempotency key, correlation ID, payload ref, timestamps | unique tenant/idempotency; status/created index | Retention; tenant RLS |
| `task_attempts` | `id`, `tenant_id`, task ID, attempt, status, worker, error, timestamps | unique task/attempt | Cascade task; tenant RLS |
| `outbox_events` | `id`, `tenant_id`, task ID, topic/routing key, payload jsonb, attempts, available_at, claimed_at, published_at, last_error | unique task/routing key; unpublished/available index | Append until published, then retain briefly; tenant RLS plus restricted publisher policy |
| `idempotency_keys` | `id`, `tenant_id`, key, operation, request hash, response ref, expires_at | unique tenant/key/operation | TTL cleanup; tenant RLS |
| `distributed_locks` | `id`, `tenant_id`, resource type/id, owner, lease expiry, fencing token | unique resource lock | Expiry cleanup; restricted RLS |

### Usage, monitoring, security

| Table | Key columns and types | Constraints/indexes | Delete and RLS |
|---|---|---|---|
| `usage_events` | `id`, `tenant_id`, type, quantity numeric, source id, idempotency key, occurred_at | unique tenant/idempotency; tenant/time index; quantity >=0 | Immutable ledger; tenant RLS |
| `monthly_usage_aggregates` | `tenant_id`, period date, type, quantity | PK tenant/period/type; non-negative | Retain billing history; tenant RLS |
| `tenant_resource_usage` | `tenant_id`, sampled_at, CPU, memory, storage, replicas | tenant/time index | Time-based retention; tenant RLS |
| `rate_limit_events` | `id`, `tenant_id`, endpoint class, limit, observed, occurred_at | tenant/time index | Short retention; tenant RLS |
| `replica_usage_records` | `id`, `tenant_id`, deployment/revision, replica, start/end, runtime seconds | non-negative runtime | Retain usage window; tenant RLS |
| `audit_logs` | `id`, `tenant_id`, actor, action, resource, before/after redacted jsonb, occurred_at | tenant/time and action indexes | Append-only, long retention; tenant RLS |
| `security_events` | `id`, `tenant_id nullable`, type, severity, source, sanitized detail, occurred_at | severity/time index | Restricted access and retention |

### Partitioning decision

Do **not** partition `interaction_events` initially. Correct RLS, constraints, indexes, and training queries are more important. Add monthly range partitioning only when a load test shows vacuum, retention, or query performance problems at several million rows. Partitioning is a future optimization because it increases migration, uniqueness, and retention complexity.

Interaction events are append-only. Corrections use compensating events or a `supersedes_event_id`; privacy deletion anonymizes user linkage or adds tombstones while preserving aggregate integrity where policy permits.

---

## 25. Important SQL DDL examples

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TYPE training_job_status AS ENUM (
  'queued', 'waiting_for_resources', 'preparing_data', 'building_graph',
  'training', 'evaluating', 'registering', 'deploying', 'succeeded',
  'failed', 'cancelling', 'cancelled'
);

CREATE TABLE tenants (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug citext NOT NULL UNIQUE,
  name text NOT NULL,
  status text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active','suspended','deleting','deleted')),
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE products (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  external_product_id text NOT NULL,
  title text NOT NULL,
  price numeric(14,2) CHECK (price IS NULL OR price >= 0),
  is_active boolean NOT NULL DEFAULT true,
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, external_product_id),
  UNIQUE (tenant_id, id)
);
CREATE INDEX products_tenant_active_idx ON products (tenant_id, is_active);

CREATE TABLE external_users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  external_user_id text NOT NULL,
  attributes jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  UNIQUE (tenant_id, external_user_id),
  UNIQUE (tenant_id, id)
);

CREATE TABLE interaction_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  event_id text NOT NULL,
  external_user_id text NOT NULL,
  external_product_id text NOT NULL,
  event_type text NOT NULL CHECK (event_type IN (
    'product_view','product_click','add_to_cart','remove_from_cart','purchase','rating'
  )),
  rating numeric(4,2),
  configured_weight numeric(8,3),
  occurred_at timestamptz NOT NULL,
  received_at timestamptz NOT NULL DEFAULT now(),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (tenant_id, event_id)
);
CREATE INDEX interaction_user_time_idx
  ON interaction_events (tenant_id, external_user_id, occurred_at DESC);
CREATE INDEX interaction_product_time_idx
  ON interaction_events (tenant_id, external_product_id, occurred_at DESC);
CREATE INDEX interaction_tenant_time_idx
  ON interaction_events (tenant_id, occurred_at);

CREATE TABLE training_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  model_id uuid,
  dataset_snapshot_id uuid,
  status training_job_status NOT NULL DEFAULT 'queued',
  configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
  random_seed bigint NOT NULL,
  requested_by uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  deadline_at timestamptz,
  cancellation_requested_at timestamptz,
  failure_reason text,
  UNIQUE (tenant_id, id)
);
CREATE INDEX training_jobs_tenant_status_created_idx
  ON training_jobs (tenant_id, status, created_at);
CREATE UNIQUE INDEX one_active_training_job_per_tenant
  ON training_jobs (tenant_id)
  WHERE status IN ('queued','waiting_for_resources','preparing_data','building_graph',
                   'training','evaluating','registering','deploying','cancelling');

CREATE TABLE models (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name text NOT NULL,
  model_type text NOT NULL,
  default_configuration jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, name),
  UNIQUE (tenant_id, id)
);

CREATE TABLE model_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  model_id uuid NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  status text NOT NULL CHECK (status IN (
    'registered','eligible','active','retired','rejected','archived','failed_deployment'
  )),
  framework text NOT NULL,
  framework_version text NOT NULL,
  code_version text NOT NULL,
  model_configuration jsonb NOT NULL,
  hyperparameters jsonb NOT NULL,
  dataset_snapshot_id uuid NOT NULL,
  training_job_id uuid NOT NULL,
  event_cutoff_timestamp timestamptz NOT NULL,
  artifact_uri text NOT NULL,
  artifact_checksum text NOT NULL,
  artifact_size bigint NOT NULL CHECK (artifact_size >= 0),
  hit_at_10 double precision,
  ndcg_at_10 double precision,
  training_loss double precision,
  validation_loss double precision,
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid,
  activated_at timestamptz,
  retired_at timestamptz,
  failure_reason text,
  parent_model_version_id uuid,
  rollback_target_id uuid,
  is_active boolean NOT NULL DEFAULT false,
  FOREIGN KEY (tenant_id, model_id) REFERENCES models(tenant_id, id),
  UNIQUE (tenant_id, model_id, version),
  UNIQUE (tenant_id, id)
);
CREATE INDEX model_versions_tenant_status_created_idx
  ON model_versions (tenant_id, status, created_at DESC);
CREATE UNIQUE INDEX one_active_version_per_model
  ON model_versions (tenant_id, model_id) WHERE is_active;

CREATE TABLE model_deployments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  model_id uuid NOT NULL,
  desired_model_version_id uuid,
  active_model_version_id uuid,
  status text NOT NULL CHECK (status IN (
    'pending','progressing','available','degraded','rolling_back','stopped'
  )),
  desired_replicas integer NOT NULL DEFAULT 1 CHECK (desired_replicas >= 0),
  current_replicas integer NOT NULL DEFAULT 0 CHECK (current_replicas >= 0),
  ready_replicas integer NOT NULL DEFAULT 0 CHECK (ready_replicas >= 0),
  kubernetes_deployment_name text,
  kubernetes_service_name text,
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, model_id) REFERENCES models(tenant_id, id),
  UNIQUE (tenant_id, model_id),
  UNIQUE (tenant_id, id)
);

CREATE TABLE task_records (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  job_id uuid,
  task_type text NOT NULL,
  status text NOT NULL CHECK (status IN (
    'pending','published','claimed','running','succeeded','failed','dead_lettered','cancelled'
  )),
  idempotency_key text NOT NULL,
  correlation_id uuid NOT NULL,
  schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version > 0),
  payload_ref jsonb NOT NULL DEFAULT '{}'::jsonb,
  lease_owner text,
  lease_expires_at timestamptz,
  fencing_token bigint NOT NULL DEFAULT 0 CHECK (fencing_token >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE (tenant_id, idempotency_key),
  UNIQUE (tenant_id, id)
);
CREATE INDEX task_records_ready_idx
  ON task_records (status, created_at)
  WHERE status IN ('pending','published');

CREATE TABLE usage_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  usage_type text NOT NULL,
  quantity numeric(20,4) NOT NULL CHECK (quantity >= 0),
  source_id text NOT NULL,
  idempotency_key text NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, idempotency_key)
);
CREATE INDEX usage_events_tenant_occurred_idx
  ON usage_events (tenant_id, occurred_at);

CREATE TABLE outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  task_record_id uuid NOT NULL,
  routing_key text NOT NULL,
  payload jsonb NOT NULL,
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  claimed_at timestamptz,
  published_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, task_record_id) REFERENCES task_records(tenant_id, id),
  UNIQUE (tenant_id, task_record_id, routing_key)
);
CREATE INDEX outbox_ready_idx
  ON outbox_events (available_at, created_at)
  WHERE published_at IS NULL;
```

One active deployment per tenant/model is enforced similarly with a partial unique index. Replica counts use checks such as `desired_replicas >= 0`, `ready_replicas >= 0`, and `ready_replicas <= desired_replicas` except during carefully modeled transitional observations.

---

## 26. Row-Level Security policies

### Application transaction pattern

```sql
BEGIN;
SELECT set_config('app.current_tenant_id', :tenant_id::text, true);
-- Repository queries here
COMMIT;
```

The third argument `true` makes the setting transaction-local. Do not use a persistent session `SET` with a connection pool.

### Generic policy example

```sql
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE products FORCE ROW LEVEL SECURITY;

CREATE POLICY products_tenant_select ON products
FOR SELECT TO graphrec_app
USING (
  tenant_id = current_setting('app.current_tenant_id', true)::uuid
);

CREATE POLICY products_tenant_modify ON products
FOR ALL TO graphrec_app
USING (
  tenant_id = current_setting('app.current_tenant_id', true)::uuid
)
WITH CHECK (
  tenant_id = current_setting('app.current_tenant_id', true)::uuid
);
```

Apply equivalent policies to every tenant-owned table. A safer helper function may return NULL or raise a controlled error when tenant context is absent.

### Roles

- `graphrec_app`: normal API/worker queries; no `BYPASSRLS`; not table owner.
- `graphrec_controller`: tenant-scoped registry reads plus restricted global deployment reconciliation view; no arbitrary tenant writes.
- `graphrec_admin`: tightly controlled operational role for approved cross-tenant support, preferably through audited security-definer functions.
- `graphrec_migrator`: table owner/migration role, unavailable to runtime pods.
- PostgreSQL superuser is never used by the application.

### Connection-pooling requirements

- Always open an explicit transaction before setting tenant context.
- `SET LOCAL`/`set_config(..., true)` occurs before any tenant query.
- Roll back on all exceptions.
- Add a checkout/checkin assertion in tests that `current_setting('app.current_tenant_id', true)` is empty outside transactions.
- Worker tasks use the same wrapper as HTTP requests.
- Cross-tenant platform jobs iterate tenants and open a new tenant-scoped transaction for each tenant rather than disabling RLS broadly.

### Background-worker bootstrap

The worker must learn tenant context without owning a broad `BYPASSRLS` role. Use a narrowly scoped `SECURITY DEFINER` function such as `claim_task(task_id, message_tenant_id, worker_id)` with a fixed `search_path`. It verifies that the durable task tenant equals the envelope tenant, atomically leases the task, returns only the tenant ID and fencing token, and writes an audit/attempt record. The worker then opens a new normal `graphrec_app` transaction, sets `SET LOCAL app.current_tenant_id`, and re-reads all tenant-owned data under RLS.

### Preventing cross-tenant joins

- Include `tenant_id` in join predicates even when UUID IDs are globally unique.
- Prefer composite unique keys `(tenant_id,id)` and composite foreign keys for sensitive relationships.
- Repository tests inspect generated SQL or results with colliding external IDs across tenants.
- Avoid security-definer functions unless necessary; fix `search_path` and audit all use.

### Explicit security test

```python
@pytest.mark.parametrize("resource", [
    "products", "interaction-events", "training-jobs", "model-versions",
    "model-artifacts", "deployment", "recommendation-history"
])
def test_tenant_a_cannot_access_tenant_b(resource, client_a, tenant_b_fixture):
    response = client_a.get(tenant_b_fixture.url_for(resource))
    assert response.status_code in {403, 404}
    assert "tenant_b" not in response.text
```

Add direct SQL tests: set context to Tenant A and query known Tenant B UUIDs; each query must return zero rows, and inserts with `tenant_id=B` must fail `WITH CHECK`.

---

## 27. API specification

All public endpoints use HTTPS, versioned paths, JSON, request-size limits, and tenant resolution from credentials. Administrative user endpoints use a short-lived bearer token; server-to-server SDK endpoints use an API key. `tenant_id` is never a trusted public field.

### Tenant, authentication, and usage

| Method/path | Auth/permission | Important input/output | Idempotency, limits, failures |
|---|---|---|---|
| `POST /v1/tenants` | Public demo registration | name, admin email -> tenant/admin | Idempotency-Key; strict signup limit; 409 duplicate |
| `POST /v1/auth/login` | Email/password | access/refresh token | Brute-force limit; 401/429 |
| `GET /v1/api-keys` | Bearer `keys:write` | redacted owned key list | No tenant selector; ten admin operations/minute |
| `GET /v1/api-keys/{id}` | Bearer `keys:write` | redacted owned key status | Foreign/missing same 404 |
| `POST /v1/api-keys` | Bearer `keys:write` | name, scopes, expiry -> one-time secret | 25 active keys; role delegation; 403/409/429 |
| `POST /v1/api-keys/{id}/rotate` | Bearer `keys:write` | grace period -> new secret | Audited; 404/409 |
| `DELETE /v1/api-keys/{id}` | Bearer `keys:write` | revoke | Repeated revoke safe; 404 |
| `GET /v1/subscription` | API key or bearer `billing:read` | plan, period, limits | Per-minute limit |
| `GET /v1/usage` | API key or bearer `usage:read` | counters, limits, reset | Cached; 503 if source unavailable |

### Catalog

| Method/path | Auth/permission | Important input/output | Idempotency, limits, failures |
|---|---|---|---|
| `PUT /v1/products/{external_id}` | API key `catalog:write` | product fields -> product | Naturally idempotent; 413/422/429 |
| `POST /v1/products:bulk-upsert` | API key `catalog:write` | max bounded product list -> counts | Idempotency-Key; size/product quota |
| `PATCH /v1/products/{external_id}` | API key `catalog:write` | partial fields -> product | Optional If-Match; 404/409 |
| `POST /v1/products/{external_id}:disable` | API key `catalog:write` | reason -> disabled | Repeated safe; 404 |
| `GET /v1/products` | API key `catalog:read` | cursor/filter -> page | Rate limited; max page size |

### Events

| Method/path | Auth/permission | Important input/output | Idempotency, limits, failures |
|---|---|---|---|
| `POST /v1/events` | API key `events:write` | event_id, user, product, type, occurred_at | `(tenant,event_id)` idempotent; 202/200 duplicate; 422/429 |
| `POST /v1/events/batches` | API key `events:write` | bounded events -> batch ID/counts | Header plus event IDs; payload limit; 413/422/429 |
| `GET /v1/events/batches/{id}` | API key `events:read` | status/counts/failures | RLS 404 for foreign ID |

### Training

| Method/path | Auth/permission | Important input/output | Idempotency, limits, failures |
|---|---|---|---|
| `POST /v1/training-jobs` | Bearer/API key `training:write` | model type/config -> job | Idempotency-Key; 409 active/cooldown; 429 quota; 422 insufficient data |
| `GET /v1/training-jobs` | `training:read` | cursor/status -> jobs | Bounded page |
| `GET /v1/training-jobs/{id}` | `training:read` | state/stage/progress/errors | 404 foreign/missing |
| `POST /v1/training-jobs/{id}:cancel` | `training:write` | reason -> cancelling | Repeated safe; 409 terminal |
| `GET /v1/training-jobs/{id}/metrics` | `training:read` | offline metrics/history | Rate/page limits |

### Models

| Method/path | Auth/permission | Important input/output | Idempotency, limits, failures |
|---|---|---|---|
| `GET /v1/models` | `models:read` | model list | Bounded page |
| `GET /v1/models/{model_id}/versions` | `models:read` | versions/metrics/status | 404 foreign |
| `GET /v1/model-versions/{id}` | `models:read` | metadata, no raw secret URI | 404 |
| `POST /v1/model-versions/{id}:activate` | `models:deploy` | reason -> revision | Idempotent if already active; 409 ineligible; 429 replica/plan |
| `POST /v1/models/{id}:rollback` | `models:deploy` | target version/reason | Audited; 409 invalid target |
| `POST /v1/model-versions/{id}:archive` | `models:write` | reason -> archived | Cannot archive active/rollback-needed version |

### Serving and feedback

Use `POST /v1/recommendations` rather than placing user/session context in a query string. The call remains synchronous; a stable `request_id` makes metering and safe SDK retries idempotent without caching a stale recommendation indefinitely.


| Method/path | Auth/permission | Important input/output | Idempotency, limits, failures |
|---|---|---|---|
| `POST /v1/recommendations` | API key `recommendations:read` | request_id, external user/session, recent events, page/context, limit, exclusions, eligibility hints, allow_fallback -> ranked products/version/strategy | Retries use request_id for metering deduplication; bounded recent sequence/candidate rules; strict RPM/concurrency; 404 user optional, 429, 503 |
| `POST /v1/recommendations/session` | same | anonymous/session recent events, context and exclusions -> ranked items | Request ID; payload/sequence limit; cold-start strategy reported |
| `POST /v1/feedback/impressions` | API key `events:write` | event ID, request, products/positions | Event idempotency; 422/429 |
| `POST /v1/feedback/clicks` | same | event ID, impression/product/time | Event idempotency |
| `POST /v1/feedback/conversions` | same | event ID, request/product/value/time | Event idempotency |

### Deployment and monitoring

| Method/path | Auth/permission | Important input/output | Idempotency, limits, failures |
|---|---|---|---|
| `GET /v1/deployment` | `deployments:read` | active version/status | 404 no deployment |
| `GET /v1/deployment/replicas` | `deployments:read` | desired/current/ready and pod states | Sanitized node/pod detail |
| `GET /v1/deployment/autoscaling` | `deployments:read` | min/max/targets/recent actions | 503 metrics unavailable |
| `GET /v1/metrics/summary` | `metrics:read` | tenant request, usage, model quality summary | Cached and bounded |

### Common failure contract

```json
{
  "error": {
    "code": "quota_exceeded",
    "message": "Recommendation concurrency limit reached",
    "correlation_id": "uuid",
    "retryable": true,
    "retry_after_seconds": 2
  }
}
```

Use 400 malformed semantics, 401 invalid credential, 403 insufficient scope, 404 missing or foreign tenant resource, 409 state conflict, 413 too large, 422 schema/domain validation, 429 quota/rate, and 503 temporary platform capacity/dependency failure.

---

## 28. SDK design and example

### Python interface

```python
from graphrec import GraphRecClient

client = GraphRecClient(
    api_key="gr_live_...",
    base_url="https://graphrec.example.edu",
    timeout=1.0,
)

client.upsert_product(external_product_id="sku-42", title="Travel Mug", price=19.99)
client.upsert_products([...])
client.track_event(
    event_id="evt-1001",
    external_user_id="customer-7",
    external_product_id="sku-42",
    event_type="product_view",
    occurred_at="2026-08-01T00:00:00Z",
)
recommendations = client.get_recommendations(
    external_user_id="customer-7",
    top_n=10,
    recent_events=[{"product_id": "sku-42", "event_type": "product_view"}],
    context={"page": "homepage", "locale": "en-BD"},
    exclude_product_ids=[],
    allow_fallback=True,
)
job = client.create_training_job(model_type="simplified_dgsr")
status = client.get_training_status(job.id)
models = client.list_models()
client.activate_model(models[0].versions[-1].id)
usage = client.get_usage()
deployment = client.get_deployment_status()
```

### SDK behavior

- Sends `Authorization: ApiKey <secret>`, `User-Agent`, and `X-GraphRec-SDK-Version`; the public API never accepts `tenant_id`.
- Default connect/read timeout is explicit and configurable.
- Retries safe reads and idempotent writes, including recommendation POSTs carrying a stable `request_id`, on network error, 429, and selected 503 responses using exponential backoff with jitter and server `Retry-After`.
- Generates `Idempotency-Key` for bulk upsert, event batches, and training requests when the caller does not provide one.
- Splits batches to server maximums and reports per-item failures.
- Provides typed request/response models and errors: `AuthenticationError`, `PermissionError`, `ValidationError`, `RateLimitError`, `ConflictError`, `ServiceUnavailableError`.
- Offers `GraphRecAsyncClient` using `httpx.AsyncClient` after the synchronous client is stable.
- Never accepts `tenant_id` or tenant-impersonation headers.

### E-commerce backend integration

```python
from datetime import datetime, timezone
from fastapi import FastAPI
from graphrec import GraphRecClient, GraphRecError

app = FastAPI()
graphrec = GraphRecClient(
    api_key=settings.GRAPHREC_API_KEY,
    base_url=settings.GRAPHREC_BASE_URL,
    timeout=0.9,
)

@app.post("/shop/products/{sku}/view")
def product_view(sku: str, customer_id: str):
    event_id = f"view:{customer_id}:{sku}:{int(datetime.now(timezone.utc).timestamp())}"
    graphrec.track_event(
        event_id=event_id,
        external_user_id=customer_id,
        external_product_id=sku,
        event_type="product_view",
        occurred_at=datetime.now(timezone.utc),
    )
    return {"accepted": True}

@app.get("/shop/recommendations")
def recommendations(customer_id: str):
    try:
        result = graphrec.get_recommendations(
            external_user_id=customer_id,
            top_n=10,
            allow_fallback=True,
        )
        return {"products": [item.external_product_id for item in result.items]}
    except GraphRecError:
        return {"products": local_store_popular_products(limit=10)}
```

A Node.js SDK can later share an OpenAPI-generated model layer plus a small handwritten retry/idempotency wrapper. Browser JavaScript should generally call the tenant's own backend, not expose a privileged GraphRec API key.

---

## 29. Docker Compose deployment

### Services

```text
api
postgres
rabbitmq
redis
worker-general
worker-training
inference-a
inference-b
rustfs
scheduler-outbox
deployment-controller-local (mock or disabled)
prometheus
grafana
demo-shop (optional)
```

Use one application image with different commands. `scheduler-outbox` polls PostgreSQL for unpublished outbox rows and scheduled work, then publishes with RabbitMQ confirmation. Bind named volumes for PostgreSQL, RabbitMQ, RustFS, Prometheus, and Grafana. Health checks gate startup; migrations run as a one-shot service.

### Compose skeleton

The repository should contain a complete file; the following skeleton shows the required process separation and dependencies without embedding secrets:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: graphrec
      POSTGRES_USER: graphrec_owner
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: ["pg_data:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U graphrec_owner -d graphrec"]
      interval: 5s
      timeout: 3s
      retries: 20

  rabbitmq:
    image: rabbitmq:4-management-alpine
    environment:
      RABBITMQ_DEFAULT_USER: graphrec
      RABBITMQ_DEFAULT_PASS: ${RABBITMQ_PASSWORD}
    volumes: ["rabbit_data:/var/lib/rabbitmq"]
    ports: ["15672:15672"]
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 5s
      timeout: 5s
      retries: 20

  redis:
    image: redis:8-alpine
    command: ["redis-server", "--appendonly", "yes", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
    volumes: ["redis_data:/data"]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 20

  rustfs:
    image: rustfs/rustfs:latest
    command: server /data --console-address :9001
    environment:
      RUSTFS_ROOT_USER: ${RUSTFS_ROOT_USER}
      RUSTFS_ROOT_PASSWORD: ${RUSTFS_ROOT_PASSWORD}
    volumes: ["rustfs_data:/data"]
    ports: ["9001:9001"]

  migrate:
    build: .
    command: ["alembic", "upgrade", "head"]
    environment: &app_env
      DATABASE_URL: postgresql+psycopg://graphrec_owner:${POSTGRES_PASSWORD}@postgres:5432/graphrec
      CELERY_BROKER_URL: amqp://graphrec:${RABBITMQ_PASSWORD}@rabbitmq:5672//
      REDIS_URL: redis://redis:6379/0
      S3_ENDPOINT_URL: http://rustfs:9000
    depends_on:
      postgres: {condition: service_healthy}

  api:
    build: .
    command: ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
    environment: *app_env
    ports: ["8000:8000"]
    depends_on:
      migrate: {condition: service_completed_successfully}
      rabbitmq: {condition: service_healthy}
      redis: {condition: service_healthy}

  scheduler-outbox:
    build: .
    command: ["python", "-m", "apps.scheduler_outbox.main"]
    environment: *app_env
    depends_on:
      migrate: {condition: service_completed_successfully}
      rabbitmq: {condition: service_healthy}

  worker-general:
    build: .
    command: ["celery", "-A", "apps.worker.celery_app", "worker", "-Q", "events.default,dataset.prepare,evaluation,artifact.registration,deployment,usage,housekeeping", "--concurrency=2"]
    environment: *app_env
    depends_on:
      scheduler-outbox: {condition: service_started}

  worker-training:
    build: .
    command: ["celery", "-A", "apps.worker.celery_app", "worker", "-Q", "training.free,training.basic,training.pro,graph.build", "--concurrency=1"]
    environment: *app_env
    deploy:
      resources:
        limits: {cpus: "2.0", memory: 4G}
    depends_on:
      scheduler-outbox: {condition: service_started}

  inference-a:
    build: .
    command: ["uvicorn", "apps.inference.main:app", "--host", "0.0.0.0", "--port", "8001"]
    environment:
      <<: *app_env
      GRAPHREC_TENANT_ID: ${TENANT_A_ID}
      GRAPHREC_MODEL_VERSION_ID: ${TENANT_A_MODEL_VERSION_ID}
      GRAPHREC_ARTIFACT_URI: ${TENANT_A_ARTIFACT_URI}
      GRAPHREC_ARTIFACT_SHA256: ${TENANT_A_ARTIFACT_SHA256}

  inference-b:
    build: .
    command: ["uvicorn", "apps.inference.main:app", "--host", "0.0.0.0", "--port", "8001"]
    environment:
      <<: *app_env
      GRAPHREC_TENANT_ID: ${TENANT_B_ID}
      GRAPHREC_MODEL_VERSION_ID: ${TENANT_B_MODEL_VERSION_ID}
      GRAPHREC_ARTIFACT_URI: ${TENANT_B_ARTIFACT_URI}
      GRAPHREC_ARTIFACT_SHA256: ${TENANT_B_ARTIFACT_SHA256}

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./ops/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana:latest
    volumes:
      - grafana_data:/var/lib/grafana
      - ./ops/grafana:/etc/grafana/provisioning:ro
    ports: ["3000:3000"]
    depends_on: [prometheus]

volumes:
  pg_data: {}
  rabbit_data: {}
  redis_data: {}
  rustfs_data: {}
  prometheus_data: {}
  grafana_data: {}
```

Pin tested image versions in the actual repository rather than relying on `latest`. Use separate owner, migration, runtime, and RLS-enforced database roles; the simplified environment block above is architectural, not a production secret layout.

### Local model serving

Docker Compose cannot demonstrate Kubernetes scheduling, HPA, anti-affinity, or Service endpoint readiness in the same way. It can demonstrate tenant-pinned processes and load balancing:

- Start `inference-a-1`, `inference-a-2`, and `inference-b-1` as separate services or scale a generic inference service with generated tenant-specific Compose overrides.
- Put an Nginx/Traefik local proxy in front of Tenant A's two replicas.
- Run a script that starts the second Tenant A container after a load threshold to simulate scale-out, then stops it after cooldown.
- Assert both A replicas use the same artifact checksum and B uses a different one.

Docker Compose remains the primary development environment for API, RLS, queue workflows, training, registry, inference, metering, and dashboards.

---

## 30. Three-node k3s deployment

### Three-node Kubernetes deployment diagram

```mermaid
flowchart TB
    INGRESS[Traefik / Ingress]

    subgraph NODE1[Node 1 - online]
        API[FastAPI API]
        A1[Tenant A Replica A1]
        PROM[Prometheus]
    end

    subgraph NODE2[Node 2 - mixed]
        B1[Tenant B Replica B1]
        TRAIN[Training worker]
        RABBIT[RabbitMQ]
        REDIS[Redis]
    end

    subgraph NODE3[Node 3 - state/control/spare]
        PG[PostgreSQL]
        RUSTFS[RustFS]
        CTRL[Deployment controller]
        GEN[General worker plus scheduler/outbox]
        A2[Tenant A Replica A2 when scaled]
    end

    INGRESS --> API
    API --> A1
    API --> A2
    API --> B1
    API --> PG
    API --> REDIS
    GEN --> RABBIT
    TRAIN --> RABBIT
    TRAIN --> RUSTFS
    CTRL --> PG
```

Actual placement is a scheduler outcome constrained by requests, affinity preferences, taints, and available volumes. The diagram is a demonstrable target, not a promise that every pod always remains on that node.

### Networking and routing

- Ingress exposes only public API/admin routes.
- Per-tenant inference Services are ClusterIP and unreachable externally.
- API resolves tenant route from deployment metadata and calls the internal Service DNS name.
- NetworkPolicy, if supported by the selected k3s CNI, allows API to inference, workers/controller to stateful dependencies, and denies unnecessary lateral traffic. Do not make NetworkPolicy the only isolation control.

### Controller permissions

A dedicated Kubernetes service account may get create/get/list/watch/patch/update/delete only for Deployments, ReplicaSets as needed, Services, HPAs, ConfigMaps, Events, and selected pod status in the GraphRec namespace. It cannot read arbitrary cluster Secrets or mutate nodes/RBAC.

### Stateful services in the demo

Running PostgreSQL, RabbitMQ, Redis, and RustFS inside the cluster is acceptable for the university demonstration because it makes the environment self-contained. It is not equivalent to managed production infrastructure, multi-zone persistence, tested backups, or enterprise high availability. Use persistent volumes and document restore steps.


---

## 31. Resource requests and limits

Initial values are starting points for load testing, not guarantees.

| Workload | Replicas | CPU request/limit | Memory request/limit | Storage | Priority |
|---|---:|---:|---:|---:|---|
| FastAPI API | 1, optionally 2 | 250m / 750m | 256 MiB / 768 MiB | none | high-online |
| Tenant inference pod | 1-3 per tenant | 500m / 1 CPU | 768 MiB / 1.5 GiB | `emptyDir` 1-2 GiB | high-online |
| Artifact init container | per pod startup | 100m / 500m | 128 / 512 MiB | shared `emptyDir` | inherits pod |
| General worker | 1 | 250m / 750m | 256 / 768 MiB | none | normal |
| Training worker | 1 | 1 CPU / 2 CPU | 2 GiB / 4 GiB | temp 2-5 GiB | low-batch |
| Deployment controller | 1 | 100m / 300m | 128 / 384 MiB | none | normal |
| Scheduler | 1 | 50m / 200m | 96 / 256 MiB | none | normal |
| PostgreSQL | 1 | 500m / 2 CPU | 1 / 3 GiB | 20+ GiB PV | stateful |
| RabbitMQ | 1 | 250m / 1 CPU | 512 MiB / 1.5 GiB | 5+ GiB PV | stateful |
| Redis | 1 | 100m / 500m | 256 / 768 MiB | 1-2 GiB PV optional | stateful |
| RustFS | 1 | 250m / 1 CPU | 512 MiB / 1.5 GiB | 20+ GiB PV | stateful |
| Prometheus | 1 | 250m / 750m | 512 MiB / 1.5 GiB | 10+ GiB PV | monitoring |
| Grafana | 1 | 100m / 300m | 128 / 384 MiB | 1 GiB PV | monitoring |

### Protection of inference from training

- Inference and API use a higher PriorityClass.
- Training concurrency is one and has strict CPU/memory limits.
- The scheduler gives training a preferred affinity for a node without active inference; this is best effort.
- A platform pressure rule stops admitting new training jobs when online P95, queue depth, or node CPU exceeds a threshold.
- Kubernetes may evict lower-priority training before online pods under pressure, but persistent checkpoints are required because eviction remains possible.
- Reserve at least one schedulable inference-sized resource slot when demonstrating autoscaling. This may mean deliberately underutilizing the cluster at baseline.

### Persistent volumes

Use local-path storage for the demo with clear node-loss limitations. PostgreSQL and RustFS require backup/export scripts before the final demonstration. RabbitMQ durability is useful, but task records in PostgreSQL and idempotent stages allow rebuilding messages after broker loss.

---

## 32. Failure handling and recovery

| Failure | Expected behavior | Recovery |
|---|---|---|
| One inference pod fails | Service removes unready endpoint. If another replica exists, requests continue; if it was the only replica, brief 503/fallback occurs | Deployment recreates pod; init re-downloads pinned artifact |
| One k3s node fails | Pods on that node disappear. Stateless pods may reschedule if capacity exists; local PV stateful services may remain unavailable | Manual node recovery or restore; do not claim HA |
| PostgreSQL unavailable | Authentication cache may be insufficient for safe writes; most APIs fail 503; inference may serve a very short cached route only if policy allows | Stop accepting mutable work, alert, restore/restart DB |
| RabbitMQ unavailable | API operations that commit task plus outbox state may still return accepted; async execution pauses and queue-age alerts rise | Outbox publisher retries with backoff and publisher confirms after broker recovery |
| Redis unavailable | Rate limit/locks/cache unavailable; expensive operations fail closed or use conservative DB path; normal inference may be reduced | Reconnect, rebuild counters from durable ledger |
| RustFS unavailable | Existing loaded replicas continue; new training registration and new pod starts fail; rolling update must not remove old pods | Alert and restore RustFS before rollout |
| Model loading fails | Pod never becomes ready; old version remains during rolling update | Mark revision failed; inspect checksum/config; rollback |
| Autoscaling cannot schedule pod | Existing replicas serve; pending state visible; bounded queue/rate limiting activates | Free resources, pause training, lower load, or add capacity outside MVP |
| Training worker crashes | RabbitMQ redelivers after visibility/connection recovery; idempotency and checkpoint resume | New attempt acquires lock/fencing token and resumes |
| Controller crashes | Existing Deployments keep serving; desired changes pause | Kubernetes restarts controller; leader lock expires; reconcile from DB |
| Usage aggregation fails | Raw idempotent usage events remain durable | Retry aggregate; reconcile next run |

### Transactional outbox (selected)

For every API operation that must both commit PostgreSQL state and publish a task, insert an `outbox_events` row in the same transaction. The standalone scheduler/outbox process claims rows with `FOR UPDATE SKIP LOCKED`, publishes with confirmation, and sets `published_at`. Duplicate publication is harmless because tasks are idempotent. This closes the database/broker dual-write gap without introducing a large orchestration platform.

### Graceful degradation

- Never switch to another tenant's model.
- Prefer stale-but-known tenant popular products over cross-tenant or unvalidated results.
- Do not activate a new version while RustFS, PostgreSQL, or readiness checks are unhealthy.
- Record correlation IDs and state transitions so the demonstration can explain failures.

---

## 33. Security design

### Identity and access

- Hash tenant-user passwords with Argon2id. Generate API keys as `gr_live_` plus unpadded Base64URL for 32 random bytes; store only `gr_live_` plus the first eight encoded characters and `HMAC-SHA-256(server_pepper, full_key)` for indexed lookup and constant-time verification. Persist a hash version for pepper rotation; one-time secrets are never replayed or recovered.
- Issue short-lived bearer access tokens for tenant administrators. Refresh tokens are rotated and revocable.
- API keys have scopes, expiry, last-used time, rotation, and revocation.
- Resolve tenant from the credential. Reject any public `tenant_id`, `X-Tenant-ID`, or object URI that attempts tenant selection.
- Internal service tokens are short-lived, audience-bound, signed, and include tenant/model/deployment claims.

### Application protection

- Pydantic request validation, allowlisted event/model types, bounded arrays, maximum sequence lengths, and body-size limits.
- Rate limiting and concurrency limits at the API plus optional ingress limits.
- CORS disabled by default for server-to-server SDK use; enable only explicit admin UI origins.
- HTTPS assumed at ingress; local Compose may use HTTP only on the developer machine.
- Audit key creation, activation, rollback, quota changes, administrative reads, deletion, and security failures.
- Redact authorization headers, credentials, PII, and raw event metadata from logs.

### Database and object security

- RLS and least-privilege roles; runtime roles are not owners and do not have `BYPASSRLS`.
- Parameterized SQL/SQLAlchemy queries.
- Generated object paths, prefix checks, checksums, file-size caps, and allowlisted manifest schemas.
- Store only state dictionaries or `safetensors`; never dynamically import tenant code or load arbitrary pickle.
- Tenant deletion follows revoke -> stop serving -> tombstone -> erase/anonymize -> verify -> audit.

### Container and Kubernetes security

- Non-root UID, no privilege escalation, dropped Linux capabilities, seccomp runtime default.
- Read-only root filesystem where possible; writable `emptyDir` only for model download/temp files.
- Minimal images with pinned dependencies and vulnerability scanning.
- Kubernetes Secrets for infrastructure credentials; no secrets in ConfigMaps or image layers.
- Narrow controller RBAC and separate service accounts for API, workers, controller, and inference.
- Resource requests/limits and network policy where supported.

### Privacy considerations

Use pseudonymous external IDs, minimize event metadata, document retention, allow user erasure/anonymization, and avoid exporting raw behavior into metrics. This is a project architecture and not a claim of compliance with any specific law.

---

## 34. Testing strategy

### Test layers

- **Unit:** quota calculations, state transitions, model scoring, samplers, SDK retry logic, path validation.
- **Database:** constraints, indexes, migrations, append-only triggers if used, active-version uniqueness.
- **RLS:** two-tenant reads/writes/joins and no-context failures.
- **API integration:** auth, permissions, idempotency, request limits, error contract.
- **SDK:** sync/async clients, retries, backoff, batch splitting, typed errors.
- **Events:** duplicate `event_id`, batch replay, correction/tombstone behavior.
- **Queue:** routing, late ACK, retry, idempotent stage replay, poison message, DLQ, tenant mismatch.
- **Training:** snapshot cutoff, ordering, graph bounds, cancellation, checkpoint resume, reproducibility metadata.
- **Temporal leakage:** no edge, mapping, popularity count, or neighbor after prediction cutoff appears in training input.
- **Model evaluation:** known toy datasets produce expected retrieval Recall@K, Hit@10/NDCG@10, coverage/diversity, and stable Top-N overlap; invalid metrics block eligibility.
- **Funnel:** source quotas, deduplication, retrieval recall, eligibility fail-closed behavior, vectorized scoring, ordering category caps/diversity, deterministic tie-breaks, and last-known-good fallback.
- **Feature parity:** the same fixture produces equivalent offline and online feature tensors for the same schema version; incompatible schema prevents readiness.
- **Registry/artifact:** checksum, manifest, safe loading, corrupted file, wrong tenant/version.
- **Controller:** fake Kubernetes API tests for create/update/rollback, immutable template, HPA caps, RBAC denial.
- **Serving:** pinned identity, correct retrieval artifacts, filter disabled products before scoring, batch-score size limits, deterministic ordering, precomputed fallback, timeout, circuit breaker.
- **Quotas/load:** concurrent Redis scripts, monthly reconciliation, global caps.
- **Recovery:** dependency outages, worker crash, pod termination during requests, unschedulable scale-out.
- **End-to-end:** product -> event -> train -> register -> activate -> recommend -> feedback.

### Required Tenant A load test

Use Locust or k6 plus Prometheus assertions:

1. Start A and B at stable low load with one ready replica each.
2. Confirm A1/A-v1 and B1/B-v3 identity endpoints and checksums.
3. Increase only Tenant A to approximately 20 concurrent requests or a measured RPS that overloads one replica.
4. Verify A CPU/in-flight/queue/P95 crosses threshold.
5. Verify A HPA desired replicas changes 1 to 2.
6. Verify A2 starts, downloads A-v1, validates checksum, warms, and becomes ready.
7. Verify Tenant A Service endpoints contain A1 and A2; Tenant B still contains B1 only.
8. Verify A latency and queue recover.
9. Reduce A load and verify the configured cooldown/stabilization period.
10. Verify A returns to one ready replica without failed in-flight requests beyond the documented timeout policy.

### Isolation assertions

- A1 and A2 load only Model A; B1 loads only Model B.
- Tenant A cannot activate a B version, query B deployment, read B events, or read B recommendation history.
- A forged queue message with Tenant A envelope and Tenant B durable job is rejected and logged as a security event.
- A worker invocation without tenant context fails before any tenant table access.
- Service selectors cannot match pods from another tenant.

### Acceptance metrics

- Zero cross-tenant results across the automated suite.
- Duplicate event and usage submissions produce one durable effect.
- Corrupted/wrong-tenant artifacts never become ready.
- The load test produces the expected 1 -> 2 -> 1 Tenant A replica timeline while Tenant B remains at 1.
- A replay test proves that an item absent from the retrieval candidate set cannot be recovered by scoring, making Recall@K a release gate.
- Repeated identical requests against the same model/catalog/context produce stable ordering except where an explicitly versioned exploration rule is enabled.

---

## 35. Suggested repository structure

```text
graphrec/
  README.md
  pyproject.toml
  docker-compose.yml
  .env.example
  alembic.ini
  apps/
    api/
      main.py
      routes/
      dependencies.py
    worker/
      celery_app.py
      tasks/
    training_worker/
      tasks.py
    inference/
      main.py
      loader.py
      recommender.py
    deployment_controller/
      main.py
      reconciler.py
    scheduler_outbox/
      main.py
      publisher.py
      fair_dispatch.py
    demo_shop/
  graphrec_core/
    auth/
    tenancy/
    database/
      models/
      repositories/
      rls.py
    catalog/
    events/
    features/
      builder.py
      schema.py
      parity.py
    training/
      snapshots.py
      graph_builder.py
      samplers.py
      baselines.py
      dgsr_lite.py
      evaluation.py
      export_serving_bundle.py
      serialization.py
    retrieval/
      exact.py
      neighbors.py
      popular.py
      content.py
      merge.py
    filtering/
      eligibility.py
    ordering/
      policy.py
      diversity.py
    registry/
    deployment/
    inference/
    quotas/
    usage/
    observability/
    schemas/
  sdk/python/graphrec/
  migrations/versions/
  infrastructure/
    compose/
    k8s/
      base/
      monitoring/
      tenant-serving-template/
    prometheus/
    grafana/
  tests/
    unit/
    integration/
    rls/
    training/
    controller/
    load/
    e2e/
  scripts/
    seed_demo.py
    create_demo_tenants.py
    run_load_test.sh
    backup_demo.sh
    verify_artifact.py
  docs/
    architecture.md
    api.md
    threat-model.md
    demo-runbook.md
```

Use Alembic migrations, typed SQLAlchemy 2 models, Pydantic v2 schemas, Ruff/Black, mypy or Pyright, pytest, and pre-commit. Keep domain modules independent of FastAPI/Celery entrypoints so unit tests do not require infrastructure.

---

## 36. Twelve-week implementation plan

### Phase 1: tenancy and ingestion

| Week | Objective | Tasks | Deliverable | Acceptance criteria |
|---|---|---|---|---|
| 1 | Freeze scope and architecture | ADRs, diagrams, threat model, Compose skeleton, CI | Approved architecture baseline | Supervisor can trace every requirement to a component |
| 2 | Database and tenancy core | Alembic, tenant/catalog tables, app/migrator roles, RLS helper | PostgreSQL schema v1 | Tenant A cannot read/write Tenant B rows in tests |
| 3 | Authentication and catalog | Admin login, API keys/scopes, product CRUD/bulk upsert, audit | Working catalog API | Hashed credentials, tenant-derived context, idempotent product sync |
| 4 | SDK and events | Python SDK base, single/batch event APIs, RabbitMQ/Celery, deduplication | End-to-end event ingestion | Duplicate events have one effect; batch status works |

### Phase 2: training and registry

| Week | Objective | Tasks | Deliverable | Acceptance criteria |
|---|---|---|---|---|
| 5 | Dataset snapshots | Cutoff queries, RustFS paths, manifests, ordering/filtering | Reproducible tenant snapshot | Same cutoff/config gives verified data checksum behavior |
| 6 | Baseline recommenders | Popularity and BPR, temporal split, Hit/NDCG | Train/evaluate baselines | Metrics run on toy and demo datasets; no leakage tests pass |
| 7 | Graph and DGSR-lite | Edge-aware PyG graph, bounded sampler, embeddings, long/short fusion | Simplified DGSR training | Edge/time/order features affect messages; hard graph caps hold; CPU training completes |
| 8 | Serving bundle and registry | Job states, locks, checkpoints, feature schema, item embeddings/neighbors, candidate and ordering configs, safe artifact bundle | Tenant-specific model versions | Two tenants produce distinct complete serving bundles; feature parity and checksum tests pass |

### Phase 3: serving, scaling, and demonstration

| Week | Objective | Tasks | Deliverable | Acceptance criteria |
|---|---|---|---|---|
| 9 | Online inference funnel | Tenant-pinned inference image, retrieval merge, eligibility filter, vectorized DGSR scoring, deterministic ordering, sync gateway, fallback, feedback APIs | Real-time four-stage recommendations | Correct version returned; Recall@K measured; disabled products filtered before scoring; deterministic Top-N and timeouts handled |
| 10 | Deployment lifecycle | Controller, init container, readiness/warm-up, rolling activation/rollback | Automated per-tenant deployment | Failed new model leaves previous version serving |
| 11 | Autoscaling, quotas, monitoring | HPA, custom metric if feasible, dashboards, rate/concurrency limits, usage ledger | Tenant A scaling demo candidate | A scales 1 -> 2 while B remains 1; metrics show timeline |
| 12 | Hardening and presentation | Failure tests, security review, docs, backup, load test, final demo rehearsal | Final project release | Required diagrams/tests pass; demo runbook reproducible |

### Scope-control rule

If schedule slips, preserve in this order: tenancy/RLS, event idempotency, popularity baseline, model registry, tenant-pinned inference, activation/rollback, Tenant A scale demonstration. Reduce advanced DGSR attention, custom latency scaling, async SDK, and detailed billing before compromising isolation or correctness.

---

## 37. MVP versus future-production comparison

| Area | Semester MVP | Future production |
|---|---|---|
| Tenants | 2-4 active demo tenants | Many tenants with lifecycle automation |
| Serving | Dedicated deployment per active tenant with retrieval-filter-DGSR score-order funnel | Hybrid shared pool plus dedicated promotion, multi-stage learned ranking |
| Database | Single PostgreSQL in demo cluster, shared schema/RLS | Managed HA PostgreSQL, replicas, backups, tested DR |
| Object storage | Single RustFS | Managed regional/multi-region object storage |
| Broker/cache | RabbitMQ and Redis single instances | Managed/clustered services with capacity planning |
| Training | One CPU worker, scheduled/batch | Elastic CPU/GPU workers, richer orchestration |
| Model | Popularity/BPR baselines; simplified edge-aware DGSR; exact/precomputed multi-source retrieval; deterministic ordering | ANN service/index, richer inductive/content encoders, learned rankers/re-rankers, exploration, drift/fairness and online experiments |
| Autoscaling | HPA CPU as required path; optional one in-flight custom metric; min 1 | Predictive/multi-metric autoscaling, scale-to-zero for cold tenants |
| Deployment | Rolling update | Canary/blue-green with automated analysis |
| Events | REST batches | Streaming platform and online feature updates |
| Observability | Prometheus/Grafana and structured logs | Distributed tracing, centralized logs, SLO/error budgets |
| Billing | Mock plans and usage ledger | Payment provider, invoices, taxation, entitlement service |
| Security | Strong demo controls and RLS | Managed secrets/KMS, formal compliance, penetration testing |
| Availability | Best effort on three nodes | Multi-zone, multi-region, tested disaster recovery |

Do not implement future complexity inside the MVP unless a measured requirement forces it.

---

## 38. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| DGSR-lite is too complex or low quality | Model work delays platform | Popularity/BPR milestones first; bounded architecture; activation based on metrics |
| Model cold start is slow | Burst latency before scale-out | Keep one warm replica, init container, small artifacts, bounded queue, fallback |
| Three-node cluster lacks spare capacity | A2 remains pending | Reserve capacity, cap training, priority classes, realistic requests, scripted demo load |
| RLS context leaks through pooling | Cross-tenant exposure | Transaction-local setting, runtime role not owner, forced RLS, CI tests |
| Queue duplicates execute work twice | Corrupt states/usage | Durable idempotency keys, compare-and-set transitions, outbox, late ACK |
| Wrong model artifact loads | Severe isolation failure | Generated URI, per-tenant read-only credential, manifest tenant/version, checksum, immutable deployment template, startup abort |
| Redis counter drift | Incorrect quota | Durable usage ledger and scheduled reconciliation |
| RabbitMQ/DB dual-write gap | Lost task | Selected transactional outbox with publisher confirms and idempotent consumers |
| Training starves inference | Online degradation | Concurrency 1, strict limits, lower priority, admission pause, node preference |
| High-cardinality metrics overload Prometheus | Monitoring failure | Label whitelist; logs/DB for request/user/product detail |
| Too many detailed tables/endpoints | Semester scope expansion | Implement core columns first; keep optional fields in JSONB; prioritize demo path |
| Stateful component/node failure | Demo outage | Backups, restart runbook, clear non-HA statement, rehearse recovery |
| Competing replica controllers | Flapping and overwritten desired state | HPA is the sole normal replica writer; deployment controller only manages templates and HPA policy |
| Manual thresholds are wrong | Flapping or no scaling | Load-test and document measured thresholds; HPA stabilization |
| Artifact format vulnerability | Code execution | `safetensors` or controlled state dict, no tenant code/pickle, version allowlist |
| Retrieval misses relevant products | Ranker cannot recover them | Measure Recall@K independently, use multiple bounded sources, gate activation on retrieval recall |
| Training-serving feature skew | Offline gain becomes online loss | One shared FeatureBuilder, schema checksums, parity fixtures, readiness rejection |
| Stale eligibility/catalog state | Disabled or unavailable item returned | Versioned active-catalog cache, invalidation on product change, fail-closed filter and final check |
| Recommendation outputs oscillate | Inconsistent UX | Deterministic tie-breaks, churn/Jaccard metric, bounded boosts, manual activation review |

---

## 39. Final technology stack

| Layer | Selected technology |
|---|---|
| Language | Python 3.12 or a project-supported stable version |
| Public/admin API | FastAPI, Pydantic v2, Uvicorn |
| ORM/migrations | SQLAlchemy 2, Alembic |
| Database | PostgreSQL with shared schema and forced RLS |
| Broker/task framework | RabbitMQ + Celery |
| Cache/locks/rate limits | Redis |
| ML | PyTorch, PyTorch Geometric, NumPy/pandas or Polars as needed |
| Baselines | Popularity, implicit/BPR implementation |
| Artifact format | `safetensors` plus JSON/Parquet manifests; controlled PyTorch state dict fallback |
| Object storage | RustFS with S3-compatible client |
| Containers | Docker, Docker Compose |
| Orchestration | k3s, Kubernetes Deployments/Services/HPA |
| Controller | Python Kubernetes client, periodic reconciliation and leader lock |
| Durable dispatch | PostgreSQL transactional outbox plus standalone publisher |
| Metrics | Prometheus client, exporters, kube-state-metrics |
| Dashboards | Grafana |
| Testing | pytest, Testcontainers where practical, Locust or k6 |
| SDK | `httpx`, typed Pydantic/dataclass response models |
| CI quality | Ruff, Black, mypy/Pyright, dependency/image scanning |

Version pins should be recorded in lock files and artifact environment manifests. Before implementation, select versions that are mutually supported by PyTorch, PyG, Python, and the chosen base images.

---

## 40. Final architecture decision summary

1. **Multi-tenancy:** shared PostgreSQL schema with `tenant_id`, forced RLS, tenant identity derived from credentials, and no public tenant selector.
2. **Application shape:** modular FastAPI monolith with separate general worker, training worker, scheduler/outbox publisher, deployment-controller, and inference processes.
3. **Asynchronous work:** RabbitMQ with Celery for small control messages; PostgreSQL task records and a transactional outbox provide durable dispatch; Redis is reserved for cache, counters, semaphores, and locks.
4. **Modeling:** popularity and BPR baselines plus one CPU-friendly, edge-aware DGSR model using timestamped ordered user-item edges, bounded two-hop sampling, long/short preference fusion, and next-item link prediction. The same DGSR version exports retrieval embeddings and performs final batch scoring; no second learned ranker is required.
5. **Artifacts:** immutable tenant-prefixed RustFS bundles, per-tenant read-only inference credentials, checksum and manifest validation, `safetensors`/controlled state-dict loading, and PostgreSQL model registry.
6. **Serving:** dedicated Kubernetes Deployment and ClusterIP Service per active tenant. This is the concrete MVP choice.
7. **Deployment:** lightweight custom reconciler creates tenant resources; init container downloads and verifies the artifact; rolling update uses zero unavailable and one surge pod.
8. **Autoscaling:** one HPA per tenant Deployment and no competing scaler. CPU is the required MVP metric; one in-flight custom metric is optional. Keep one warm replica and enforce per-plan/global caps.
9. **Tenant A scenario:** when A's runtime load crosses threshold, HPA scales A from one to two replicas of exactly Model A v1. Readiness gates traffic. Tenant B stays at one Model B v3 replica. A later scales back after cooldown.
10. **Online recommendation funnel:** recommendations remain synchronous POST requests and execute candidate retrieval -> eligibility filtering -> batched DGSR scoring -> deterministic ordering. Multi-source retrieval, stage caps, strict timeouts, distributed admission control, active-catalog filtering, version-matched last-known-good lists, and popularity fallback keep the path bounded.
11. **Training isolation:** one active training job per tenant, global concurrency one, tenant snapshots, locks, idempotent stages, checkpoints, and strict resource limits.
12. **Observability and metering:** Prometheus/Grafana, bounded tenant labels, durable usage events, Redis fast counters, reconciliation, and mock Free/Basic/Pro plans.
13. **Deployment target:** Docker Compose for primary development and an optional three-node k3s demonstration. The cluster is educational and capacity-limited, not enterprise-grade HA.
14. **Implementation strategy:** deliver RLS and event correctness first, batch baselines second, DGSR-lite and the complete serving bundle third, then the four-stage online funnel, deployment, and scaling. This sequence follows the batch-first principle while still satisfying real-time inference.

The architecture is deliberately concrete, tenant-safe, and small enough to implement in a semester while still demonstrating model lifecycle, graph-based recommendation, queue processing, resource control, Kubernetes rollout, and independent tenant autoscaling.

The design basis is explicit: DGSR contributes the time/order-aware dynamic user-item graph and next-item link-prediction framing; Kubernetes HPA contributes one authoritative per-Deployment scaling loop and stabilization behavior; PostgreSQL RLS contributes `USING`/`WITH CHECK` enforcement under a transaction-local tenant context; RabbitMQ/Celery supplies acknowledged asynchronous delivery while PostgreSQL task records and the outbox supply durable orchestration truth.

### Technical reference anchors

- [DGSR paper — Dynamic Graph Neural Networks for Sequential Recommendation](https://arxiv.org/abs/2104.07368)
- [Kubernetes Horizontal Pod Autoscaling](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/)
- [Kubernetes autoscaling/v2 HPA API](https://kubernetes.io/docs/reference/kubernetes-api/autoscaling-horizontal-pod-autoscaler-v2/)
- [Celery brokers and backends](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/)
- [RabbitMQ consumer acknowledgements and publisher confirms](https://www.rabbitmq.com/docs/confirms)
- [RabbitMQ dead-letter exchanges](https://www.rabbitmq.com/docs/dlx)
- [PostgreSQL Row Security Policies](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [PyTorch serialization semantics and `weights_only`](https://docs.pytorch.org/docs/stable/notes/serialization.html)
- [RustFS identity and access management](https://docs.min.io/aistor/administration/iam/)
- [Aman.ai RecSys introduction and 2-stage/4-stage funnel](https://aman.ai/recsys/intro/)
- [Aman.ai candidate generation and serving optimizations](https://aman.ai/recsys/candidate-gen/)
- [Aman.ai ranking/scoring](https://aman.ai/recsys/ranking/)
- [Aman.ai re-ranking](https://aman.ai/recsys/re-ranking/)
- [Aman.ai GNNs for recommendation](https://aman.ai/recsys/gnn/)
- [Aman.ai recommender-system challenges](https://aman.ai/recsys/challenges/)
- [Aman.ai cold-start strategies](https://aman.ai/recsys/cold-start/)
