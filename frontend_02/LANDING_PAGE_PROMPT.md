# Prompt: build the GraphRec public landing page and sync the console with it

> Paste everything below this line into a coding agent that is running in `graphrec/frontend_02/`.

---

You are working in `frontend_02/`, the GraphRec operator console: **React 19.1 + React Router 7 (`BrowserRouter`) + Vite 7 + TypeScript 5.8**, tested with **Vitest + Testing Library** and **Playwright** (`e2e/`). It has **no UI library, no CSS framework and no icon package**. Styling is three plain stylesheets loaded in this order in `src/main.tsx`: `styles/modernist.css` (tokens and base components), `styles/console.css` (layout and primitives), `styles/system.css` (semantic layer, loaded last). nginx serves `dist/` with an SPA fallback (`try_files … /index.html`) and proxies `/v1/` to the API.

GraphRec is a multi-tenant recommendation platform for e-commerce. Each tenant syncs its product catalog, streams interaction events (view, click, add-to-cart, purchase, rating), takes immutable dataset snapshots, trains its own **DGSR** model (Dynamic Graph Neural Network for Sequential Recommendation, a time-aware user–item graph model), versions, activates, rolls back and archives models, and serves real-time Top-N recommendations for known shoppers and anonymous sessions. It also applies diversity and freshness rules, records impression, click and conversion feedback, and enforces per-plan quotas. Tenant data is isolated with forced PostgreSQL row-level security. API keys are scoped and stored as HMAC verifiers only.

**The problem:** GraphRec has no public marketing page. Today `/` sends signed-out visitors straight to `/login`. The only brand pitch is the dark "showcase" panel on the left of the auth screens (`PublicLayout` in `src/layouts/Layouts.tsx`).

**Your task:** build a public marketing site (a landing page plus a pricing page) and make every existing page consistent with it: navigation, links, brand, copy, theme, metadata and tests. Do **not** add any runtime dependency. Do **not** change the backend.

Read every file named in this prompt before you edit it. Run `npm run build` and `npm test -- --run` before you finish.

---

## 1. What already exists (verified, so you don't have to rediscover it)

### Routing (`src/App.tsx`)
- `Root()` at `/`: a tenant session goes to `/home`, a platform session goes to `/admin/status`, otherwise `/login`.
- `PublicLayout` wraps `/login`, `/register`, `/setup`, `/invite/accept`, `/recover`, `/recover/confirm` (redirects to `/setup`) and `/admin/login`.
- `RequireTenant` → `TenantLayout` wraps `/home`, `/account`, `/users`, `/integration`, `/credentials`, `/products*`, `/events/submit`, `/submissions/:id`, `/datasets`, `/training*`, `/models*`, `/recommendation-rules`, `/usage` and `/service-status`. Most are gated by `RequireScope`.
- `RequirePlatform` → `PlatformLayout` wraps `/admin/status`, `/admin/tenants*`, `/admin/plans*` and `/admin/audit`.
- `ErrorLayout` wraps `/403`, `/404`, `/error` and `*`. It renders inside whichever layout matches the current session.

### Layout pieces in `src/layouts/Layouts.tsx` that the marketing site must reuse
These are private today. Move them into shared modules (see §6) instead of copying them:
- `BrandMark`: a 32×32 SVG logo. Ink square, four graph nodes, one node in `var(--color-accent)`.
- `GraphIllustration`: a decorative user–item graph SVG, styled by `.auth-graph .e/.n/.hot/.halo` in `console.css`.
- `ThemeButton`: toggles light/dark through `useTheme()`, which writes `data-theme` on `<html>` and persists to `localStorage["graphrec.theme"]`. The first visit follows `prefers-color-scheme`.
- The auth showcase copy, which is the de-facto brand voice:
  - Headline: **"Recommendations that learn from every interaction."**
  - Lede: "Sync your catalog, stream events, and serve time-aware graph recommendations from one multi-tenant console."
  - Bullets: "Train and version models on your own event history" · "Promote, roll back and monitor serving deployments" · "Scoped API keys and per-tenant usage quotas"

