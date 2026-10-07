# GraphRec console: UI/UX audit and redesign

*Audited Oct 3, 2026 · frontend `web` · data: the live `beauty` tenant (real API responses captured from the signed-in console, read-only)*

## How this audit was made

- **Source:** the current working tree of `web/src`. The app on `:5180` is served by the Docker nginx image and only picks up source changes after a rebuild, so each build was rendered locally and served the real tenant's API responses (fixture: `docs/ui-audit/fixture.mjs`).
- **Configurations:** every page in four of them: desktop 1440 px and mobile 390 px, each in light and dark. Full-page screenshots.
- **Extra states:** the mobile navigation drawer, plus empty states (no products, no models, nothing deployed), error states (API returns 503) and loading states (API never answers).
- **Screenshots:** `docs/ui-audit/docs/ui-audit/before/<page>--<config>.png` and `docs/ui-audit/after/<page>--<config>.png`. The `<config>` values are `desktop-light`, `desktop-dark`, `mobile-light`, `mobile-dark` and `mobile-nav`.
- **Item IDs:** each issue has an ID (for example `PR-3`). The **Verification** section at the end marks every ID as Fixed, Partially fixed or Deferred.

### What the live data looks like (this drives many findings)

| Fact | Value |
|---|---|
| Plan | Free; product limit 5,000 |
| Stored products | **57,289** (52,289 over the limit). All have the title "Item N", no category, price 0.00, and metadata `{source: interaction_log}` |
| Interaction events | 394,908 loaded on Sep 12 (dataset upload); **0** accepted in the current usage period (Oct 1 – Nov 1) |
| Recommendation requests | 0 in every window |
| Model versions | 3, all imported from the **same** pretrained checkpoint `dgsr_beauty_t4_v2`, so every quality metric is identical. The **oldest** (v1, `…d41640`) is active after a rollback; the newest (v3) is Retired; v2 is Archived |
| Training runs | 3 `pretrained_import` jobs. Each reports `progress: 0` and `stage: completed` |
| Snapshots | 3. Product count is 57,288 vs 57,289, and none is linked to a training run, although all three jobs reference `2c2825a1…` |
| Billing periods | Two disagree: the subscription period is Sep 12 – Oct 12, while usage resets Nov 1 |


## Screenshot index

