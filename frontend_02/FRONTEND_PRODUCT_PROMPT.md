# Prompt: make the GraphRec frontend a production-ready, appealing SaaS product

> Paste everything below this line into a coding agent running in `graphrec/frontend_02/`. This prompt covers the **frontend only**. Backend work it depends on goes into a list for the backend team (see §9); do not change `apps/`, `graphrec_core/` or `migrations/`.

---

## 0. Outcome

Turn `frontend_02/` from a well-audited operator console into **a complete SaaS web product**. A business should be able to:

1. land on the public site;
2. understand GraphRec and its plans;
3. sign up and activate an account;
4. reach its first live recommendation through guided onboarding;
5. run the product day to day.

The whole experience must look and feel like one deliberate, polished product, and the build must meet the production bar in §6.

**Ground rules**
- **Read before you change.** Read `README.md`, `AUDIT.md`, `UI_AUDIT.md` (Phases 1–4, especially the *Deferred* and *Partially fixed* rows), `IMPLEMENTATION.md`, `design/ROUTES.md`, `LANDING_PAGE_PROMPT.md`, every file in `src/`, and every test in `src/**/*.test.*` and `e2e/`. Bring the app up against the real API (`docker compose up -d --build` at the repo root, then `npm run dev`) and click through every route as both a tenant administrator and a developer, and as a platform operator.
- **Honesty is a feature.** Never show invented data, fake counts, placeholder health or capabilities the API lacks. A failed read is an error state, never "empty" or "0". Keep the audit's rule that unavailable measurements show a status, not a zero.
- **Keep the stack**: React 19, React Router 7, Vite 7, TypeScript, hand-written CSS with tokens. Do not add a UI kit, a CSS framework or a state library. Small, justified additions are allowed: ESLint/Prettier, axe for tests, a self-hosted font, an optional error-reporting SDK behind an env flag. List each one with its reason.
- **Get approval at two points**: after the design direction (§2) and before deleting or renaming any route. Otherwise decide, and log the decision in `docs/FRONTEND_DECISIONS.md`.
- **Work in small commits.** After every commit, `npm run build`, `npm test -- --run` and the Playwright suite must pass.

---

## 1. Phase 1: product and UX audit (deliverable before any code change)

Write `docs/FRONTEND_PRODUCT_AUDIT.md` with:

- **Journey map.** Visitor → sign-up → setup → first recommendation → daily operation → plan limit reached → account and team management → operator workflows. For each step, give the route, what the user is trying to do, the friction you observed, and screenshots at 1440 and 390 px.
- **Gap list against a complete SaaS.** Tick each of these as present / partial / missing:
  - public site;
  - pricing;
  - sign-up;
  - email-based activation;
  - guided onboarding;
  - in-app help and docs;
  - plan and upgrade path;
  - account settings;
  - team management;
  - notifications;
  - status communication;
  - legal pages;
  - error recovery;
  - empty states that teach.
- **Every open item from `UI_AUDIT.md`** (Deferred and Partially fixed) and `AUDIT.md`, each with a plan.
- **Technical findings.** Verify each of these and add any others you find:
  - there is no route-level code splitting (`lazy`/`Suspense` are absent), so the whole console ships in one bundle;
  - there is no React error boundary, and a render error blanks the app;
  - there is no `public/` directory, so no favicon, manifest or OG image;
  - `nginx.conf` has no cache headers for hashed assets, no compression and no security headers;
  - three overlapping CSS layers (`modernist.css` → `console.css` → `system.css`); audit item X-1 says the older passes still need folding in;
  - 15 inline `style={{…}}` usages;
  - no ESLint/Prettier configuration;
  - `VITE_API_BASE_URL` is baked in at build time, so one image cannot serve several environments;
  - tokens live in `sessionStorage` and the API has no refresh endpoint, so users are signed out at 15 minutes with no warning.
- **Bundle size, Lighthouse scores** (Performance, Accessibility, Best Practices, SEO) for `/login`, `/home`, `/products` and `/usage`, and **axe violations** per route. These are the baseline.

Send the user a summary and the top ten issues, then continue.

---

## 2. Phase 2: design direction ("appealing", made concrete)

The current look is clean but generic: system fonts, ink buttons, and a brand orange used almost nowhere. Make GraphRec distinctive and trustworthy without losing the audited clarity.

