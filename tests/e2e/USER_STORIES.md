# End-to-end user stories — every SRS role on the Beauty dataset

These stories follow `GraphRec_Complete_SRS.md` §2.1 (stakeholders), §2.2 (actors),
§2.7 (project user story) and the requirement ids in §2.3–2.6. Each clause is
executed, in this order, by `tests/e2e/beauty_e2e.py` against a live stack, and
the storefront stories are then verified by hand in the browser. Requirement ids
in brackets are what the clause demonstrates.

The data is the Amazon Beauty interaction log (`dgsr_notebooks/Beauty.csv`:
52,204 shoppers, 57,289 items, 394,908 interactions) and the model is the DGSR
checkpoint the notebook trained on it (`dgsr_beauty_t4_v2/best.pt`, validation
NDCG@10 0.338, Hit@10 0.496 on 47,404 held-out examples).

## Roles and accounts created by the run

| SRS role | Account | How it authenticates |
|---|---|---|
| Tenant Business Owner | registers the tenant *Beauty Shop* and becomes its first administrator | one-time setup token → password |
| Tenant Administrator | `owner-<run>@beauty.example` (`tenant_administrator`) | email + password (bearer token, all tenant scopes incl. `users:write`) |
| Tenant Developer | `dev-<run>@beauty.example` (`tenant_developer`), invited by the administrator | invitation setup token → password (bearer token, catalog / events / keys / training:read) |
| Tenant E-Commerce Application | the storefront API key the developer creates | `ApiKey gr_live_…` with `catalog:*`, `events:*`, `recommendations:read` |
| Platform Administrator | the operator holding `PLATFORM_ADMIN_TOKEN` | shared platform token (never a tenant credential) |
| E-Commerce Customer | Beauty shoppers `0`, `40`, `112` (personas Lina, Noah, Maya) and an anonymous visitor | indirect — through the storefront, never a GraphRec actor |

A second tenant (*Other Shop*) is registered only to prove isolation.

## 1. Tenant Business Owner

*As a business owner I join GraphRec so my store gets recommendations.*

1. I register a tenant with my email and receive an active tenant plus a one-time setup token. [NR-F-01]
2. I set my password with the token; a second use of the same token is refused. [NR-F-01, security]
3. Another business registering later sees none of my products, cannot read one by id, cannot activate my model and never receives recommendations from it. [NR-NF-01, ER-NF-02, BRULE-02, BRULE-07]

## 2. Tenant Administrator

*As the tenant administrator I configure users, train and operate the model, and watch usage.*

1. Signing in gives me the `tenant_administrator` role; a wrong password is rejected. [NR-F-02]
2. I invite a developer and receive their one-time setup token; inviting the same address twice is a conflict; the user list shows both of us. [NR-F-02, SRS 2.7]
3. I create an explicit dataset snapshot from this tenant's events only. [ER-F-01, BRULE-12]
4. Requesting a training job that imports an artifact which does not exist is a clear 404. [NR-NF-03]
5. I request training with the DGSR checkpoint; the job succeeds and yields a model version. [NR-F-07, NR-F-08]
6. The version shows its offline quality (Hit@k, NDCG@k), the checkpoint's SHA-256 and how completely it covers my catalog and shoppers; it starts as *eligible*. [NR-F-09, ER-F-02, ER-F-03, ER-NF-03]
7. I activate it; exactly one version is active and the service status names that version and when it took over. [NR-F-10, NR-F-16, BRULE-08]
8. I import a second version and activate it; the first becomes *retired* and serving follows the new one. [NR-F-10, ER-F-06]
9. I roll back to the first version; serving follows again. Rolling back to an unknown id is rejected. [NR-F-11, ER-F-07, XR-F-05]
10. I cannot archive the active version; I can archive the retired one. [NR-F-11]
11. Training history lists the failed and the succeeded jobs with their reasons. [NR-F-08, ER-NF-04]
12. Usage shows the accepted events, training jobs and the recommendation requests just served; the plan and limits are visible; the metrics summary reports what those requests measured. [NR-F-15, ER-F-08, ER-F-12]

## 3. Tenant Developer

*As the developer I connect the store and load its data.*