| Page | Before | After |
|---|---|---|
| account | [desktop-dark](docs/ui-audit/before/account--desktop-dark.png) · [desktop-light](docs/ui-audit/before/account--desktop-light.png) · [mobile-dark](docs/ui-audit/before/account--mobile-dark.png) · [mobile-light](docs/ui-audit/before/account--mobile-light.png) · [mobile-nav](docs/ui-audit/before/account--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/account--desktop-dark.png) · [desktop-light](docs/ui-audit/after/account--desktop-light.png) · [mobile-dark](docs/ui-audit/after/account--mobile-dark.png) · [mobile-light](docs/ui-audit/after/account--mobile-light.png) · [mobile-nav](docs/ui-audit/after/account--mobile-nav.png) |
| admin-audit | [desktop-dark](docs/ui-audit/before/admin-audit--desktop-dark.png) · [desktop-light](docs/ui-audit/before/admin-audit--desktop-light.png) · [mobile-dark](docs/ui-audit/before/admin-audit--mobile-dark.png) · [mobile-light](docs/ui-audit/before/admin-audit--mobile-light.png) · [mobile-nav](docs/ui-audit/before/admin-audit--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/admin-audit--desktop-dark.png) · [desktop-light](docs/ui-audit/after/admin-audit--desktop-light.png) · [mobile-dark](docs/ui-audit/after/admin-audit--mobile-dark.png) · [mobile-light](docs/ui-audit/after/admin-audit--mobile-light.png) · [mobile-nav](docs/ui-audit/after/admin-audit--mobile-nav.png) |
| admin-login | [desktop-dark](docs/ui-audit/before/admin-login--desktop-dark.png) · [desktop-light](docs/ui-audit/before/admin-login--desktop-light.png) · [mobile-dark](docs/ui-audit/before/admin-login--mobile-dark.png) · [mobile-light](docs/ui-audit/before/admin-login--mobile-light.png) | [desktop-dark](docs/ui-audit/after/admin-login--desktop-dark.png) · [desktop-light](docs/ui-audit/after/admin-login--desktop-light.png) · [mobile-dark](docs/ui-audit/after/admin-login--mobile-dark.png) · [mobile-light](docs/ui-audit/after/admin-login--mobile-light.png) |
| admin-plans | [desktop-dark](docs/ui-audit/before/admin-plans--desktop-dark.png) · [desktop-light](docs/ui-audit/before/admin-plans--desktop-light.png) · [mobile-dark](docs/ui-audit/before/admin-plans--mobile-dark.png) · [mobile-light](docs/ui-audit/before/admin-plans--mobile-light.png) · [mobile-nav](docs/ui-audit/before/admin-plans--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/admin-plans--desktop-dark.png) · [desktop-light](docs/ui-audit/after/admin-plans--desktop-light.png) · [mobile-dark](docs/ui-audit/after/admin-plans--mobile-dark.png) · [mobile-light](docs/ui-audit/after/admin-plans--mobile-light.png) · [mobile-nav](docs/ui-audit/after/admin-plans--mobile-nav.png) |
| admin-status | [desktop-dark](docs/ui-audit/before/admin-status--desktop-dark.png) · [desktop-light](docs/ui-audit/before/admin-status--desktop-light.png) · [mobile-dark](docs/ui-audit/before/admin-status--mobile-dark.png) · [mobile-light](docs/ui-audit/before/admin-status--mobile-light.png) · [mobile-nav](docs/ui-audit/before/admin-status--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/admin-status--desktop-dark.png) · [desktop-light](docs/ui-audit/after/admin-status--desktop-light.png) · [mobile-dark](docs/ui-audit/after/admin-status--mobile-dark.png) · [mobile-light](docs/ui-audit/after/admin-status--mobile-light.png) · [mobile-nav](docs/ui-audit/after/admin-status--mobile-nav.png) |
| admin-tenant | [desktop-dark](docs/ui-audit/before/admin-tenant--desktop-dark.png) · [desktop-light](docs/ui-audit/before/admin-tenant--desktop-light.png) · [mobile-dark](docs/ui-audit/before/admin-tenant--mobile-dark.png) · [mobile-light](docs/ui-audit/before/admin-tenant--mobile-light.png) · [mobile-nav](docs/ui-audit/before/admin-tenant--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/admin-tenant--desktop-dark.png) · [desktop-light](docs/ui-audit/after/admin-tenant--desktop-light.png) · [mobile-dark](docs/ui-audit/after/admin-tenant--mobile-dark.png) · [mobile-light](docs/ui-audit/after/admin-tenant--mobile-light.png) · [mobile-nav](docs/ui-audit/after/admin-tenant--mobile-nav.png) |
| admin-tenants | [desktop-dark](docs/ui-audit/before/admin-tenants--desktop-dark.png) · [desktop-light](docs/ui-audit/before/admin-tenants--desktop-light.png) · [mobile-dark](docs/ui-audit/before/admin-tenants--mobile-dark.png) · [mobile-light](docs/ui-audit/before/admin-tenants--mobile-light.png) · [mobile-nav](docs/ui-audit/before/admin-tenants--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/admin-tenants--desktop-dark.png) · [desktop-light](docs/ui-audit/after/admin-tenants--desktop-light.png) · [mobile-dark](docs/ui-audit/after/admin-tenants--mobile-dark.png) · [mobile-light](docs/ui-audit/after/admin-tenants--mobile-light.png) · [mobile-nav](docs/ui-audit/after/admin-tenants--mobile-nav.png) |
| credentials | [desktop-dark](docs/ui-audit/before/credentials--desktop-dark.png) · [desktop-light](docs/ui-audit/before/credentials--desktop-light.png) · [mobile-dark](docs/ui-audit/before/credentials--mobile-dark.png) · [mobile-light](docs/ui-audit/before/credentials--mobile-light.png) · [mobile-nav](docs/ui-audit/before/credentials--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/credentials--desktop-dark.png) · [desktop-light](docs/ui-audit/after/credentials--desktop-light.png) · [mobile-dark](docs/ui-audit/after/credentials--mobile-dark.png) · [mobile-light](docs/ui-audit/after/credentials--mobile-light.png) · [mobile-nav](docs/ui-audit/after/credentials--mobile-nav.png) |
| datasets | [desktop-dark](docs/ui-audit/before/datasets--desktop-dark.png) · [desktop-light](docs/ui-audit/before/datasets--desktop-light.png) · [mobile-dark](docs/ui-audit/before/datasets--mobile-dark.png) · [mobile-light](docs/ui-audit/before/datasets--mobile-light.png) · [mobile-nav](docs/ui-audit/before/datasets--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/datasets--desktop-dark.png) · [desktop-light](docs/ui-audit/after/datasets--desktop-light.png) · [mobile-dark](docs/ui-audit/after/datasets--mobile-dark.png) · [mobile-light](docs/ui-audit/after/datasets--mobile-light.png) · [mobile-nav](docs/ui-audit/after/datasets--mobile-nav.png) |
| events | [desktop-dark](docs/ui-audit/before/events--desktop-dark.png) · [desktop-light](docs/ui-audit/before/events--desktop-light.png) · [mobile-dark](docs/ui-audit/before/events--mobile-dark.png) · [mobile-light](docs/ui-audit/before/events--mobile-light.png) · [mobile-nav](docs/ui-audit/before/events--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/events--desktop-dark.png) · [desktop-light](docs/ui-audit/after/events--desktop-light.png) · [mobile-dark](docs/ui-audit/after/events--mobile-dark.png) · [mobile-light](docs/ui-audit/after/events--mobile-light.png) · [mobile-nav](docs/ui-audit/after/events--mobile-nav.png) |
| integration | [desktop-dark](docs/ui-audit/before/integration--desktop-dark.png) · [desktop-light](docs/ui-audit/before/integration--desktop-light.png) · [mobile-dark](docs/ui-audit/before/integration--mobile-dark.png) · [mobile-light](docs/ui-audit/before/integration--mobile-light.png) · [mobile-nav](docs/ui-audit/before/integration--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/integration--desktop-dark.png) · [desktop-light](docs/ui-audit/after/integration--desktop-light.png) · [mobile-dark](docs/ui-audit/after/integration--mobile-dark.png) · [mobile-light](docs/ui-audit/after/integration--mobile-light.png) · [mobile-nav](docs/ui-audit/after/integration--mobile-nav.png) |
| login | [desktop-dark](docs/ui-audit/before/login--desktop-dark.png) · [desktop-light](docs/ui-audit/before/login--desktop-light.png) · [mobile-dark](docs/ui-audit/before/login--mobile-dark.png) · [mobile-light](docs/ui-audit/before/login--mobile-light.png) | [desktop-dark](docs/ui-audit/after/login--desktop-dark.png) · [desktop-light](docs/ui-audit/after/login--desktop-light.png) · [mobile-dark](docs/ui-audit/after/login--mobile-dark.png) · [mobile-light](docs/ui-audit/after/login--mobile-light.png) |
| model-detail | [desktop-dark](docs/ui-audit/before/model-detail--desktop-dark.png) · [desktop-light](docs/ui-audit/before/model-detail--desktop-light.png) · [mobile-dark](docs/ui-audit/before/model-detail--mobile-dark.png) · [mobile-light](docs/ui-audit/before/model-detail--mobile-light.png) · [mobile-nav](docs/ui-audit/before/model-detail--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/model-detail--desktop-dark.png) · [desktop-light](docs/ui-audit/after/model-detail--desktop-light.png) · [mobile-dark](docs/ui-audit/after/model-detail--mobile-dark.png) · [mobile-light](docs/ui-audit/after/model-detail--mobile-light.png) · [mobile-nav](docs/ui-audit/after/model-detail--mobile-nav.png) |
| models | [desktop-dark](docs/ui-audit/before/models--desktop-dark.png) · [desktop-light](docs/ui-audit/before/models--desktop-light.png) · [mobile-dark](docs/ui-audit/before/models--mobile-dark.png) · [mobile-light](docs/ui-audit/before/models--mobile-light.png) · [mobile-nav](docs/ui-audit/before/models--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/models--desktop-dark.png) · [desktop-light](docs/ui-audit/after/models--desktop-light.png) · [mobile-dark](docs/ui-audit/after/models--mobile-dark.png) · [mobile-light](docs/ui-audit/after/models--mobile-light.png) · [mobile-nav](docs/ui-audit/after/models--mobile-nav.png) |
| models-empty | [desktop-light](docs/ui-audit/before/models-empty--desktop-light.png) · [mobile-light](docs/ui-audit/before/models-empty--mobile-light.png) · [mobile-nav](docs/ui-audit/before/models-empty--mobile-nav.png) | [desktop-light](docs/ui-audit/after/models-empty--desktop-light.png) · [mobile-light](docs/ui-audit/after/models-empty--mobile-light.png) · [mobile-nav](docs/ui-audit/after/models-empty--mobile-nav.png) |
| not-found | [desktop-dark](docs/ui-audit/before/not-found--desktop-dark.png) · [desktop-light](docs/ui-audit/before/not-found--desktop-light.png) · [mobile-dark](docs/ui-audit/before/not-found--mobile-dark.png) · [mobile-light](docs/ui-audit/before/not-found--mobile-light.png) · [mobile-nav](docs/ui-audit/before/not-found--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/not-found--desktop-dark.png) · [desktop-light](docs/ui-audit/after/not-found--desktop-light.png) · [mobile-dark](docs/ui-audit/after/not-found--mobile-dark.png) · [mobile-light](docs/ui-audit/after/not-found--mobile-light.png) · [mobile-nav](docs/ui-audit/after/not-found--mobile-nav.png) |
| overview | [desktop-dark](docs/ui-audit/before/overview--desktop-dark.png) · [desktop-light](docs/ui-audit/before/overview--desktop-light.png) · [mobile-dark](docs/ui-audit/before/overview--mobile-dark.png) · [mobile-light](docs/ui-audit/before/overview--mobile-light.png) · [mobile-nav](docs/ui-audit/before/overview--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/overview--desktop-dark.png) · [desktop-light](docs/ui-audit/after/overview--desktop-light.png) · [mobile-dark](docs/ui-audit/after/overview--mobile-dark.png) · [mobile-light](docs/ui-audit/after/overview--mobile-light.png) · [mobile-nav](docs/ui-audit/after/overview--mobile-nav.png) |
| overview-empty | [desktop-light](docs/ui-audit/before/overview-empty--desktop-light.png) · [mobile-light](docs/ui-audit/before/overview-empty--mobile-light.png) · [mobile-nav](docs/ui-audit/before/overview-empty--mobile-nav.png) | [desktop-light](docs/ui-audit/after/overview-empty--desktop-light.png) · [mobile-light](docs/ui-audit/after/overview-empty--mobile-light.png) · [mobile-nav](docs/ui-audit/after/overview-empty--mobile-nav.png) |
| overview-error | [desktop-light](docs/ui-audit/before/overview-error--desktop-light.png) · [mobile-light](docs/ui-audit/before/overview-error--mobile-light.png) · [mobile-nav](docs/ui-audit/before/overview-error--mobile-nav.png) | [desktop-light](docs/ui-audit/after/overview-error--desktop-light.png) · [mobile-light](docs/ui-audit/after/overview-error--mobile-light.png) · [mobile-nav](docs/ui-audit/after/overview-error--mobile-nav.png) |
| overview-loading | [desktop-light](docs/ui-audit/before/overview-loading--desktop-light.png) · [mobile-light](docs/ui-audit/before/overview-loading--mobile-light.png) · [mobile-nav](docs/ui-audit/before/overview-loading--mobile-nav.png) | [desktop-light](docs/ui-audit/after/overview-loading--desktop-light.png) · [mobile-light](docs/ui-audit/after/overview-loading--mobile-light.png) · [mobile-nav](docs/ui-audit/after/overview-loading--mobile-nav.png) |
| product-detail | [desktop-dark](docs/ui-audit/before/product-detail--desktop-dark.png) · [desktop-light](docs/ui-audit/before/product-detail--desktop-light.png) · [mobile-dark](docs/ui-audit/before/product-detail--mobile-dark.png) · [mobile-light](docs/ui-audit/before/product-detail--mobile-light.png) · [mobile-nav](docs/ui-audit/before/product-detail--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/product-detail--desktop-dark.png) · [desktop-light](docs/ui-audit/after/product-detail--desktop-light.png) · [mobile-dark](docs/ui-audit/after/product-detail--mobile-dark.png) · [mobile-light](docs/ui-audit/after/product-detail--mobile-light.png) · [mobile-nav](docs/ui-audit/after/product-detail--mobile-nav.png) |
| product-new | [desktop-dark](docs/ui-audit/before/product-new--desktop-dark.png) · [desktop-light](docs/ui-audit/before/product-new--desktop-light.png) · [mobile-dark](docs/ui-audit/before/product-new--mobile-dark.png) · [mobile-light](docs/ui-audit/before/product-new--mobile-light.png) · [mobile-nav](docs/ui-audit/before/product-new--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/product-new--desktop-dark.png) · [desktop-light](docs/ui-audit/after/product-new--desktop-light.png) · [mobile-dark](docs/ui-audit/after/product-new--mobile-dark.png) · [mobile-light](docs/ui-audit/after/product-new--mobile-light.png) · [mobile-nav](docs/ui-audit/after/product-new--mobile-nav.png) |
| products | [desktop-dark](docs/ui-audit/before/products--desktop-dark.png) · [desktop-light](docs/ui-audit/before/products--desktop-light.png) · [mobile-dark](docs/ui-audit/before/products--mobile-dark.png) · [mobile-light](docs/ui-audit/before/products--mobile-light.png) · [mobile-nav](docs/ui-audit/before/products--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/products--desktop-dark.png) · [desktop-light](docs/ui-audit/after/products--desktop-light.png) · [mobile-dark](docs/ui-audit/after/products--mobile-dark.png) · [mobile-light](docs/ui-audit/after/products--mobile-light.png) · [mobile-nav](docs/ui-audit/after/products--mobile-nav.png) |
| products-empty | [desktop-light](docs/ui-audit/before/products-empty--desktop-light.png) · [mobile-light](docs/ui-audit/before/products-empty--mobile-light.png) · [mobile-nav](docs/ui-audit/before/products-empty--mobile-nav.png) | [desktop-light](docs/ui-audit/after/products-empty--desktop-light.png) · [mobile-light](docs/ui-audit/after/products-empty--mobile-light.png) · [mobile-nav](docs/ui-audit/after/products-empty--mobile-nav.png) |
| products-error | [desktop-light](docs/ui-audit/before/products-error--desktop-light.png) · [mobile-light](docs/ui-audit/before/products-error--mobile-light.png) · [mobile-nav](docs/ui-audit/before/products-error--mobile-nav.png) | [desktop-light](docs/ui-audit/after/products-error--desktop-light.png) · [mobile-light](docs/ui-audit/after/products-error--mobile-light.png) · [mobile-nav](docs/ui-audit/after/products-error--mobile-nav.png) |
| recover | [desktop-dark](docs/ui-audit/before/recover--desktop-dark.png) · [desktop-light](docs/ui-audit/before/recover--desktop-light.png) · [mobile-dark](docs/ui-audit/before/recover--mobile-dark.png) · [mobile-light](docs/ui-audit/before/recover--mobile-light.png) | [desktop-dark](docs/ui-audit/after/recover--desktop-dark.png) · [desktop-light](docs/ui-audit/after/recover--desktop-light.png) · [mobile-dark](docs/ui-audit/after/recover--mobile-dark.png) · [mobile-light](docs/ui-audit/after/recover--mobile-light.png) |
| register | [desktop-dark](docs/ui-audit/before/register--desktop-dark.png) · [desktop-light](docs/ui-audit/before/register--desktop-light.png) · [mobile-dark](docs/ui-audit/before/register--mobile-dark.png) · [mobile-light](docs/ui-audit/before/register--mobile-light.png) | [desktop-dark](docs/ui-audit/after/register--desktop-dark.png) · [desktop-light](docs/ui-audit/after/register--desktop-light.png) · [mobile-dark](docs/ui-audit/after/register--mobile-dark.png) · [mobile-light](docs/ui-audit/after/register--mobile-light.png) |
| rules | [desktop-dark](docs/ui-audit/before/rules--desktop-dark.png) · [desktop-light](docs/ui-audit/before/rules--desktop-light.png) · [mobile-dark](docs/ui-audit/before/rules--mobile-dark.png) · [mobile-light](docs/ui-audit/before/rules--mobile-light.png) · [mobile-nav](docs/ui-audit/before/rules--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/rules--desktop-dark.png) · [desktop-light](docs/ui-audit/after/rules--desktop-light.png) · [mobile-dark](docs/ui-audit/after/rules--mobile-dark.png) · [mobile-light](docs/ui-audit/after/rules--mobile-light.png) · [mobile-nav](docs/ui-audit/after/rules--mobile-nav.png) |
| service-status | [desktop-dark](docs/ui-audit/before/service-status--desktop-dark.png) · [desktop-light](docs/ui-audit/before/service-status--desktop-light.png) · [mobile-dark](docs/ui-audit/before/service-status--mobile-dark.png) · [mobile-light](docs/ui-audit/before/service-status--mobile-light.png) · [mobile-nav](docs/ui-audit/before/service-status--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/service-status--desktop-dark.png) · [desktop-light](docs/ui-audit/after/service-status--desktop-light.png) · [mobile-dark](docs/ui-audit/after/service-status--mobile-dark.png) · [mobile-light](docs/ui-audit/after/service-status--mobile-light.png) · [mobile-nav](docs/ui-audit/after/service-status--mobile-nav.png) |
| setup | [desktop-dark](docs/ui-audit/before/setup--desktop-dark.png) · [desktop-light](docs/ui-audit/before/setup--desktop-light.png) · [mobile-dark](docs/ui-audit/before/setup--mobile-dark.png) · [mobile-light](docs/ui-audit/before/setup--mobile-light.png) | [desktop-dark](docs/ui-audit/after/setup--desktop-dark.png) · [desktop-light](docs/ui-audit/after/setup--desktop-light.png) · [mobile-dark](docs/ui-audit/after/setup--mobile-dark.png) · [mobile-light](docs/ui-audit/after/setup--mobile-light.png) |
| submission | [desktop-dark](docs/ui-audit/before/submission--desktop-dark.png) · [desktop-light](docs/ui-audit/before/submission--desktop-light.png) · [mobile-dark](docs/ui-audit/before/submission--mobile-dark.png) · [mobile-light](docs/ui-audit/before/submission--mobile-light.png) · [mobile-nav](docs/ui-audit/before/submission--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/submission--desktop-dark.png) · [desktop-light](docs/ui-audit/after/submission--desktop-light.png) · [mobile-dark](docs/ui-audit/after/submission--mobile-dark.png) · [mobile-light](docs/ui-audit/after/submission--mobile-light.png) · [mobile-nav](docs/ui-audit/after/submission--mobile-nav.png) |
| sync | [desktop-dark](docs/ui-audit/before/sync--desktop-dark.png) · [desktop-light](docs/ui-audit/before/sync--desktop-light.png) · [mobile-dark](docs/ui-audit/before/sync--mobile-dark.png) · [mobile-light](docs/ui-audit/before/sync--mobile-light.png) · [mobile-nav](docs/ui-audit/before/sync--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/sync--desktop-dark.png) · [desktop-light](docs/ui-audit/after/sync--desktop-light.png) · [mobile-dark](docs/ui-audit/after/sync--mobile-dark.png) · [mobile-light](docs/ui-audit/after/sync--mobile-light.png) · [mobile-nav](docs/ui-audit/after/sync--mobile-nav.png) |
| training | [desktop-dark](docs/ui-audit/before/training--desktop-dark.png) · [desktop-light](docs/ui-audit/before/training--desktop-light.png) · [mobile-dark](docs/ui-audit/before/training--mobile-dark.png) · [mobile-light](docs/ui-audit/before/training--mobile-light.png) · [mobile-nav](docs/ui-audit/before/training--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/training--desktop-dark.png) · [desktop-light](docs/ui-audit/after/training--desktop-light.png) · [mobile-dark](docs/ui-audit/after/training--mobile-dark.png) · [mobile-light](docs/ui-audit/after/training--mobile-light.png) · [mobile-nav](docs/ui-audit/after/training--mobile-nav.png) |
| training-run | [desktop-dark](docs/ui-audit/before/training-run--desktop-dark.png) · [desktop-light](docs/ui-audit/before/training-run--desktop-light.png) · [mobile-dark](docs/ui-audit/before/training-run--mobile-dark.png) · [mobile-light](docs/ui-audit/before/training-run--mobile-light.png) · [mobile-nav](docs/ui-audit/before/training-run--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/training-run--desktop-dark.png) · [desktop-light](docs/ui-audit/after/training-run--desktop-light.png) · [mobile-dark](docs/ui-audit/after/training-run--mobile-dark.png) · [mobile-light](docs/ui-audit/after/training-run--mobile-light.png) · [mobile-nav](docs/ui-audit/after/training-run--mobile-nav.png) |
| usage | [desktop-dark](docs/ui-audit/before/usage--desktop-dark.png) · [desktop-light](docs/ui-audit/before/usage--desktop-light.png) · [mobile-dark](docs/ui-audit/before/usage--mobile-dark.png) · [mobile-light](docs/ui-audit/before/usage--mobile-light.png) · [mobile-nav](docs/ui-audit/before/usage--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/usage--desktop-dark.png) · [desktop-light](docs/ui-audit/after/usage--desktop-light.png) · [mobile-dark](docs/ui-audit/after/usage--mobile-dark.png) · [mobile-light](docs/ui-audit/after/usage--mobile-light.png) · [mobile-nav](docs/ui-audit/after/usage--mobile-nav.png) |
| users | [desktop-dark](docs/ui-audit/before/users--desktop-dark.png) · [desktop-light](docs/ui-audit/before/users--desktop-light.png) · [mobile-dark](docs/ui-audit/before/users--mobile-dark.png) · [mobile-light](docs/ui-audit/before/users--mobile-light.png) · [mobile-nav](docs/ui-audit/before/users--mobile-nav.png) | [desktop-dark](docs/ui-audit/after/users--desktop-dark.png) · [desktop-light](docs/ui-audit/after/users--desktop-light.png) · [mobile-dark](docs/ui-audit/after/users--mobile-dark.png) · [mobile-light](docs/ui-audit/after/users--mobile-light.png) · [mobile-nav](docs/ui-audit/after/users--mobile-nav.png) |