### Design tokens and rules
The tokens in the code are the source of truth. The Modernist DS readme in `design/_ds/` (Archivo font, 0px radius, red primary buttons) is **not** what ships, so don't follow it.
- **Colour:** `--color-bg`, `--color-surface`, `--color-surface-2/3`, `--color-text`, `--color-border(-strong)` and the `--color-neutral-100…900` ramp. Brand accent `--color-accent` (#c8361b light / #ff6d50 dark) with the `--color-accent-100…900` ramp. Ink solids `--color-ink`, `--color-ink-hover`, `--color-on-ink`. State colours `--ok/--warn/--danger/--info/--neu`, each with `-bg` and `-line`. Every token is redefined under `:root[data-theme="dark"]`.
- **Auth panel tokens:** `--auth-panel`, `--auth-panel-2` and `--color-canvas` (in `console.css`).
- **`system.css` semantic rules you must keep:** red means error, amber means warning, green means success, **blue (`--color-link` = `--info`) means interaction/links**, neutral means information. **The brand orange is reserved for the logo, the focus ring and illustration highlights.** Do not use it for buttons or body links. There is one primary button per view: `.btn-primary` is an ink fill, then `.btn-secondary`, then `.btn-ghost`.
- **Scales:** spacing `--space-1…7` (4/8/12/16/24/32/48). Type `--text-xs…3xl` (12…28). `--content-max: 1200px`, `--prose-max: 70ch`. Radii `--radius-sm/md/lg/pill` and `--radius-card: 12px`. Shadows `--shadow-sm/md/lg`. Focus ring `--ring`.
- **Fonts:** `--font-heading` and `--font-body` are the system-ui stack, `--mono` is the monospace stack. Do not load web fonts.
- **Existing classes to reuse:** `.btn`, `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.btn-sm`, `.tag`, `.mono`, `.muted`, `.row`, `.stack`, `.sr-only`, `.skip-link`, `.snippet` (with `.s-head`, `.s-label` and `CopyButton` from `ui/primitives.tsx`), `.theme-toggle`, `.brand-mark` and `.auth-logo`.
- **Breakpoints in use:** 1100, 960 (the auth showcase hides), 800 (the console sidebar collapses), 640, 600 and 520 px. The Playwright sweep fails any page that scrolls horizontally at 320, 390, 768 or 1024 px.

### Conventions
- Every page sets `document.title` to `"<Title> · GraphRec"`. `ui/Page.tsx` does this for console pages.
- Accessibility already in place: skip link, `#main-content` with `tabIndex={-1}` focused on route change, `aria-current` on nav, and `aria-label` on icon buttons. Inline SVG icons are hand-drawn with `aria-hidden="true"`.
- Sessions live in `sessionStorage` (`auth/session.ts`). `useSession()` exposes `{ tenant, platform }`.

### Product facts to use as marketing content (do not invent others)
- **Core loop:** catalog sync (`POST /v1/products:bulk-upsert`), events (`POST /v1/events`, batches of up to 1,000), dataset snapshots, DGSR training jobs, model versions (activate, roll back, archive), recommendations (`POST /v1/recommendations`, `POST /v1/recommendations/session`), feedback (`/v1/feedback/impressions|clicks|conversions`), usage and quotas, service status (p95 latency, fallback rate, capacity).
- **Recommendation response:** `request_id`, `items[{external_product_id, position}]`, `model_version_id`, `strategy`, `fallback_used`, `fallback_tier`, `applied_rules`, `rules_version`. Every result carries its provenance.
- **Cold start:** an unknown shopper or an anonymous session is encoded as a "virtual root" through the saved graph and labelled `session`. A fallback tier is used when no model is active.
- **Recommendation rules:** category diversity (max per category) and freshness boost (weight and half-life).
- **Retraining policy panel:** scheduled or threshold-based retraining.
- **Security:** row-level-security tenant isolation, scoped API keys (`catalog:*`, `events:*`, `training:*`, `models:*`, `usage:read`, `deployments:read`, `keys:write`, `users:write`), rotation with grace period, revocation, one-time secrets, and non-disclosing errors with `correlation_id`.
- **Roles:** Tenant Administrator and Tenant Developer, plus a separate Platform Operator realm.
- **Python SDK** (`sdks/python`, package `graphrec-sdk`): sync and async clients, `CatalogSync`, a buffered `EventTracker`, and `RecommendationSession` for impressions, clicks and conversions. Retries never duplicate side effects. The SDK auto-splits bulk calls under the 16 KiB body limit. Quickstart:
  ```python
  from graphrec_sdk import GraphRec
  from graphrec_sdk.ecommerce import CatalogSync, EventTracker
  client = GraphRec(base_url="https://graphrec.example.com", api_key="gr_live_...")
  CatalogSync(client).run([{"external_id": "sku-100", "title": "Linen shirt", "price": "49.90", "category": "shirts"}])
  with EventTracker(client, batch_size=100, flush_interval=5) as tracker:
      tracker.view("customer-42", "sku-100", session_id="sess-1")
      tracker.purchase("customer-42", "sku-100", order_id="ORD-1001")
  recs = client.storefront.recommendations.get(user_id="customer-42", top_n=10)
  ```
  Before you publish this snippet, confirm the exact recommendation method name in `sdks/python/src` and `sdks/python/README.md`, and fix the last line if it differs.
- **Raw HTTP example.** The API-key header format comes from `pages/tenant/IntegrationPage.tsx`:
  ```http
  POST /v1/recommendations
  Authorization: ApiKey <credential secret>
  { "user_id": "cus-9931", "top_n": 10, "fallback_allowed": true, "context": { "surface": "cart" } }
  ```
- **Demo storefront:** `apps/demo-storefront` ("Facet", a beauty shop) consumes GraphRec through the SDK and shows each recommendation's provenance. You may mention it as "a reference storefront". Do not link to it, because it has no public URL.

### Plans (there is no public plans endpoint; `GET /v1/platform/plans` needs the operator token)
These are the current seeded limits. Free comes from migrations `0001` and `0031`; Basic and Pro come from `0012`. The SRS table is stale for Free.

| Limit (label from `lib/labels.ts`) | Free | Basic | Pro |
|---|---:|---:|---:|
| Accepted events / month | 50,000 | 500,000 | 2,000,000 |
| Recommendation requests / month | 20,000 | 250,000 | 1,000,000 |
| Requests per minute | 120 | 300 | 1,000 |
| Concurrent recommendation requests | 8 | 12 | 30 |
| Stored products | 5,000 | 50,000 | 500,000 |
| Training jobs / month | 1 | 4 | 12 |
| Concurrent training jobs | 1 | 1 | 2 |
| Max training duration | 30 min | 60 min | 180 min |
| Active model versions | 2 | 5 | 10 |
| Max inference replicas | 1 | 2 | 3 |
| Artifact storage | 1 GiB | 5 GiB | 20 GiB |
| Queued messages | 500 | 5,000 | 50,000 |

**Plans carry no prices, and payments are out of scope.** Every new tenant is put on Free at registration (`registration/service.py`). Only a platform operator can assign Basic or Pro (`/admin/tenants/:id`).

### Honesty constraints (from the SRS, §1.3, ASM-06 and CON-05)
GraphRec is presented as a limited-capacity system, not a production high-availability service. The landing page must **not** include:
- invented customer logos, testimonials, user counts, uptime percentages or "trusted by" strips;
- SLA language or a guaranteed latency. The P95 < 300 ms target is "measured at supported load, not contractual". If you mention it, phrase it like that or leave it out;
- claims of SOC 2, GDPR or other certifications;
- fake prices, "Buy now" or checkout flows, or links to pages that don't exist (blog, careers, docs site, status page).

---

## 2. Routing decisions (implement exactly)

1. **`/` becomes the landing page for signed-out visitors.** A tenant session still redirects to `/home` and a platform session still redirects to `/admin/status`. This keeps the existing vitest "the root resolves by identity" test green. Implement it in `Root()`: render `<LandingPage />` inside the new `MarketingLayout` when there is no session.
2. **Add `/pricing`.** It is always reachable, signed in or not, because tenants check plan limits too.
3. Add a new layout route **`MarketingLayout`** for these marketing pages. It must stay separate from `PublicLayout`, which remains the split-screen auth shell.
4. `*` (the 404) must stay inside `ErrorLayout`. When nobody is signed in, the 404 renders in `PublicLayout` as it does today, and its "back" link now goes to `/`, which is the landing page.
5. Do not add `/features`, `/docs`, `/privacy`, `/terms`, `/contact` or any other route. Features live as sections on `/`.

---

## 3. Information architecture of `/`

Build it as one long page from section components in `src/pages/marketing/`. Give each section an `id` so the header can anchor-link to it (`/#features`, `/#how-it-works`, `/#developers`, `/#security`). Use exactly one `<h1>` and an `<h2>` per section. Write copy in the existing voice: plain, specific, technical and calm. Use no exclamation marks and no hype words ("revolutionary", "AI-powered magic"). Use sentence case in headings, as the console does.

1. **Marketing header** (sticky, `<header>` with `<nav aria-label="Marketing">`)
   - Left: `BrandMark` + "GraphRec", linking to `/`.
   - Centre: links to Features, How it works, Developers, Security and Pricing (`/pricing`).
   - Right: `ThemeButton` (compact), then a **session-aware CTA**:
     - signed out: a "Sign in" ghost button (`/login`) and a "Create a tenant" primary button (`/register`);
     - tenant session: an "Open console" primary button (`/home`);
     - platform session: an "Open platform console" primary button (`/admin/status`).
   - Below 800 px: a hamburger reusing the console's `icon-btn nav-toggle` SVGs and `aria-expanded` pattern. Escape and route changes close it, and a scrim sits behind it. Copy this behaviour from `Shell` in `Layouts.tsx`.
2. **Hero.** Reuse the auth showcase's dark radial panel look (`--auth-panel`, `--auth-panel-2`, the orange glow `::after`), in both themes, at full width.
   - Eyebrow: "Recommendation platform for e-commerce".
   - `h1`: **"Recommendations that learn from every interaction."** This exact string must match the auth panel; see §5.
   - Lede: a slightly expanded version of the auth lede.
   - CTAs: "Create a tenant" (primary, light-on-dark variant) and "See pricing" (secondary).
   - A tertiary text link "Already have an account? Sign in".
   - Visual: an enlarged `GraphIllustration`. Optionally animate the "hot" path with a CSS stroke-dash draw, only under `prefers-reduced-motion: no-preference`.
3. **The problem, in one line.** "Large catalogs bury the right product. Building a recommender per shop means data pipelines, temporal modelling, evaluation, serving, isolation and quotas." Follow it with "GraphRec is that system, shared and isolated per tenant."
4. **Features (`#features`).** A six-card grid (3×2, then 2×3, then 1×6). Each card has a hand-drawn inline SVG icon (Lucide-style, 1.75 stroke, `currentColor`, `aria-hidden`), a title and two sentences:
   - **Time-aware graph models.** DGSR learns from the order and timing of interactions, not just co-occurrence.
   - **Your data, your model.** Every tenant trains on its own snapshots, and versions are immutable.
   - **Safe model lifecycle.** Activate eligible versions, roll back to a retained one, archive the rest.
   - **Cold start handled.** Anonymous sessions and new shoppers get session-aware results, and a fallback tier covers you when no model is active.
   - **Business rules.** Category diversity caps and freshness boosts, applied and reported per response (`applied_rules`).
   - **Observable serving.** p95 latency, fallback rate, capacity, and usage against quota.
5. **How it works (`#how-it-works`).** A numbered five-step rail that echoes the console's stage-rail look:
   1. Sync catalog
   2. Stream events
   3. Snapshot & train
   4. Activate a version
   5. Serve & measure feedback

   Each step names its real endpoint in `.mono` small text. Use an `<ol>`.
6. **Developers (`#developers`).** Two columns: copy on the left, a tabbed code sample on the right.
   - Copy bullets: scoped API keys, idempotent batches with duplicate detection, consistent error envelope with `correlation_id`, Python SDK (sync and async), auto-split bulk calls, retries that never duplicate side effects.
   - Code sample tabs: "Python SDK" | "HTTP request" | "Response". Use the existing `.snippet` styling and `CopyButton`. Make it a real ARIA tablist with arrow-key navigation. The Response tab shows a realistic `RecommendationResult` JSON with `strategy`, `fallback_used: false`, `fallback_tier`, `applied_rules: ["diversity"]` and `model_version_id`, with the caption "Every result says which model and which rules produced it."
7. **Security & isolation (`#security`).** A 2×2 grid:
   - row-level-security tenant isolation, with no tenant id in any URL;
   - scoped, rotatable, revocable API keys stored as HMAC verifiers, with secrets shown once;
   - role-based console (Administrator / Developer) and a separate operator realm;
   - non-disclosing errors and audit trails.
8. **Console preview.** A stylised, *non-interactive* HTML/CSS mock of the Overview page: health rows, four metric tiles, sidebar nav groups. Build it from the real console class names where practical so it inherits theme changes. Mark it `aria-hidden="true"` and put a visible caption under it. **Do not** embed screenshots, because they would go stale and would not theme.
9. **Pricing teaser.** Three compact plan cards (Free / Basic / Pro) showing three headline limits each, linking to `/pricing`.
10. **Final CTA band.** "Start on the Free plan." Button: Create a tenant. Secondary link: Sign in.
11. **Marketing footer** (`<footer>`). Brand and one-line description. Link columns:
    - Product: Features, How it works, Pricing.
    - Console: Sign in, Create a tenant, Finish account setup (`/setup`), Reset password (`/recover`).
    - Operators: Platform sign-in (`/admin/login`).

    Also include the `ThemeButton` and "© {current year} GraphRec". There are no social links and no legal links.

---

## 4. `/pricing`

- Put the plan data in **one typed module, `src/marketing/plans.ts`**. It exports `PLANS: MarketingPlan[]` with `code: "free" | "basic" | "pro"`, `name`, `tagline`, `limits: Record<LimitKey, number>` (raw numbers, keys identical to the backend `limits` JSON keys above) and `price: null`. Add a header comment naming the migrations it mirrors (`0001`, `0012`, `0031`) and saying that operators can edit plans at runtime, so these numbers are the seeded defaults.
- Format every number with the existing helpers in `lib/format.ts` (`fmtNumber`, bytes). Take every row label from `lib/labels.ts` so the pricing table uses the same words as `/usage` and `/admin/plans`. If a label is missing there, add it there instead of hard-coding it.
- Layout: three plan cards. **Basic** gets an "Most room to grow"-style neutral `.tag`; do not say "most popular", because that is unverifiable. Under the cards, a full comparison `<table>` with a `<caption>`, `scope="col"` and `scope="row"`, and numeric cells right-aligned in tabular numerals. At narrow widths it scrolls horizontally inside its own wrapper, never the page; reuse the `.table-scroll-hint` pattern.
- Price display: Free shows "Free". Basic and Pro show "Assigned by your platform operator" in place of a price.
- CTAs:
  - Free: "Create a tenant" → `/register`.
  - Basic and Pro: "Start on Free" → `/register`, with the note "Every tenant starts on Free. A platform operator moves you to Basic or Pro."
  - When a tenant is signed in, replace the CTAs with "View your usage" → `/usage`.
- FAQ: four or five `<details>`/`<summary>` items. Cover what counts as an accepted event (duplicates are confirmed, not double-counted), what happens at a quota limit (requests are rejected with a clear error, and `/usage` shows the state), whether limits reset monthly, how to change plans (operator-assigned), and whether there is a payment flow (no).

---

## 5. Sync every existing page with the marketing site

Make each of these changes and keep the existing behaviour intact:

1. **`PublicLayout` (all auth pages).**
   - The `.auth-logo` links to `/`, which is now the landing page. Add a small "← Back to GraphRec" link in `.auth-top` (left side on desktop, next to the mobile logo on narrow screens).
   - Move the showcase headline, lede and bullets into **`src/marketing/copy.ts`** (`BRAND.tagline`, `BRAND.lede`, `BRAND.pillars`), and import them in both `PublicLayout` and the hero so the two can never drift. The mobile pitch line (`.auth-pitch-mobile`) also reads `BRAND.tagline`.
   - Add a "Plans & limits" link to `/pricing` in the showcase foot.
2. **`LoginPage`, `RegisterPage`, `SetupPage`, `RecoverPage` and `AdminLoginPage`.** Leave the forms alone.
   - `RegisterPage`'s footnote gains "New tenants start on the Free plan. <Link to="/pricing">Compare plans</Link>."
   - Check every "Back to sign in" and secondary link still resolves.
3. **Console shells.**
   - In `Shell`, the mobile header's `<Link to="/">` must go to the console home: `/home` for tenants, `/admin/status` for platform. Today it bounces through `Root`; make it explicit.
   - The `TenantLayout` aside foot gains a muted "Plans & limits" link to `/pricing`, next to Account.
   - Do not link to the marketing page from inside the console nav.
4. **Error pages (`ErrorPages.tsx`).** "Back to start" / "Go to Overview" must be session-aware:
   - tenant → "Go to Overview" (`/home`);
   - platform → "Go to Platform Status" (`/admin/status`);
   - signed out → "Go to GraphRec home" (`/`).

   Today they always link `/`, which is wrong now that `/` is the landing page.
5. **`UsagePage`.** Add a small "Compare plans" link to `/pricing` next to the subscription/plan block.
6. **`index.html`.**
   - Set the `<title>` to "GraphRec: Recommendations that learn from every interaction".
   - Rewrite the meta description for the public site.
   - Add `theme-color` (light and dark via `media`), Open Graph and Twitter tags (`og:title`, `og:description`, `og:type=website`; no `og:image` unless you create one in `public/`), and an inline SVG favicon derived from `BrandMark` (`public/favicon.svg`).
   - Add an inline pre-paint script that reads `localStorage["graphrec.theme"]` (wrapped in try/catch) and falls back to `prefers-color-scheme`, then sets `data-theme` on `<html>` before React mounts. This removes the light-to-dark flash that is more visible on a marketing page.
7. **Document titles.** The landing page sets "GraphRec: Recommendations that learn from every interaction". Pricing sets "Pricing · GraphRec". Restore the console's titles on navigation, which `Page` already does.
8. **README.md.** Add `/` (landing) and `/pricing` to the route map and describe `MarketingLayout`.

---

## 6. Code structure

```
src/
  brand/BrandMark.tsx            ← moved out of Layouts.tsx (export BrandMark, GraphIllustration)
  brand/ThemeButton.tsx          ← moved out of Layouts.tsx
  marketing/copy.ts              ← BRAND strings shared by hero and auth showcase
  marketing/plans.ts             ← plan limits (single source on the frontend)
  layouts/MarketingLayout.tsx    ← header + <main id="main-content" tabIndex={-1}> + footer + skip link
  pages/marketing/LandingPage.tsx
  pages/marketing/PricingPage.tsx
  pages/marketing/sections/*.tsx ← Hero, Features, HowItWorks, Developers, Security, ConsolePreview, PricingTeaser, FinalCta
  styles/marketing.css           ← imported in main.tsx AFTER system.css; every rule scoped under .mkt
```

- `Layouts.tsx` must import `BrandMark`, `GraphIllustration` and `ThemeButton` from `brand/`, so there is no duplication.
- **CSS rules:**
  - Every new rule lives in `marketing.css` and is scoped under a `.mkt` root class on `MarketingLayout`, so nothing leaks into the console.
  - Use tokens only, with no new hex values. The one exception is the dark hero panel, which may reuse the literal values the auth showcase already uses; better still, promote them to tokens in `console.css` and use them in both places.
  - Every colour must work in both themes. Check each section with `data-theme="dark"`.
  - Body links use `--color-link`. CTAs use `.btn-primary` / `.btn-secondary`. On the dark hero, add a `.btn-on-dark` variant (white fill, ink text) instead of using orange.
  - Content width is `--content-max`. Section vertical rhythm is `clamp(48px, 8vw, 112px)`. Headings use fluid `clamp()` sizes. Keep body at the console's 14.5–16px range, with an 18px lede.
  - Give each anchored section `scroll-margin-top` equal to the sticky header height. `scroll-behavior: smooth` applies only under `prefers-reduced-motion: no-preference`.
  - Wrap all motion in `@media (prefers-reduced-motion: no-preference)`.
- Keep components small and typed. Do not add any new dependency: no icon libraries, no animation libraries, no CSS frameworks, no web fonts.
- Hash links: `BrowserRouter` does not scroll to `#id` by itself. Add a small effect in `MarketingLayout` that scrolls to `location.hash` after navigation, including from `/pricing` → `/#features`, and otherwise scrolls to the top and focuses `#main-content`, matching the existing pattern.

---

## 7. Accessibility and quality bar

- One `h1` per page. Landmarks: `header`, `nav`, `main`, `footer`. A skip link to `#main-content`.
- Every interactive element is keyboard-reachable with the existing `:focus-visible` ring. Code tabs follow the WAI-ARIA tabs pattern. The mobile menu traps nothing, closes on Escape, and returns focus to its toggle.
- Colour contrast is at least 4.5:1 for body text and at least 3:1 for large text and UI in **both** themes, including grey text on the dark hero.
- Decorative SVGs have `aria-hidden="true"`. The console preview has `aria-hidden` plus a visible text caption.
- No layout shift from fonts or images. No horizontal scroll at 320 px.
- Lighthouse targets on `npm run build && npm run preview`: Accessibility 100, Best Practices ≥ 95, SEO ≥ 95 for `/` and `/pricing`.

---

## 8. Tests to add or update

**Vitest** (`src/**/*.test.tsx`, using `renderAt` from `src/test/render.tsx`):
- `/` signed out renders the landing page: the heading "Recommendations that learn from every interaction." and the "Create a tenant" link to `/register`.
- `/` with a tenant session redirects to `/home`. The existing platform redirect test stays green.
- The marketing header CTA shows "Open console" when a tenant is signed in.
- `/pricing` renders three plans and a comparison table. Its numbers come from `PLANS`; assert "50,000" and "2,000,000". Signed-in tenants see "View your usage".
- The auth showcase and the hero render the same `BRAND.tagline`.
- Error pages link to `/home`, `/admin/status` or `/` depending on the session.
- A unit test that `PLANS` limit keys all have labels in `lib/labels.ts`.

**Playwright:**
- `e2e/console.spec.ts`: the test "public: root redirects to sign-in…" must now assert that `/` shows the landing page, clicks "Create a tenant", lands on `/register`, and continues the existing registration flow unchanged. Rename the test accordingly.
- `e2e/routes.spec.ts`: add `/` and `/pricing` to the public route sweep, so they are screenshotted at desktop and 390 px and checked for horizontal overflow.

`npm run build` (which includes `tsc -b`) and `npm test -- --run` must both pass. Do not weaken or delete existing assertions, except the one root-redirect expectation that this change intentionally replaces.

---

## 9. Acceptance checklist (verify each item before you finish)

- [ ] Signed out, `/` shows the landing page. Signed in, `/` still goes to the right console.
- [ ] `/pricing` works signed out and signed in, and its numbers match §1 exactly.
- [ ] No invented logos, testimonials, metrics, SLAs, certifications or prices.
- [ ] Header, footer and auth screens cross-link correctly, and no link points to a route that doesn't exist.
- [ ] Hero `h1`, auth showcase headline and mobile pitch read from `BRAND.tagline`.
- [ ] `BrandMark`, `GraphIllustration` and `ThemeButton` exist once, in `src/brand/`.
- [ ] Theme toggle works on every marketing section with no flash on load, and dark mode is visually checked.
- [ ] Orange appears only in the logo, focus ring and illustrations. Links are blue and the primary CTA is ink (white-on-dark in the hero).
- [ ] No horizontal scroll at 320, 390, 768, 1024 or 1440 px, and the mobile menu works.
- [ ] All motion respects `prefers-reduced-motion`.
- [ ] Console pages look and behave exactly as before, apart from the links listed in §5.
- [ ] `npm run build` and `npm test -- --run` pass, and the Playwright specs are updated.
- [ ] README route map updated.

When you're done, reply with:
- a short summary of the files you added and changed;
- any SDK method name you had to correct in the snippet;
- anything in this prompt you could not satisfy, and why.