1. I set my password with the invitation token and sign in as `tenant_developer` with limited scopes (no `training:write`). [NR-F-02]
2. I cannot invite users and cannot request training. [NR-F-02]
3. I create the storefront credential with the storefront scopes; I cannot delegate a training scope; I rotate the credential with a grace period and see its status. [NR-F-03, ER-F-11]
4. I upload the Beauty interaction log (`user_id,item_id,time`, 8.5 MB): 57,289 items become products, 394,908 interactions become `purchase` events, and a snapshot with those counts is produced. [NR-F-05, NR-F-06, ER-F-01]
5. Uploading the same log again records no new events or products. [NR-NF-05, ER-F-04]
6. Submission status is visible per batch. [NR-F-06]

## 4. Tenant E-Commerce Application

*As the store's backend I keep the catalog current, report behaviour and show recommendations.*

1. Products are paginated with a total; specific products can be fetched by id; a product can be updated and disabled; an unknown product is a clear 404. [NR-F-04, NR-NF-03]
2. I submit events one at a time and in batches; a repeated event id is reported as a duplicate, not stored twice. [NR-F-06, ER-F-04, NR-NF-05]
3. My credential cannot start training or read the model registry. [NR-F-02, BRULE-01]
4. A known shopper (user `0`) is served `personalized` by the active DGSR version, and the ranking is the one the training notebook computed for that user. [NR-F-12, ER-F-05, ER-NF-06]
5. Disabled and out-of-stock products are never recommended; items the shopper already bought are not recommended again; explicit exclusions are honoured. [BRULE-09, XR-F-04]
6. Identical requests give identical ordering. [ER-NF-06]
7. Shoppers with different histories (Lina `0`, Noah `40`, Maya `112`) receive different rankings. [NR-F-12]
8. An anonymous session with recent items receives model-based `session` recommendations; a session with nothing known, or an unknown shopper, receives an explicit tenant-safe fallback. [NR-F-13, XR-F-01, XR-F-09, ER-F-10]
9. New live events (view, add to cart, purchase) are folded into a known shopper's history at the next request. [XR-F-01]
10. P95 end-to-end latency over 40 requests is below 300 ms. [NR-NF-04]
11. I report impression, click and conversion feedback for a served request. [NR-F-14]

## 5. Platform Administrator

*As the operator I keep tenants safe and the platform observable.*

1. Platform status is reported; the new tenant appears in the tenant list; pricing plans with limits are visible. [ER-F-12, XR-F-06]
2. I store a quota override for the tenant (2,000,000 accepted events). [ER-F-09, BRULE-10]
3. I suspend the tenant; its storefront credential is refused. I restore it; it serves again. [ER-NF-07, platform stakeholder]
4. Administrative actions are in the audit log; the failure list is available. [ER-F-11, ER-NF-09]
5. The platform token is not a tenant credential. [NR-NF-02, BRULE-01]

## 6. E-Commerce Customer (through the Facet storefront)

Verified in the browser after `tests/e2e/beauty_e2e.py --write-storefront-env`
hands the tenant over to `apps/demo-storefront`:

1. The shop lists the tenant's catalog (first page of 57,289 items) and a live "Recommended" shelf whose footer names the model version and proof status.
2. Switching persona (Lina / Noah / Maya / New visitor) changes the shelf; the compare lab shows three distinct rankings for the three shoppers and the fallback for the visitor.
3. Opening a product records a view; "goes with" excludes the product itself.
4. Adding to the cart and checking out records the purchase; retrying the order returns the same order id with `duplicateCount`.
5. `scripts/verify_personalization.py` passes for the imported version, so the operator may set `MODEL_PROOF_VERIFIED=true` for that exact version and the shelf label becomes *model verified*.

## What the run proves and what it does not

- Serving is the real DGSR forward pass (Algorithm 1 over the saved graph, Eq. 17–18);
  user `0`'s API ranking equals `recommendations_user_0.csv` from the notebook.
- Training on this backend is an **artifact import**: the checkpoint was trained on
  Kaggle (Tesla T4, 12 epochs). In-platform training of a tenant's own snapshot is
  still to be built; the import verifies engine, config, data fingerprint and
  vocabulary before a version is registered.
- Plan quotas are recorded and overridable but not yet enforced on event or
  recommendation submission (ER-F-09 is partial); feedback is acknowledged but not
  stored (BRULE-11 is partial). Both are listed in `Claude outputs/ANALYSIS.md`.