---

## Phase 1: page inventory

| Area | Pages |
|---|---|
| Public | Sign in `/login`, Register `/register`, Finish setup `/setup`, Accept invite `/invite/accept`, Reset password `/recover` and `/recover/confirm`, Platform sign-in `/admin/login` |
| Tenant: data | Overview `/home`, Products `/products`, Product `/products/:id`, Add product `/products/new`, Synchronize Catalog `/products/sync`, Submit Events `/events/submit`, Submission `/submissions/:id`, Datasets `/datasets` |
| Tenant: models | Training `/training`, Training run `/training/:jobId`, Model Versions `/models`, Model version `/models/:versionId`, Recommendation Rules `/recommendation-rules` |
| Tenant: operations | Service Status `/service-status`, Usage & Quotas `/usage` |
| Tenant: developer and admin | API Credentials `/credentials`, Integration `/integration`, Team members `/users`, Account `/account` |
| Platform | Status `/admin/status`, Tenants `/admin/tenants`, Tenant `/admin/tenants/:id`, Plans `/admin/plans` and `/admin/plans/:id`, Failures & Audit `/admin/audit` |
| Errors | `/403`, `/404` (also the catch-all route), `/error` |

**Shared building blocks:**
- `layouts/Layouts.tsx`: Shell, sidebar and public split layout.
- `ui/Page.tsx`: page header.
- `ui/Form.tsx`: forms.
- `ui/Dialog.tsx`: dialogs.
- `ui/primitives.tsx`: Badge, Tag, Banner, Stats, FilterBar, DataTable, Cell, Panel, DefinitionList, Meter, EmptyState, CopyButton.
- `lib/format.ts`, `lib/labels.ts`, `lib/quota.ts` and `lib/status.ts`: formatting, labels, quota logic and status tones.
- Styling: tokens in `styles/modernist.css`; layout and four stacked "polish passes" in `styles/console.css`, which by now is 49 KB of overrides layered on overrides.

---

## Phase 2: page audits

### Page: Sign in (`/login`), plus Register, Setup, Reset password and Platform sign-in

Screenshots: `docs/ui-audit/before/login--*.png`, `docs/ui-audit/before/register--*.png`, `docs/ui-audit/before/setup--*.png`, `docs/ui-audit/before/recover--*.png`, `docs/ui-audit/before/admin-login--*.png`

**LG-1. The form is a card inside a card.**
- **Now:** a bordered "Email / Password" box sits inside the bordered sign-in card. At 390 px it is clearly double-boxed.
- **Problem:** "Why are there two boxes? Which one is the form?" The extra border adds noise and takes 40 px of width on mobile.
- **Better:** remove the inner card. The fields sit directly in the sign-in card.

**LG-2. The secondary links are three tiers deep.**
- **Now:** "New to GraphRec? Create a tenant", then "Have a setup link? Finish account setup", then "Platform operator sign-in", each on its own centred line.
- **Problem:** "Which of these is for me?" Three centred lines read as a footer menu.
- **Better:** keep "New to GraphRec? **Create a tenant**" as the single alternative. Put "Finish account setup · Operator sign-in" on one muted line.