1. **Write `docs/DESIGN_DIRECTION.md`** proposing a direction built on what the product is: *a time-aware user–item graph*.
   - **Brand motif.** The existing `BrandMark` and `GraphIllustration` (nodes, edges, one hot path in the accent colour). Use it in the marketing hero, auth panel, empty states, onboarding and loading moments. Never use it as data decoration on operational screens.
   - **Typography.** One self-hosted variable sans for UI and headings (woff2 in `public/fonts`, `font-display: swap`, latin subset, preloaded) and one mono for IDs and code. No third-party font CDN; the audit removed it for privacy and reliability. Define a clear type scale, using the existing `--text-*` tokens as a starting point.
   - **Colour.** Keep the semantic rules in `system.css`: red = error, amber = warning, green = success, blue = interaction, neutral = information. Give the brand accent a deliberate role: marketing, onboarding progress, the focus ring, illustrations and the selected nav indicator. Body links stay blue and primary buttons stay ink. Light and dark themes must reach parity, with every token defined in both and contrast verified.
   - **Surfaces and density.** Calm sections over nested cards (the audit's no-card-in-card rule). Comfortable density on overview pages and compact density in tables. Give each table a sticky header and visible row focus.
   - **Motion.** Purposeful only: route transitions under 200 ms, a skeleton → content cross-fade, the onboarding progress fill, and an optional graph "draw" in the hero. Everything respects `prefers-reduced-motion`.
   - **Voice.** Plain, specific and calm, in sentence case, with no hype and no exclamation marks. Error messages say what happened and what to do next.
2. **Before/after mock-ups** for four screens: landing hero, Overview (`/home`), Products and Model version detail. Build them as real pages behind a `?preview=design` flag or in a scratch branch.
3. **Stop and ask the user to approve the direction.** After approval, implement it as tokens first, then components, then pages.

---

## 3. Phase 3: foundation refactor

- **One design system.** Merge `modernist.css`, `console.css` and `system.css` into a layered structure: `tokens.css` (primitives plus semantic tokens for both themes), `base.css`, `components.css`, `layouts.css`, and per-area files (`marketing.css`, `console.css`, `auth.css`). Use CSS `@layer` to make the ordering explicit. Delete dead selectors (verify with a coverage run). Replace the 15 inline styles with classes.
- **Component inventory** in `src/ui/`. Each component is accessible, themed and documented in a living style guide at `/__styleguide` (development builds only). The set:
  - Button, IconButton, Link;
  - Input, Select, Textarea, Checkbox, Radio, Switch, Field with error association, Form with dirty tracking (fixes PD-4/X-12);
  - Dialog, ConfirmDialog, Drawer;
  - Toast, Banner;
  - Tabs, Menu (⋯), Tooltip;
  - Table with sticky header, mobile card mode (finishes X-10), sorting where the API allows, and a pagination control with jump-to-page (PR-7);
  - EmptyState, Skeleton, ErrorState;
  - Badge/Tag, Meter, StatCard, DefinitionList, CodeBlock with copy, StageRail, Breadcrumbs, CopyField and IdChip (finishes X-6).
- **Icons.** One small inline-SVG icon set in `src/ui/icons.tsx`: Lucide-style, 1.75 stroke, `currentColor`, `aria-hidden`. No icon package.
- **Tooling.**
  - ESLint (typescript-eslint, react-hooks, jsx-a11y) and Prettier.
  - `npm run lint` and `npm run typecheck` scripts.
  - Strict TypeScript, with no `any` in new code.

---

## 4. Phase 4: complete the product surface

**Public site.** Implement `LANDING_PAGE_PROMPT.md` in full: `/` landing, `/pricing`, marketing header and footer, and auth pages synced with the site. Add:

- **`/docs`**: a public, static developer guide built from the content in `IntegrationPage.tsx` and `sdks/python/README.md`. Sections: quickstart, authentication and API keys, catalog sync, events, recommendations and feedback, errors, limits, SDK. Give it a sidebar table of contents, anchor links and copyable code blocks. This also closes IN-1/IN-2. Inside the console, `/integration` links to the relevant sections and shows the tenant's live credential state.
- **`/privacy` and `/terms`**: ask the user for the text. Until they provide it, ship clearly marked placeholder pages that say "Draft – not yet published" and keep them out of the sitemap. Never invent legal text.

**Sign-up and activation.**
- Polish `/register` → `/setup`. Add a password-strength hint, show/hide password, caps-lock warning, success transitions, and clear copy about the one-time setup link.
- When the backend sends emails (§9), switch the copy to "Check your inbox". Until then, keep the on-screen link flow.

**Guided onboarding (the most important new feature).** A first-run setup at `/home` for new tenants:
- **Progress is computed from real reads**, never from local flags. The audit removed a localStorage checklist for exactly this reason.
- **Steps:**
  1. Create an API key.
  2. Add products (manual, CSV/JSON upload, or "load sample catalog" if the API supports it; otherwise omit that option).
  3. Send events.
  4. Take a snapshot and train.
  5. Review quality and activate.
  6. Try a recommendation. Reuse `TryRecommendation` from `HomePage.tsx`.
  7. Integrate. Show the SDK snippet, prefilled with the tenant's base URL.
- **Each step has** a short explanation, the one primary action, the next step, and links to `/docs`.
- **Progress widget.** A compact progress indicator in the sidebar until every step is done, then it disappears. Role-aware: developers see the integration steps, administrators see training and activation.

**Daily operation.** Overview becomes a real dashboard:
- health summary;
- key metrics with sparklines from `GET /v1/usage/trends` and `/v1/metrics/summary`;
- the active model and its quality;
- quota headroom;
- the next recommended action.

Build charts as small hand-written SVG components following the existing token colours: line and bar, with axis labels, accessible data tables, and support for both themes. Finish every Deferred or Partially fixed `UI_AUDIT.md` item that does not need the backend, and list the rest in §9.

**Plan and billing (no payments).**
- A `/settings/plan` page showing the current plan, limits, usage against limits and reset period, with the plan comparison from `/pricing`.
- "Request an upgrade" opens a dialog explaining that a platform operator assigns plans, plus a contact action configured by `VITE_SALES_CONTACT` and hidden if unset.
- In-app quota banners at 80% and 100% link here.

**Settings.** Consolidate into `/settings` with tabs:
- Profile: the session record. Password change only if the API supports it.
- Team: `/users`, finishing TM-1/TM-2 where the API allows.
- API keys: move from `/credentials` and keep a redirect.
- Plan & usage.
- Appearance: theme.

Keep every old URL working with redirects, and update the nav.

**Session experience.**
- Warn two minutes before the access token expires, with "Stay signed in" (when a refresh endpoint exists) or "Sign in again" that preserves the return path.
- Show an offline banner when `navigator.onLine` is false or API calls fail with network errors.
- Keep a single, consistent toast system.

**Command palette (⌘K / Ctrl+K).** Navigate to any permitted route and jump to a product, model version or training job by exact ID. Scope-aware.

**Operator console (`/admin/*`).** Apply the same design system. Add plan assignment and plan edit UI if the endpoints exist (`PUT /v1/platform/plans/{id}`, plan-assignment migration `0018`); verify them first. Give the audit list pagination and URL-persisted filters.

**Errors and empty states.**
- A top-level error boundary plus one per route, showing a friendly page with a correlation reference and "Reload".
- Each empty state teaches the next step with one action, and the brand illustration where appropriate.
- 404 and 403 pages match the marketing look when the visitor is signed out.

---

## 5. Phase 5: content and SEO

- Write all microcopy in one voice (§2). Add `src/copy/` for shared strings, so that copy is centralised and ready for i18n later. Do not add an i18n library yet.
- Per-route `document.title` and meta description. Public pages get Open Graph and Twitter tags, a generated `og.png` (1200×630, brand motif, no fake data), `favicon.svg`, `apple-touch-icon.png`, `site.webmanifest`, `robots.txt` (disallow console and admin paths) and `sitemap.xml` (public routes only).
- Console routes send `<meta name="robots" content="noindex">`.

---

## 6. Phase 6: production bar (the definition of "production-ready")

**Performance**
- Route-level code splitting with `React.lazy` + `Suspense`. Marketing, console and admin become separate chunks, and the landing page must not download console code.
- Budgets enforced in CI: landing ≤ 90 KB JS gzip, console shell ≤ 180 KB, Lighthouse Performance ≥ 90 on mid-tier mobile for `/` and `/home`, LCP < 2.5 s, CLS < 0.1, INP < 200 ms.
- Self-hosted font subset and preloaded. No layout shift.
- Prefetch the likely next route on hover or focus.

**Accessibility**
- WCAG 2.2 AA. Run axe in Playwright on every route in both themes with zero serious or critical violations.
- Full keyboard paths for every journey in §1. Focus is managed on route change and in dialogs.
- Visible focus, target size ≥ 24 px, and no information conveyed by colour alone.

**Security**
- nginx security headers: a strict CSP (`default-src 'self'`, no `unsafe-inline` for scripts; move the theme pre-paint script to a hashed inline script or an external file), HSTS (when served over TLS), `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `frame-ancestors 'none'` and `Permissions-Policy`.
- Never log tokens or secrets.
- Keep one-time secrets masked in screenshots and out of the DOM after dismissal.
- Keep the safe return-path validation in `LoginPage` and `AdminLoginPage`.

**Delivery**
- **nginx caching:** hashed `/assets/*` → `Cache-Control: public, max-age=31536000, immutable`; `index.html` → `no-cache`.
- **Compression:** gzip (and brotli if the image supports it).
- **SPA fallback:** keep it, but return a real 404 status for unknown static files.
- **Runtime configuration:** serve `/config.json`, generated from environment variables at container start (API base URL, sales contact, error-reporting DSN, environment name), so one image works in every environment. Keep build-time `VITE_*` only as a development fallback.
- **Docker image:** the Dockerfile runs nginx as non-root, ships no source maps publicly (upload them to the error reporter if one is configured), and has a healthcheck.

**Reliability and observability**
- An optional error-reporting adapter: Sentry-compatible, loaded only when a DSN is configured, with PII scrubbing.
- Web-vitals reporting to the same adapter.
- A `/version` value from the build: git SHA and version, shown in the console footer and the error page.

**Quality gates (CI-ready scripts)**
- `lint`, `typecheck`, `test` (vitest; coverage ≥ 80% on `src/ui`, `src/lib` and `src/api`), `e2e` (Playwright), `e2e:a11y` (axe), `e2e:visual` (screenshot comparison for the key screens at 1440 and 390 px in both themes) and `size` (bundle budgets).
- Supported browsers: last 2 versions of Chrome, Edge, Firefox and Safari, plus iOS Safari 16+. Test at 320, 390, 768, 1024, 1440 and 1920 px with no horizontal page scroll.

---

## 7. Tests to keep green and extend

- Every existing vitest and Playwright test keeps passing. Update assertions only where a behaviour change was intended, and say so in the commit.
- New coverage:
  - landing and pricing render and are session-aware;
  - onboarding progress derives from API reads (mocked fetch), including the failed-read state, which must not count as "not done";
  - settings redirects from old URLs;
  - session expiry warning;
  - the command palette respects scopes;
  - error boundary fallback;
  - quota banners at 80% and 100%;
  - every chart has an accessible data table.
- Playwright journeys:
  - visitor → register → setup → onboarding to a first recommendation, against the real stack;
  - developer-role journey;
  - operator journey;
  - mobile journey at 390 px.

---

## 8. Phase 7: verification and handover

1. Run every gate in §6 and record the numbers against the Phase 1 baseline in `docs/FRONTEND_PRODUCT_AUDIT.md`, as a before/after table.
2. Capture after-screenshots for every route at 1440 and 390 px in both themes into `docs/ui-audit/after-product/`.
3. Walk the journey map with fresh eyes, or with a separate review agent that did not build it, and fix what it finds.
4. Update `README.md`: route map, architecture, scripts, runtime configuration and deployment.

**Final report to the user:**
- what changed;
- the before/after metrics;
- the decisions you made;
- what still depends on the backend (§9);
- any open questions, such as legal text, the sales contact or the font licence.

---

## 9. Backend dependency list (write it, don't build it)

Maintain `docs/BACKEND_REQUESTS.md` for everything the frontend needs from the API. Each entry gives the endpoint shape, why it's needed and the UI that waits on it. Expected entries (verify each one):

- token refresh endpoint;
- transactional email for setup, invite and recovery;
- password change for signed-in users;
- full-catalog text search and server-side sort (PR-1/PR-5);
- sync dry-run validation (SY-1);
- a sample-catalog loader for onboarding;
- per-user management actions (role change, lock/unlock, resend invite);
- tenant-scoped audit read;
- a public plans endpoint, so `/pricing` stops mirroring migrations;
- pagination on platform audit and failures;
- `artifact_bytes` for imported checkpoints (US-5);
- consistent usage periods (US-2).

Where the API lacks something, the UI shows an honest limitation instead of a fake control.

---

## Definition of done

- [ ] Design direction approved, implemented through tokens, and parity verified in light and dark.
- [ ] Public site, pricing, docs, sign-up, onboarding, dashboard, settings, plan page, operator console and error pages are complete and visually consistent.
- [ ] A new tenant reaches a first recommendation through onboarding with no outside help.
- [ ] Every Deferred and Partial `UI_AUDIT.md` item is fixed, or listed in `BACKEND_REQUESTS.md` with a reason.
- [ ] Performance, accessibility, security, delivery and observability gates in §6 pass and are scripted for CI.
- [ ] Every test suite is green, including the new journeys, axe and visual checks.
- [ ] No fake data, no dead links, and no control without a backing endpoint.
- [ ] The README and docs match the shipped product.