**LG-3. On mobile, the brand explanation disappears completely.**
- **Now:** at 390 px only the logo and the form remain.
- **Problem:** "What is GraphRec?" A first-time visitor on a phone gets no context.
- **Better:** add a one-line tagline under the logo on mobile: "Recommendations that learn from every interaction."

**Priority**
- High: LG-1
- Medium: LG-2
- Low: LG-3

**Stronger structure**
```
┌───────────── 5/12 ─────────────┬──────────────── 7/12 ─────────────────┐
│ ◆ GraphRec                     │                              ☾ Dark   │
│                                │   ┌───────────────────────────────┐   │
│  (graph illustration)          │   │ Sign in                       │   │
│  Recommendations that learn…   │   │ Use your tenant credentials…  │   │
│  • Train and version models    │   │ Email     [               ]   │   │
│  • Promote and roll back       │   │ Password  [               ]   │   │
│  • Scoped keys and quotas      │   │ [          Sign in          ] │   │
│                                │   │        Forgot password?       │   │
│  © 2026 GraphRec               │   │ ───────────────────────────── │   │
│                                │   │ New to GraphRec? Create tenant│   │
│                                │   │ Finish setup · Operator login │   │
└────────────────────────────────┴───┴───────────────────────────────┴───┘
```

**Questions this page should answer fast:** Am I in the right place? How do I get in? What do I do if I can't?

---

### Page: Overview (`/home`)

Screenshots: `docs/ui-audit/before/overview--*.png`, `docs/ui-audit/before/overview-empty--*.png`, `docs/ui-audit/before/overview-error--*.png`, `docs/ui-audit/before/overview-loading--*.png`

These issues were confirmed from your screenshots. The earlier round already fixed the two competing banners, the repeated "No interactions" (4×) and "Send events" (3×), the "Continue" button and the sidebar height; this audit verifies those against the real data.

**OV-1. The model's age contradicts itself.**
- **Now:** "since it was trained **20 days ago**" in the status list, and "trained **21 days ago**" on the Active model card.
- **Problem:** "Which is it?" Two numbers for the same fact undermine trust in all the other numbers.
- **Better:** compute both from one helper, so both read "trained 21 days ago".

**OV-2. The 'Over Limit' badge uses title case, unlike every other label.**
- **Now:** a red pill reading "Over Limit".
- **Problem:** inconsistent casing makes it look like a different component.
- **Better:** "Over limit".

**OV-3. The headline doesn't say what the blocking issue is.**
- **Now:** "1 issue needs fixing".
- **Problem:** "What issue?" Users have to read the row below to find out.
- **Better:** when there is one issue, the headline is that issue: "Product storage limit exceeded". When there are several, "2 issues need attention", then the list.

**OV-4. The 'Version 1' tile has no link to the version list.**
- **Now:** "Version 1 · DGSR · trained 21 days ago". Nothing hints that 3 versions exist or that v1 is the *oldest*.
- **Problem:** "Is this the newest model? Why is the oldest one live?"
- **Better:** "Version 1 of 3 · rolled back Sep 12". The tile links to Model Versions.

**OV-5. 'Ready, no traffic' and 'Model activated Sep 12, 2026 at 11:29 PM' wrap badly in a quarter-width card.**
- **Now:** the date breaks across two lines ("…11:29 / PM").
- **Problem:** the card looks broken.
- **Better:** a shorter subline, "Since Sep 12", with the full date and timezone in a tooltip.

**OV-6. The error state stacks five identical red banners.**
- **Now:** at 503, five full-width "The request could not be completed" banners, then a still-rendered empty skeleton.
- **Problem:** "Is everything broken, or five things?" It reads as a cascade, and Retry has to be pressed five times.
- **Better:** one banner, "GraphRec couldn't load the overview. 5 of 6 data sources failed (reference 6f1e…). [Try again]", that retries everything.

**OV-7. The empty tenant (nothing set up) leads with red 'Blocking' rows.**
- **Now:** a new tenant sees "Recommendations are not being served" and "The catalog is empty", both marked Blocking.
- **Problem:** "Did I break something?" For a new tenant this is onboarding, not an incident.
- **Better:** when there are no products and no models, show a "Get started" checklist instead: ① Add your catalog ② Send interaction events ③ Train a model ④ Activate it. Each step has a link.

**OV-8. On mobile the 'Refresh data' button sits between the title and the description.**
- **Now:** Title, then [Refresh data], then the description.
- **Problem:** the action splits the heading from its explanation.
- **Better:** on mobile, show the header actions after the description, or as an icon button next to the title.

**Priority**
- High: OV-1, OV-6, OV-7
- Medium: OV-3, OV-4, OV-8
- Low: OV-2, OV-5

**Stronger structure**
```
Overview                                            ⟳ Refresh data
Health of your data, model and recommendation service.   Updated 2 min ago
┌ ● Product storage limit exceeded ─────────────────────────────────────┐
│ BLOCKING  57,289 of 5,000 products … new products blocked [Manage catalog]│
│ WARNING   No interaction events this period …             [Send events]  │
└──────────────────────────────────────────────────────────────────────────┘
┌ Catalog ──────┐┌ Events ───────┐┌ Active model ─┐┌ Serving ──────┐
│ 57,289 ▓▓▓▓▓▓ ││ 0             ││ Version 1 of 3││ Ready, no     │
│ Over limit    ││ this period   ││ trained 21d   ││ traffic       │
└───────────────┘└───────────────┘└───────────────┘└───────────────┘
Recommendation traffic · last 24 hours
┌ (empty state until the first request) ────────────────────────────────┐
```

**Questions:** Is it running? Is anything blocking me? Is the data flowing? What do I do next?

---

### Page: Products (`/products`)

Screenshots: `docs/ui-audit/before/products--*.png`, `docs/ui-audit/before/products-empty--*.png`, `docs/ui-audit/before/products-error--*.png`

**PR-1. Products are listed in string order.**
- **Now:** Item 0, Item 1, Item 10, Item 100, Item 1000, Item 10000, Item 10001…
- **Problem:** "Where is Item 2?" It looks like data is missing.
- **Better:** sort the visible page naturally (0, 1, 10, 100… becomes 0, 1, 2, 3…). Note that the API orders the whole list by string `external_id`; see the backend list.

**PR-2. The title duplicates the ID on every row.**
- **Now:** "Item 0" with "0" underneath, "Item 1" with "1" underneath, and so on.
- **Problem:** "Why is everything written twice?"
- **Better:** when the title is just "Item {id}", show only the title and hide the ID line. Show the ID line only when it adds information (SKU-4471 under "Brass hinge").

**PR-3. Every row shows '—' for category and '0.00' for price.**
- **Now:** 50 rows of "—" and "0.00".
- **Problem:** "Is the price broken? Are these free?" Two dead columns waste 30% of the width.
- **Better:** if no product on the page has a category or price, hide those columns and show one note: "These products were created from an interaction log and have no category or price yet. [Synchronize catalog] to add them." Show a missing price as "Not set", never "0.00".

**PR-4. The badge and its sub-text repeat on every row.**
- **Now:** "Available" plus "Eligible for recommendations" on every row.
- **Problem:** the repetition makes rows twice as tall (74 px) and hides the rows that differ.
- **Better:** one badge. "Available" means eligible; only excluded rows get an explanation, for example "Out of stock · not recommended".

**PR-5. There are three competing search mechanisms.**
- **Now:** "Search this page", "Availability on this page" and "Find anywhere by external ID" [Find product].
- **Problem:** "Does search look at all 57,289 products or only these 50?" Users can't tell why their product isn't found.
- **Better:** one search box, "Search by title or ID", with the scope stated in it: "Filtering 50 shown of 57,289 · press Enter to find an exact ID across the catalog". Availability becomes a compact select next to it.

**PR-6. 'Add product' stays primary while the catalog is over its limit.**
- **Now:** [Add product] in dark primary style.
- **Problem:** "Why did my save fail?" The page invites an action that will be refused with 429.
- **Better:** while over the limit, disable Add product with the reason "Product limit reached (57,289 of 5,000)", and show a compact banner above the table: "Your catalog is 52,289 products over the Free plan limit. New products are blocked; existing ones can still be updated. [Review usage]".

**PR-7. Pagination is at the bottom of a 4,200 px page and doesn't show the position.**
- **Now:** "50 shown · page 1 of 1,146 · 57,289 products", then [Previous] [Next].
- **Problem:** "How do I jump to page 500? How many are there?"
- **Better:** show "1–50 of 57,289" in the table header, and add pagination (‹ 1 2 3 … 1,146 ›) at both the top and the bottom.

**PR-8. Rows are too tall for a catalog table.**
- **Now:** about 74 px per row.
- **Problem:** only about 10 products fit on a laptop screen.
- **Better:** about 48 px rows, with the title and ID on one line.

**PR-9. The row actions 'Open' and 'Disable' have the same weight on every row.**
- **Now:** two ghost buttons repeated 50 times.
- **Problem:** visual noise; Disable is one stray click from a destructive change. A confirmation dialog does exist, so that part of your list is *not confirmed*.
- **Better:** the row itself links to the product. Disable moves into a "⋯" menu, keeping its confirmation dialog.

**PR-10. On mobile the table overflows with a 'Scroll horizontally' hint.**
- **Now:** "Scroll horizontally to see all columns →"
- **Problem:** at 390 px the Availability column is cut off.
- **Better:** on narrow screens, show each product as a stacked row: title, then the status badge and the updated date.

**Priority**
- High: PR-1, PR-3, PR-5, PR-6
- Medium: PR-2, PR-4, PR-7, PR-8
- Low: PR-9, PR-10

**Stronger structure**
```
Products                                    [Synchronize catalog] [+ Add product (disabled)]
Manage the catalog used for recommendations.
┌ ⚠ Catalog is 52,289 over the Free plan limit (5,000). New products are blocked. [Review usage] ┐
┌ 🔍 Search title or ID…            [Availability ▾]          1–50 of 57,289   ‹ 1 2 … › ┐
│ Product            Availability     Updated                                 ⋯ │
│ Item 0             ● Available      Sep 12, 2026                            ⋯ │
│ …                                                                            │
└──────────────────────────────────────────────────────────────────────────────┘
ⓘ These products came from an interaction log and have no category or price. [Synchronize catalog]
```

**Questions:** How many products do I have? Are they eligible? Can I add more? How do I find one?

---

### Page: Product (`/products/:id`) and Add product (`/products/new`)

**PD-1. The page is a summary on top and the same data as a form below.**
- **Now:** a definition list (External product id, Category, Price, Active "active", Availability "available") and then an editable form with the same fields.
- **Problem:** "Which one do I edit?" Everything is shown twice.
- **Better:** a single form with a read-only header row: "Item 0 · ● Available · Updated Sep 12". Remove the duplicate definition list.

**PD-2. Raw enum values are shown.**
- **Now:** "Active: active", "Availability: available" (monospace).
- **Problem:** this looks like debug output.
- **Better:** one badge, "Available"; "Inactive" only when that's the case.

**PD-3. The metadata textarea shows raw JSON.**
- **Now:** `{ "source": "interaction_log" }`
- **Problem:** "Can I break something by editing this?"
- **Better:** label it "Metadata (advanced, JSON)" and keep it collapsed by default.

**PD-4. 'Update product' and 'Back to products' have no unsaved-changes state.**
- **Now:** the primary button is always active.
- **Problem:** "Did I change anything?"
- **Better:** disable Save until something changes, and show a "● Unsaved changes" marker.

**PD-5. Add product shows no limit warning.**
- **Now:** a normal form while the catalog is over its limit.
- **Problem:** the save will fail with 429.
- **Better:** a banner at the top, "Your catalog is over its product limit. Saving a new product will be refused. [Review usage]", and disable "Save product".

**Priority**
- High: PD-5
- Medium: PD-1, PD-2
- Low: PD-3, PD-4

**Questions:** Is this product recommended? What do I change? Did it save?

---

### Page: Synchronize Catalog (`/products/sync`)

**SY-1. The JSON textarea is the whole UI, with no example of the result.**
- **Now:** a "Product collection (JSON)" placeholder and [Submit synchronization].
- **Problem:** "What happens to my existing products?"
- **Better:** a short "Creates new IDs and updates existing ones. Up to 1,000 per request." above the field, plus a "Validate" step that shows "3 new · 2 updated · 1 invalid" before submitting.

**SY-2. 'Required / Optional fields' lives in a separate card below the form.**
- **Problem:** users read the field list after they've already pasted their data.
- **Better:** move it into the field hint.

**SY-3. The over-limit state isn't reflected.**
- **Problem:** syncing new products will fail.
- **Better:** "Only updates to existing products will be accepted while the catalog is over its limit."

**Priority**
- High: SY-3
- Medium: SY-1
- Low: SY-2

**Questions:** What will this change? Did it work? What failed?

---

### Page: Submit Events (`/events/submit`) and Submission (`/submissions/:id`)

**EV-1. The 'Submission mode' select sits in its own card above the form.**
- **Now:** a card with "Submission mode [Single Event ▾]".
- **Problem:** "Is this a filter or part of the form?"
- **Better:** a segmented control in the form header: [Single event | Batch (JSON)].

**EV-2. Submissions are labelled by raw UUID.**
- **Now:** `c8f23e8a-f7bd-4189-abab-806afea09933` as both the link text and the detail page title ("Submission c8f23e8a-…-806afea09933").
- **Problem:** this is unreadable and wraps on mobile.
- **Better:** "Batch of 2 events · Sep 12, 2026 at 10:51 PM", with the ID as a copyable chip.

**EV-3. The table lists only batches, not single events.**
- **Now:** "Recent batch submissions".
- **Problem:** "I just sent an event; where is it?"
- **Better:** say so: "Single events are confirmed inline and are not listed here."

**EV-4. Placeholders look like filled values.**
- **Now:** "ev-33810", "cus-9931", "SKU-6002" in grey monospace.
- **Problem:** at a glance they read as pre-filled data.
- **Better:** "e.g. ev-33810".

**Priority**
- Medium: EV-1, EV-2, EV-3
- Low: EV-4

**Questions:** How do I send events? Did the last batch work? How many were rejected?

---

### Page: Datasets (`/datasets`)

**DS-1. Every snapshot says 'Not used yet' although all three training runs used one.**
- **Now:** "2c2825a1… · Not used yet", while every job lists `dataset_snapshot_id = 2c2825a1…`.
- **Problem:** "Was my model trained on this?" The page contradicts Training.
- **Better:** derive usage from the training runs: "Used by 3 training runs". (The backend leaves `training_job_id` null; see the backend list.)

**DS-2. Three near-identical snapshots, and nothing explains why.**
- **Now:** 394,912 / 57,288, then 394,908 / 57,289, then 394,908 / 57,289, all on Sep 12 within 2 minutes.
- **Problem:** "Which one should I use?"
- **Better:** mark the newest "Latest" and show the difference from the previous snapshot ("+4 events, −1 product").

**DS-3. The checksum column shows truncated hashes.**
- **Now:** "2c2825a1a3f9…"
- **Problem:** this is noise for almost everyone.
- **Better:** drop the column; the checksum stays available behind a copyable ID chip in the row details.

**DS-4. The import is hidden in a collapsed 'Import products and events from a file'.**
- **Problem:** the primary job of the page is hidden behind a disclosure.
- **Better:** a header action, [Import file], next to [Take snapshot].

**Priority**
- High: DS-1
- Medium: DS-2, DS-4
- Low: DS-3

**Questions:** What data do I have? Which snapshot trained my model? How do I add more?

---

### Page: Training (`/training`) and Training run (`/training/:jobId`)

**TR-1. A succeeded run shows '0% · completed'.**
- **Now:** "Progress: 0% · completed".
- **Problem:** "Did it fail?" A finished run shown at 0% looks broken.
- **Better:** show progress only while running. For a finished run: "Completed in 4 s".

**TR-2. A pretrained import is called 'Train a DGSR model'.**
- **Now:** "DGSR training run", plus a banner explaining "Train a DGSR model from tenant data, or import a prepared checkpoint".
- **Problem:** "Did it train, or did it import?" All three runs are `pretrained_import` and took 3–4 seconds.
- **Better:** label the mode: "Imported checkpoint `dgsr_beauty_t4_v2`" vs "Trained on snapshot …".

**TR-3. The training-run metric label is malformed.**
- **Now:** "evaluated_Evaluated examples".
- **Problem:** a visible bug.
- **Better:** "Evaluated examples: 47,404".

**TR-4. Raw IDs: 'Produced version v20260912172515-a42c3b'.**
- **Better:** "Version 3 (Retired)", with the tag in a chip.

**TR-5. The automatic retraining form shows dependent inputs as active while their toggles are off.**
- **Now:** "Retrain on a fixed interval ☐" next to an active "Interval (minutes) [1440]".
- **Problem:** "Is it on?"
- **Better:** disable or dim dependent fields until their toggle is on, and phrase the toggle as a sentence ("Retrain every [1440] minutes").

**TR-6. The configuration is shown as a raw JSON block.**
- **Now:** `{"mode": "pretrained_import", "pretrained_artifact": "dgsr_beauty_t4_v2"}`
- **Better:** key/value rows, "Mode: Pretrained import", "Checkpoint: dgsr_beauty_t4_v2"; the JSON goes behind a "View JSON" toggle.

**TR-7. The footnote is jargon.**
- **Now:** "Validation selects the checkpoint; test metrics use held-out next-item targets. Local worker capacity is bounded and queued work survives restarts."
- **Better:** drop it, or move it to a ⓘ tooltip on "Quality measures".

**Priority**
- High: TR-1, TR-3, TR-5
- Medium: TR-2, TR-4
- Low: TR-6, TR-7

**Questions:** Did it work? What did it produce? How good is it? Will it retrain on its own?

---

### Page: Model Versions (`/models`) and Model version (`/models/:id`)

**MV-1. Every version shows identical quality metrics.**
- **Now:** "Hit@5 0.397 · Hit@10 0.496" on v1, v2 and v3.
- **Problem:** "Are these real? Why compare?" All three were imported from the same checkpoint.
- **Better:** detect identical metrics and say so: "Same checkpoint as v1 (dgsr_beauty_t4_v2): identical scores". Show a metric difference only when it is non-zero.

**MV-2. 'Activate' is greyed out on every row with no reason.**
- **Now:** a disabled "Activate" next to Active, Retired and Archived alike.
- **Problem:** "Why can't I activate v3?" The reason exists only as a hover tooltip.
- **Better:** show the action that is actually possible: Retired → [Roll back to this]; Archived → no action, with the hint "Archived: kept for audit, cannot serve"; Eligible → [Activate].

**MV-3. Retired and Archived aren't explained.**
- **Problem:** "What's the difference?"
- **Better:** a status legend under the table: "**Eligible**: ready to activate · **Active**: serving now · **Retired**: previously active, available for rollback · **Archived**: removed from rollback, kept for audit", and the same text in each badge's tooltip.

**MV-4. The newest version is Retired while the oldest is Active, and nothing says why.**
- **Now:** v3 Retired, v2 Archived, v1 Active.
- **Problem:** "Is the system serving an old model by mistake?"
- **Better:** a line on the active row and on the strip: "Active since Sep 12, 11:29 PM: rolled back from v3".

**MV-5. The 'Active model' strip duplicates the table row.**
- **Better:** drop the strip. The active row gets a highlighted background and goes first, sorted Active → Eligible → Retired → Archived, then by date.

**MV-6. The metrics column is one dot-joined string.**
- **Now:** "Hit@5 0.397 · Hit@10 0.496".
- **Better:** two numeric columns, "Hit@10" and "NDCG@10", right-aligned with tabular numbers.

**MV-7. The detail page puts 'Quality against the active version' under a column 'Active – / Δ active –' even when this version *is* the active one.**
- **Now:** a full column of "–" dashes.
- **Problem:** this looks like broken data.
- **Better:** when the version is active, show a single "Score" column. For other versions, compare and colour the difference.

**MV-8. Metric keys are raw.**
- **Now:** "validation.Hit@5", "validation.evaluated_examples 47404.0000".
- **Better:** "Hit@5", plus a note "Evaluated on 47,404 examples (sampled, 1 positive + 100 negatives)".

**MV-9. The Artifact and index section shows `file:///artifacts/dgsr_beauty_t4_v2` broken across lines and 'Embedding index: not recorded on the version'.**
- **Better:** "Checkpoint dgsr_beauty_t4_v2" as a chip, and "Index: not recorded" in muted text.

**Priority**
- High: MV-1, MV-2, MV-4, MV-7
- Medium: MV-3, MV-5, MV-6, MV-8
- Low: MV-9

**Stronger structure**
```
Model Versions                                         [Go to training]
Each training run registers a version. Only one serves at a time.
┌ Version            Status      Hit@10  NDCG@10  Created          Action          ┐
│ ▌Version 1         ● Active    0.496   0.338    Sep 12, 10:48 PM  —               │
│   rolled back from v3 · Sep 12, 11:29 PM                                         │
│  Version 3         ◷ Retired   0.496   0.338    Sep 12, 11:25 PM  [Roll back]     │
│  Version 2         ▢ Archived  0.496   0.338    Sep 12, 10:49 PM  —               │
└──────────────────────────────────────────────────────────────────────────────────┘
ⓘ All three versions come from the same checkpoint (dgsr_beauty_t4_v2), so their scores are identical.
Legend: Active = serving · Retired = rollback target · Archived = kept for audit
```

**Questions:** Which model is serving? Is it the best one? What can I do with the others?

---

### Page: Recommendation Rules (`/recommendation-rules`)

**RR-1. Inputs look active while their toggles are off.**
- **Now:** "Limit how many items share one category ☐" next to an active "Maximum items per category [3]"; the same for the freshness weight and half-life.
- **Problem:** "Is diversity on? Will 3 apply?"
- **Better:** each rule is a card with a switch in its header. Its inputs are disabled and dimmed while the switch is off.

**RR-2. The summary duplicates the form.**
- **Now:** "Diversity Off · Freshness Off · Last changed —" above the same toggles.
- **Better:** drop the summary. The card headers carry the state ("Category diversity · Off").

**RR-3. There's no Cancel or unsaved-changes state.**
- **Now:** [Save rules] only, always enabled.
- **Better:** a sticky footer that appears only when something has changed: "● Unsaved changes [Discard] [Save rules]".

**RR-4. The info box is jargon.**
- **Now:** "Bounded and explainable. Rules only reorder eligible products after exclusions; they never add products. Freshness can move an item up by at most about 43% of the relevance range at the maximum weight (0.3)…"
- **Better:** "Rules reorder the recommended products; they never add or remove any." The details go into each rule's hint.

**RR-5. The grid is uneven.**
- **Now:** toggles in the left column and inputs on the right; "Freshness half-life" wraps alone into a new row.
- **Better:** one card per rule, inputs stacked inside.

**RR-6. 'Last changed —' and the pill 'Not configured — relevance order only' compete.**
- **Better:** in the header: "Using relevance order only (no rules saved yet)".

**RR-7. The 'Refresh data' button also discards unsaved edits, silently.**
- **Problem:** data loss.
- **Better:** remove Refresh from this page; the form loads fresh on every visit.

**Priority**
- High: RR-1, RR-3, RR-7
- Medium: RR-2, RR-4, RR-5
- Low: RR-6

**Stronger structure**
```
Recommendation Rules
Rules reorder recommended products; they never add or remove any.
Using relevance order only (no rules saved yet)
┌ Category diversity                                         [  off ] ┐
│ At most [3] items from one category (1–100)          (dimmed when off) │
└────────────────────────────────────────────────────────────────────────┘
┌ Freshness boost                                            [  off ] ┐
│ Weight [0.2] (0–0.3) · Half-life [30] days (1–3650)                    │
└────────────────────────────────────────────────────────────────────────┘
                                   ● Unsaved changes  [Discard] [Save rules]
```

**Questions:** What rules are live? What will change if I turn one on? Did my change save?

---

### Page: Service Status (`/service-status`)

**SS-1. Recorded model quality is a raw key/value dump.**
- **Now:** "items (source) 57289.0000", "layers (source) 3.0000", "embedding_dim (source) 50.0000", "checkpoint_epoch (source) 2.0000", and two full 64-character hashes.
- **Problem:** "What am I supposed to learn from this?" Counts appear as floats and hashes take 3 lines each.
- **Better:** split it into "Quality" (Hit@5/10/20, NDCG@5/10/20 in a compact table) and "Model details", with friendly labels and integers: Items 57,289 · Users 52,204 · Interactions 394,908 · Embedding size 50 · Layers 3 · Checkpoint epoch 2. Hashes go behind "Copy fingerprint" chips.

**SS-2. Labels break mid-word.**
- **Now:** "catalog_item_coverag / e (source)", "embedding_dim / (source)".
- **Better:** friendly labels plus `overflow-wrap: normal` on definition-list labels.

**SS-3. `indexed_items` (57,288) doesn't match `items` (57,289).**
- **Problem:** "Is one product missing from recommendations?"
- **Better:** show "Indexed 57,288 of 57,289 items (1 not indexed)" in amber. This is also listed for the backend.

**SS-4. 'mode (validation) sampled_101' isn't explained.**
- **Better:** "Evaluation: sampled, 1 positive and 100 random negatives per user, 47,404 examples."

**SS-5. The page is four similar cards with equal weight.**
- **Now:** Serving configuration, Rate limiting, Serving capacity, Recommendation traffic, Recorded model quality.
- **Problem:** "Is it serving or not?" The answer is a small badge in the first card.
- **Better:** a status header: "● Serving model Version 1 · ready, no traffic in the last hour". Then Traffic first, then Capacity and rate limiting (collapsed when healthy), then Model.

**SS-6. The capacity text is long and wraps awkwardly.**
- **Now:** "1 ready of 1 desired (range 1–1)", and "1 unit per 120 req/min; scale up at once, down after 120s of lower demand" in a narrow column; plus a long italic "limitation" paragraph.
- **Better:** "Capacity 1 of 1 ready (fixed: min = max = 1)". The policy line moves to a tooltip.

**SS-7. The banner text is too wide.**
- **Now:** "No requests in this window — Rates and latency will appear…" across about 140 characters.
- **Better:** cap prose at 70ch.

**SS-8. Empty scaling-events state plus '0 recent scaling events' plus [Refresh capacity] says one thing three times.**
- **Better:** one muted line: "No scaling changes yet."

**Priority**
- High: SS-1, SS-2, SS-3, SS-5
- Medium: SS-4, SS-6, SS-8
- Low: SS-7

**Stronger structure**
```
Service Status                                              ⟳ Refresh data
┌ ● Serving Version 1 (DGSR) · Ready, no traffic in the last hour ─────────────┐
Traffic  [Last hour ▾]   Requests 0 · p95 — · Errors — · Fallback —  (empty state)
Model    Quality (Hit/NDCG table)  ·  Details (items, users, interactions …)
         ⚠ Indexed 57,288 of 57,289 items
Infrastructure (collapsed when healthy): Capacity 1/1 · Rate limiter ● Healthy (Redis)
```

**Questions:** Is it serving? Which model? Is traffic flowing? Is anything degraded?

---

### Page: Usage & Quotas (`/usage`)

**US-1. The 'Remaining' column shows a meter even for informational rows, and '0 remaining' when the tenant is 52,289 over.**
- **Now:** Stored products "57,289 | 5,000 | 0 remaining | Exhausted".
- **Problem:** "0 remaining" understates the problem.
- **Better:** "52,289 over" in red, and a status of "Over limit" (distinct from "Limit reached" when used equals the limit exactly).

**US-2. Two billing periods disagree.**
- **Now:** usage says "Resets Nov 1, 2026" and "Period Oct 1 – Nov 1"; the Subscription section says period Sep 12 – Oct 12.
- **Problem:** "When does my quota reset?"
- **Better:** show one period and flag the mismatch for the backend.

**US-3. 'Training cpu seconds' and 'Replica runtime minutes' show 'No limit / Not applicable / Informational'.**
- **Better:** group them under "Tracked, no limit", without meters or badges.

**US-4. The usage trends controls take a full card even when there is no data.**
- **Better:** when there is no usage, show the empty state first and keep the controls compact.

**US-5. The 'Artifact storage' row reads 0 B even though three models exist.**
- **Problem:** this is suspicious data.
- **Better:** "0 B (imported checkpoints are not counted)". Also on the backend list.

**Priority**
- High: US-1, US-2
- Medium: US-3, US-5
- Low: US-4

**Questions:** Am I over any limit? What's blocked? When does it reset? What plan am I on?

---

### Page: API Credentials (`/credentials`)

**CR-1. The 'Allowed operations' cell is a wall of text.**
- **Now:** "10 operations — catalog read · catalog write · result read · event submission · training read · training request · models read · models write · activation · recommendations".
- **Better:** a scope-preset label ("Full access", "Storefront: catalog, events, recommendations"), with the full list in a popover.

**CR-2. Empty 'Expires', 'Revoked at' and 'Last used' columns are all '—'.**
- **Better:** merge them into one "Last used" column ("Never used" / "Sep 12"); show "No expiry" only when relevant. Drop "Revoked at" from the active list.

**CR-3. Name and prefix break across lines.**
- **Now:** "seed- / 39f889", "gr_live / _MtOTPc / 2q…".
- **Better:** no wrapping inside names; the prefix as a chip.

**CR-4. Rotate and Revoke look equally safe.**
- **Better:** Revoke styled as a danger action inside a ⋯ menu, with the confirmation kept.

**Priority**
- Medium: CR-1, CR-2, CR-3
- Low: CR-4

**Questions:** Which keys exist? Which are used? Is anything overly permissive?

---

### Page: Integration (`/integration`)

**IN-1. The page is 4,100 px of code with no navigation.**
- **Better:** a sticky table of contents (Authentication · Catalog · Events · Recommendations · Errors) and collapsible examples.

**IN-2. The Base URL and auth rows break mid-token.**
- **Now:** "http://localhost:5001/v / 1".
- **Better:** a monospace chip with a copy button, no breaks.

**IN-3. The jargon '403 insufficient_scope' appears in body copy.**
- **Better:** "Requests outside a key's permissions are refused (403)."

**Priority**
- Medium: IN-1, IN-2
- Low: IN-3

---

### Page: Team members (`/users`)

**TM-1. Display names equal the email local-part ("owner-39f889") and are repeated above the email.**
- **Better:** if the name equals the email prefix, show only the email.

**TM-2. There are no row actions for active members.**
- **Problem:** "How do I remove someone or change a role?"
- **Better:** if the API doesn't support it, say so: "Role changes are handled by your platform operator."

**Priority**
- Low: TM-1, TM-2

---

### Page: Account (`/account`)

**AC-1. 'Tenant ID: Not available' while the sidebar shows the tenant.**
- **Problem:** this is contradictory.
- **Better:** read the tenant ID the same way the sidebar does; if it's still missing, hide the row.

**AC-2. The email wraps mid-word ("owner- / 39f889@beauty.example").**
- **Better:** no breaking inside email addresses (`overflow-wrap: anywhere` only as a last resort).

**AC-3. A 16-row permission table with 'Granted' on every row.**
- **Better:** "Tenant administrator: full access to this tenant" as one line, with the table collapsed under "View all permissions"; only "Not granted" rows are highlighted.

**Priority**
- Medium: AC-1, AC-3
- Low: AC-2

---

### Pages: Platform console (`/admin/*`)

**PL-1. Quota overrides list raw snake_case keys.**
- **Now:** "training_jobs", "accepted_events", "stored_products" in monospace.
- **Better:** "Training jobs", "Accepted events" and so on, with the key in a tooltip.

**PL-2. The tenant detail shows '57,289 of 5,000' with remaining '0' and no warning.**
- **Better:** the same "Over limit" treatment as the tenant console (US-1).

**PL-3. The Plans list shows 'Limits: 3 limits'.**
- **Better:** show the two key limits: "5,000 products · 2M events/mo".

**PL-4. The platform sidebar has a single group, plus the status pill 'Platform console' in monospace.**
- **Better:** a plain subtitle, "Platform operator".

**Priority**
- Medium: PL-1, PL-2
- Low: PL-3, PL-4

---

### Error and empty states (`/404`, error, loading)

**ER-1. The error banner shows the correlation ID inline as 'ref 6f1e2a90-…' next to Try again.**
- **Better:** "Reference 6f1e2a90" as a copyable chip.

**ER-2. Loading uses grey bars of equal height for every page.**
- **Better:** skeletons shaped like the content (a header row and table rows).

**ER-3. 404: 'A resource belonging to another tenant is indistinguishable from one that does not exist.'**
- **Problem:** security jargon shown to users.
- **Better:** "This page doesn't exist, or you don't have access to it. [Go to Overview]".

**Priority**
- Medium: ER-1, ER-3
- Low: ER-2

---

## Cross-page findings (fixed once in shared code)

| ID | Finding | Where | Fix |
|---|---|---|---|
| X-1 | Four layered "polish passes" in `console.css` override each other, so spacing and borders are inconsistent and nested cards appear (LG-1) | all | Consolidate into one token-driven layer: spacing scale, radii, card and section rules applied once |
| X-2 | No max-width for prose: banners and footnotes run to about 140 characters | all | `max-width: 70ch` on prose (`.banner .b-body`, `.footnote`, `.subtitle`, `.p-body`) |
| X-3 | Definition-list labels break mid-word and values wrap at 140 px | Service Status, Account, Model, Training run | Wider label column, `overflow-wrap: normal` for labels, `break-word` (not `anywhere`) for values |
| X-4 | Metric and usage keys rendered raw (`validation.Hit@5`, `evaluated_examples 47404.0000`, snake_case) | Models, Training run, Service Status, Platform | One `metricLabel`/`humanizeKey` plus a number formatter that never prints integers as floats |
| X-5 | Status badges for Model (Eligible/Active/Retired/Archived) have no explanation | Models, Training, Service Status | Badge `title` tooltips plus a status legend component |
| X-6 | Long IDs as titles and links (UUIDs, version tags) | Submission, Training run crumbs, Datasets, Credentials | `IdChip` (shortened, monospace, copy on click) and human labels everywhere |
| X-7 | "Copy" buttons are full secondary buttons next to every ID | Model, Training run, Account | IdChip with a copy icon; one visual weight |
| X-8 | Header actions jump between title and subtitle on mobile | all pages with actions | Mobile: actions under the description, full-width row |
| X-9 | Mobile navigation trigger is a text button, "Open navigation" | all | Icon button (☰) with aria-label; the drawer overlays the page and has a scrim |
| X-10 | Tables: string sort, rows of "—", 70+ px rows, a "Scroll horizontally" hint | Products, Credentials, Datasets | Natural sort, auto-hidden empty columns, compact rows, card rows on mobile |
| X-11 | Dependent form fields look active while their toggle is off | Rules, Retraining | Fieldsets disabled while off |
| X-12 | Forms have no unsaved-changes state; "Refresh" discards edits | Rules, Retraining, Product | Dirty tracking plus a sticky save bar; no Refresh on form pages |
| X-13 | Error states stack one banner per failed request | Overview, Service Status | Shared aggregate error with a single retry |
| X-14 | Dates: relative and absolute day counts disagree (20 vs 21 days) | Overview | One `daysAgo` helper |

---

## Phase 3: what changed

### Foundation (`styles/system.css`, a new layer loaded last)

- **Semantic colour tokens:**
  - red = error and blocking; amber = warning; green = success; neutral = information.
  - `--color-link` (blue) is the only interaction colour.
  - The brand orange is reserved for the logo and the focus ring.
- **Scales:** spacing 4/8/12/16/24/32/48 px; type 12/13/14/16/18/22/28 px.
- **Widths:** `--content-max: 1200px` for pages; `--prose-max: 70ch` applied to subtitles, banners, footnotes and empty states.
- **Page header pattern:** breadcrumb, then title with badge, description, an "Updated…" line and actions on the right. On mobile the actions move under the description.
- **Button hierarchy:** one primary per view. A disabled primary looks neutral and shows its reason; Add product drops to secondary while it is blocked.
- **Nested-card guard:** a card can no longer render inside another card (this fixes the double-boxed sign-in form).
- **Definition lists:** a wider label column, no breaking inside words, and dates that never wrap.

### Shared components and helpers

- **Badges:** status-specific shapes (✓ finished, ✕ failed, ● live, spinner while running), plus a tooltip from `STATUS_HELP`. A new `StatusLegend` explains the model statuses.
- **`IdChip`:** a shortened monospace ID that copies on click. It replaces every "value + [Copy]" pair in definition lists, and is used for snapshots, checkpoints, error references and run IDs.
- **Formatters** in `lib/labels.ts`:
  - `humanizeKey` (`embedding_dim` → "Embedding size").
  - `formatMetricValue` (integers never print as floats; coverage prints as a percent).
  - `evaluationModeLabel` (`sampled_101` explained in plain words).
  - `naturalCompare` (0, 1, 2 … 10).
  - `daysSince` / `daysAgoLabel` (one rounding rule everywhere).
- **Dates** read "Sep 12, 2026 at 11:29 PM", with the full timestamp and timezone in a tooltip; this was already in place and is now used consistently.
- **ErrorBanner:** the message, then [Try again] and "Reference ⧉" on their own line. The Overview shows one combined error instead of five.
- **Tables:**
  - A pager with position ("1–50 of 57,289 · Page 1 of 1,146") at the top and bottom.
  - Highlighted rows, right-aligned numeric columns and a "⋯" row menu.
  - A `.table-mobile-cards` mode that turns rows into cards at 390 px, with no horizontal scroll.
- **Dependent settings:** a switch plus a dimmed, disabled body while off, and a sticky save bar ("● Unsaved changes [Discard] [Save rules]").
- **Navigation:**
  - The sidebar runs full height and is sticky on desktop.
  - On mobile, a ☰ icon button opens an overlay drawer with a scrim, closed by Esc or a tap outside.
  - The tenant workspace link and the platform console label use the same style.

### Pages

- **Overview:**
  - A single issue becomes the headline.
  - Model age is consistent ("trained 21 days ago" in both places).
  - The model tile reads "Version 1 of 3", with "Rolled back from a newer version".
  - The serving tile says "Since Sep 12".
  - A brand-new tenant gets a four-step "Get started" checklist instead of red Blocking rows.
  - API failures produce one combined error, and the status summary is hidden while data is missing, so it can no longer say "Everything is healthy" during an outage.
- **Products:**
  - The current page is natural-sorted.
  - The placeholder ID line is gone ("Item 0" only).
  - Empty Category and Price columns are hidden, with one explanatory note.
  - Each row has a single badge; only excluded rows get a sub-line.
  - There is one search field (scope stated, Enter opens an exact ID) plus an Availability select.
  - Add product is disabled with a reason, and an over-limit callout sits above the table.
  - Pager top and bottom, compact rows, a ⋯ menu with "Disable…" (confirmation kept), and mobile cards.
- **Product and Add product:**
  - The detail page header shows the availability badge, a copyable external ID and the updated date; the duplicate definition list is gone for editors.
  - Raw enums are replaced by labels.
  - Add product shows an over-limit warning.
- **Synchronize catalog:** shorter, plainer description, plus an over-limit warning explaining that updates still work.
- **Submit Events and Submission:**
  - The list reads "Batch of 2 events" with a short ID.
  - The detail title is "Event batch · Sep 12, 2026 at 10:51 PM".
  - Placeholders read "e.g. …".
  - A note explains that single events aren't listed.
  - Count columns are no longer monospace.
- **Datasets:**
  - Usage is derived from the training runs ("Used by 3 training runs").
  - The newest snapshot is marked "Latest", with the difference from the previous one ("+4 events, −1 products vs previous").
  - The checksum column is gone; the ID is an IdChip.
- **Training and Training run:**
  - Finished runs show "Completed in 4 s" instead of "0% · completed".
  - The source reads "Imported checkpoint dgsr_beauty_t4_v2" vs "Trained on tenant data".
  - "evaluated_Evaluated examples" is fixed.
  - The configuration is a key/value grid, with the raw JSON behind "View as JSON".
  - The jargon footnote and the banner are gone; the produced version shows its status badge.
  - In retraining, inputs are disabled while their switch is off, and an unsaved-changes note appears.
- **Model Versions and Model version:**
  - Versions are sorted Active → Eligible → Retired → Archived; the active row is highlighted, with "Rolled back from v3".
  - Hit@10 and NDCG@10 are numeric columns, with an identical-scores callout naming the shared checkpoint.
  - Each row offers the action that is actually possible: [Activate], [Roll back to this], "Audit only" or "Serving". Roll back to this opens the rollback dialog on the active version's page with that target selected.
  - The status legend is shown, and the duplicate strip is removed.
  - On the detail page, the active version shows a single Score column; other versions get a coloured Difference column.
  - Friendly metric names, an evaluation explanation, and Checkpoint and Snapshot as IdChips.
- **Recommendation Rules:**
  - One card per rule, with a switch.
  - Inputs are disabled and dimmed while the switch is off.
  - The duplicate summary is gone; the live state is a single header line.
  - Sticky Discard/Save bar with an unsaved-changes state.
  - No more Refresh button that silently discarded edits.
  - Plain-language copy.
- **Service Status:**
  - A status header ("Serving DGSR model · v1. Ready, but no recommendation requests in the last hour. Active since Sep 12, 2026 at 11:29 PM").
  - Traffic now comes before infrastructure.
  - Quality is a compact Top-5/10/20 × Hit/NDCG table, and model details are a key/value grid of integers ("57,289", "100%").
  - Hashes are behind IdChips.
  - An amber callout: "1 of 57,289 items are not in the embedding index".
  - `sampled_101` is explained in plain words.
  - Capacity copy is shorter ("1 of 1 ready (fixed at 1)"), and the long limitation text sits behind a disclosure.
- **Usage & Quotas:**
  - "52,289 over the limit" in red, with an "Over limit" status.
  - Alert copy reads "Product storage limit exceeded… (52,289 over)".
  - Unlimited rows say "Tracked, no limit".
  - A note when the subscription period and the usage reset disagree.
- **API Credentials:**
  - Name and prefix sit together.
  - Access shows a preset label ("Storefront: catalog, events and recommendations"), with the full list in a tooltip.
  - "Never used" and "No expiry" replace dash-only columns.
  - Revoke is red.
- **Account:**
  - "Tenant administrator: full access to this tenant", with the permission table collapsed.
  - Only missing permissions are highlighted.
- **Platform:**
  - Quota and plan keys are humanised.
  - Over-limit usage shows "N over".
  - The plans list shows key limits.
  - The console label uses the workspace style.
- **Sign in:**
  - No more card inside a card.
  - The secondary links are on one muted line.
  - A tagline appears on mobile.
- **404:** "Page not found. This page doesn't exist, or you don't have access to it. [Go to Overview]".

### Tests

All 61 frontend tests pass. Three tests were updated to the new copy:
- the 404 heading "Page not found";
- two "Next" buttons now exist (the pager is at the top and the bottom);
- the usage alert title, from the previous round.

No dependencies were added.

---

## Phase 4: verification

After screenshots are in `docs/ui-audit/after/` with the same names as `docs/ui-audit/before/`.

| ID | Status | Note |
|---|---|---|
| LG-1 | Fixed | nested-card guard |
| LG-2 | Fixed | |
| LG-3 | Fixed | |
| OV-1 | Fixed | shared `daysSince` |
| OV-2 | Fixed | |
| OV-3 | Fixed | single issue becomes the headline |
| OV-4 | Fixed | "Version 1 of 3", rollback note |
| OV-5 | Fixed | |
| OV-6 | Fixed | one combined error; status hidden while data is missing |
| OV-7 | Fixed | Get started checklist |
| OV-8 | Fixed | mobile header order |
| PR-1 | Partially fixed | the current page is natural-sorted; true catalog order needs the API (see backend list) |
| PR-2 | Fixed | |
| PR-3 | Fixed | empty columns hidden, plus a note |
| PR-4 | Fixed | |
| PR-5 | Partially fixed | one search field, scope stated, Enter opens an exact ID; full-catalog text search needs an API endpoint |
| PR-6 | Fixed | |
| PR-7 | Partially fixed | position and pager at top and bottom; no jump-to-page input |
| PR-8 | Fixed | |
| PR-9 | Fixed | ⋯ menu, confirmation kept |
| PR-10 | Fixed | mobile cards |
| PD-1 | Fixed | |
| PD-2 | Fixed | |
| PD-3 | Deferred | low value; the metadata editor is unchanged |
| PD-4 | Deferred | needs dirty tracking in the shared `Form`; done for Rules and Retraining first |
| PD-5 | Fixed | |
| SY-1 | Partially fixed | clearer copy; a "Validate" dry-run needs an API option |
| SY-2 | Deferred | low |
| SY-3 | Fixed | |
| EV-1 | Partially fixed | the single-filter bar is now compact; a segmented control is deferred |
| EV-2 | Fixed | |
| EV-3 | Fixed | |
| EV-4 | Fixed | |
| DS-1 | Fixed | derived from training runs (backend leaves `training_job_id` empty) |
| DS-2 | Fixed | |
| DS-3 | Fixed | |
| DS-4 | Deferred | moving the uploader into a header dialog is a bigger refactor |
| TR-1 | Fixed | |
| TR-2 | Fixed | |
| TR-3 | Fixed | |
| TR-4 | Partially fixed | status badge added; the tag is still shown, not "Version 3" |
| TR-5 | Fixed | |
| TR-6 | Fixed | |
| TR-7 | Fixed | |
| MV-1 … MV-9 | Fixed | |
| RR-1 … RR-7 | Fixed | |
| SS-1 … SS-8 | Fixed | SS-3 is surfaced in the UI; the cause is in the backend list |
| US-1 | Fixed | |
| US-2 | Partially fixed | the UI explains the mismatch; the periods themselves need a backend fix |
| US-3 | Partially fixed | meters removed; the "Informational" tag kept (a test asserts it) |
| US-4 | Deferred | low |
| US-5 | Deferred | backend: imported checkpoints report no `artifact_bytes` |
| CR-1 … CR-3 | Fixed | |
| CR-4 | Partially fixed | Revoke is red and keeps its confirmation, but is still an inline button |
| IN-1, IN-2 | Deferred | long reference page; a table of contents and chip formatting are next |
| IN-3 | Fixed | |
| TM-1, TM-2 | Deferred | low; role changes have no API |
| AC-1 | No change needed | the real session token carries `tid`; "Not available" came from my capture fixture, which is now corrected |
| AC-2 | Partially fixed | the email still wraps once at 1440 px in a three-column list |
| AC-3 | Fixed | |
| PL-1 … PL-4 | Fixed | |
| ER-1 | Fixed | |
| ER-2 | Deferred | low |
| ER-3 | Fixed | |
| X-1 | Partially fixed | a single final layer (`system.css`) now owns the foundation; the older passes in `console.css` remain and should be folded in |
| X-2 … X-5 | Fixed | |
| X-6 | Partially fixed | applied to definition lists, models, datasets, training and errors; the credential prefix is still plain text |
| X-7 … X-9 | Fixed | |
| X-10 | Partially fixed | applied to Products, Models and Datasets; Credentials and Team still use the scroll-table layout on mobile |
| X-11 | Fixed | |
| X-12 | Partially fixed | Rules and Retraining; the Product form is deferred |
| X-13, X-14 | Fixed | |

---

## Backend/data issues for Hasin

None of these were changed; the UI now shows them honestly.

1. **Product listing is string-ordered.** `GET /v1/products` sorts `external_id` as text (0, 1, 10, 100, 1000, 10000…). Add a numeric-aware order or an explicit `sort=` parameter. The UI can only sort the 50 rows it has.
2. **No server-side product search.** "Search this page" can't find a product on another page by title. Add a `q=` filter to `GET /v1/products`.
3. **Catalog far over plan.** 57,289 stored against a Free-plan limit of 5,000. Writes are now enforced correctly, and admins get the below-usage confirmation, but this tenant should be moved to Basic or Pro, or cleaned up.
4. **Training jobs report `progress: 0` when finished.** All three succeeded `pretrained_import` jobs have `stage: completed, progress: 0`. They should report 100.
5. **Snapshots never record their training run.** Every snapshot has `training_job_id: null`, although all three jobs reference snapshot `2c2825a1…`. The UI now derives usage from the jobs instead.
6. **One item missing from the embedding index.** `source.items = 57,289` vs `source.indexed_items = 57,288`; the snapshots likewise show 57,288 vs 57,289 products.
7. **Two billing periods.** The subscription runs Sep 12 – Oct 12, while usage counters reset on calendar months (Oct 1 – Nov 1). Pick one source of truth.
8. **Interaction events disappear from usage at the period boundary.** 394,908 events were loaded on Sep 12, and usage now shows 0 for the period. This is expected for a monthly meter, but "new events since last training" is also 0. Confirm that this is intended.
9. **Model storage counts 0 B.** Imported checkpoints don't record `metrics.source.artifact_bytes`, so `artifact_storage_bytes` usage stays 0 while three versions exist.
10. **Three versions from one checkpoint.** v1, v2 and v3 are byte-identical imports of `dgsr_beauty_t4_v2`. Not a bug, but it makes model comparison meaningless; consider deduplicating imports of the same checkpoint.
