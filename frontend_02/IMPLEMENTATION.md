# GraphRec frontend implementation report

September 19, 2026. Scope: the existing GraphRec console in `frontend_02`, including public, tenant and platform experiences. The separate demo storefront was not redesigned. Existing backend, SDK and other uncommitted work was preserved.

The prior route inventory, API map, screenshot evidence and severity-ranked findings are in [AUDIT.md](AUDIT.md). This work improves the complete console rather than reproducing the supplied example. It does **not** certify the backend or overall platform as production-ready.

## A. Architecture changes

- Retained React 19, TypeScript, React Router 7 and Vite. No new runtime dependency or framework migration.
- `useResource` now binds data and completions to session identity and query dependencies. Changing identity immediately masks old data; late responses cannot overwrite a newer resource or a confirmed local mutation.
- The request client deduplicates concurrent identical GETs within an authentication identity. It does not keep a persistent response cache. Successful mutations emit targeted invalidation events.
- Session-owned layouts remount on account replacement. Product, model and platform tenant details remount when their route identity changes, resetting drafts and dialogs.
- `useQueryState` and `useClearQuery` provide shareable filters/tabs and atomic multi-filter clearing. Unrelated query parameters remain intact.

## B. UX changes

- Navigation follows the actual lifecycle: Overview, Data, Models, Operations, Developer. Account and sign-out remain in the account footer.
- Overview now presents real catalog/model/job/serving state and a relevant next action. Failed reads are reported as failures rather than missing setup.
- Catalog has bounded 50-row API pagination, explicitly labelled search within the current page, and a separate full-catalog exact-ID lookup.
- Usage has one table and one consistent warning summary; subscription detail is expandable.
- Model controls reflect applicable lifecycle actions. Activation, rollback, archive, credential changes and platform changes wait for backend confirmation.
- Dataset import format details are collapsed until needed. Recovery explains the supported operator-assisted process.
- Training distinguishes importing a trained checkpoint from explicitly requesting a development placeholder. Read failures and unknown quota state block unsupported confidence claims.

## C. Design-system changes

- Shared light/dark tokens for surfaces, text, borders, semantic states, spacing, modest radii and focus.
- System typography removes the external font dependency. Readable dates include month names and timezone information.
- One main page surface, ruled sections, compact definition rows and horizontally scrollable tables replace nested card grids.
- Status colour is accompanied by text. Removed decorative update pulses and excess section kickers; reduced-motion preferences are respected.
- Improved link and muted-text contrast; common form/button dimensions and consistent spacing.

## D. Pages redesigned or refined

| Area | Screens |
| --- | --- |
| Public | Sign in, registration, setup/invitation, recovery, platform sign-in, forbidden, not found, unexpected error; preserved aliases and recovery fragments |
| Tenant | Overview, account, integration, credentials, products, add/edit product, catalog synchronization, event submission, submission detail, datasets, training list/detail, model list/detail, usage, service status |
| Platform | Status, tenant list/detail, plan list/detail, failures and audit |

All 17 tenant and six platform page routes were included. Public routes, aliases and error paths are enumerated in the audit. Shared improvements apply to every form, table, dialog and page frame using these primitives.

## E. Components removed

- Navigation-card grid and locally persisted onboarding checklist.
- Independent operational sidebar badges and their redundant fetching.
- Duplicate usage/model/platform KPI summaries and repeated metadata cards.
- Unsupported job cancellation control and reason inputs that the API never persisted.
- Duplicate model version/status metadata already present in the detail heading.

## F. Components created/refactored

- Shared modal foundation for confirmations and one-time secrets.
- `Form`/`Field` accessibility and pending-submit handling.
- `Page`, breadcrumb navigation, document titles, session shells and mobile navigation.
- `DataTable`, `PanelTable`, `DefinitionList`, `ErrorBanner`, `Meter` and keyboard tabs.
- `quotaState`, query helpers, session tenant-ID display, clipboard feedback and resource lifecycle handling.

## G. Mock/hardcoded production values removed

No fabricated production analytics or notification counts were discovered. The problems were misleading defaults and inference: failed reads shown as zero/empty, inconsistent quota summaries, readiness before data loaded, an invented error occurrence time, and successful clipboard feedback before the copy succeeded. Those were corrected.

API examples remain clearly labelled examples. Unit fixtures remain isolated to tests. Live browser tests create explicitly named test tenants and real API records. Placeholder training is a real backend behavior, now disclosed; it is not relabelled as a trained model.

## H. Backend integration improvements

- Preserved existing endpoints, scopes, URLs, token realms and mutation contracts.
- Late 401 responses expire only the session that issued them. Successful responses from a replaced account are also rejected before exposing their result.
- Reject unreadable successful HTTP responses instead of treating proxy HTML as valid data.
- Auxiliary reads obey session permissions, including model/job/credential/metrics relationships.
- Confirmed API payloads update local collections; related reads refresh where needed. Request correlation references remain available in errors.
- Registration retries retain an idempotency key for the same payload; changed registration input gets a new key.
- Usage remains the backend ledger reading; the UI does not overwrite it with unrelated catalog or registry totals.

## I. State-consistency fixes

- One quota calculation handles null limits, zero limits, the 80% warning threshold, exact exhaustion and over-limit use. Summary, row, meter and training eligibility agree.
- Initial loading, successful empty, failed read, stale data with refresh error, and confirmed success are distinct.
- No-data traffic windows show unavailable rates/latency rather than implied successful zero measurements.
- Active model selection is described separately from measured request traffic and infrastructure health.
- Pending dialogs cannot be dismissed or submitted twice. One-time secrets require explicit acknowledgement.
- Filters clear in one URL navigation; changing resources cannot retain another resource's draft or quota override result.
- Polling runs only for active jobs and pauses in hidden tabs.

## J. Responsive fixes

- Mobile navigation collapses behind a labelled toggle, then closes on navigation.
- Forms, definition rows, actions and operational summaries reflow; long identifiers wrap locally.
- Tables preserve useful column widths and scroll inside named regions, with mobile scrolling hints. Technical reference tables no longer crush identifiers into single-character columns.
- Dialogs fit the viewport and scroll vertically. Code blocks scroll within their own containers.
- Browser coverage includes 1440px desktop and 390px mobile for every page, plus representative 1024px, 768px and 320px views, dark/light themes and a mobile credential dialog.

## K. Accessibility fixes

- Skip link, labelled navigation, active-page semantics and route focus management.
- Associated field labels/hints/errors, invalid-state attributes and focus on validation errors.
- Dialog naming, focus containment/restoration, inert background and pending-operation announcements.
- Arrow/Home/End keyboard support for tabs, scoped table headings and keyboard-focusable scrolling regions.
- Visible focus outlines, reduced motion, textual status descriptions and accurate clipboard failure feedback.
- This is implementation and Chromium keyboard/DOM coverage, not a formal WCAG certification or a complete screen-reader audit.

## L. Performance improvements

- Concurrent GET deduplication and removal of global sidebar service reads reduce redundant requests.
- 50-row catalog pages bound DOM size and network payloads rather than accumulating 500-row batches.
- No remote font request, new visualization library or new application dependency.
- Hidden-tab polling is suppressed and timers/listeners clean up on unmount.
- Current production output is approximately 110 KB gzipped JavaScript and 5.7 KB gzipped CSS. No comparative performance benchmark is claimed.

## M. Tests added/updated

- Quota boundary cases and rendering consistency, including zero and informational limits.
- Late dependency/session responses, mutation overwrite protection, concurrent read deduplication and obsolete authentication failures.
- Pending, failed and blocked training; scope-limited job inspection; failed collections versus empty states.
- Activation remains unconfirmed until the response; catalog pagination failure and multi-filter clearing.
- Dialog focus/locking, input associations and rejected clipboard writes.
- Live registration/setup/login, credential creation/rotation/revocation, catalog sync/edit/disable, single/duplicate/batch events, dataset upload/snapshot, training, activation, actual serving metrics, usage/account/overview, authentication gates, platform quota/status/audit.
- A separate live lifecycle case covers replacing an active model, rollback to the retired version and archiving the replaced version, checking backend state after each operation.
- Screenshot/route sweep checks page errors and document overflow across 97 route/viewport combinations plus mobile navigation/dialog interactions. Capture waits for reads, disables screenshot animations and respects credential endpoint throttling.

## N. Remaining backend limitations

1. Default training creates synthetic embeddings and a placeholder success. A real trained DGSR checkpoint can be imported, but the deployment has no training worker, asynchronous progress or cancellation contract. An actual trained checkpoint import was not exercised because no compatible artifact was supplied for this audit.
2. Deployment status reports an active registry row, not the health of indexing/serving dependencies. Infrastructure health needs a backend contract.
3. Usage instrumentation/reconciliation is incomplete for some dimensions, notably active model versions. Ledger counts must not be equated with current registry totals.
4. Archive excludes a version from this console's activation/rollback choices, but backend `activate_model_version` does not itself enforce that lifecycle restriction. Direct API clients can bypass the UI restriction; backend validation is still required. Index deletion is best effort and can fail after the archive state commits.
5. No refresh-token endpoint, project switch, self-service recovery, dataset deletion, synchronization-history resource, general product full-text search, persisted operator reason, or quota-override GET endpoint.
6. Platform audit/failure reads expose only the latest 50 records. Several other lists are unpaginated at the API level. The frontend cannot invent cursor/history endpoints.
7. Tenant-user endpoints exist, but a new member-management product was not invented as part of redesigning the existing routes.

## O. Remaining technical debt

- Add backend lifecycle enforcement, real training orchestration, reliable ledger instrumentation and observable serving health before declaring the platform production-ready.
- Cross-browser, assistive-technology, production-scale load, security and trained-model quality validation remain separate work. Browser automation here uses Chromium.
- Runtime response schemas, network cancellation/timeouts and resumable operations would strengthen resilience. Current hooks suppress obsolete results but do not cancel every request in transit.
- Filtered full-catalog search and pagination for remaining growing collections require backend support. Current UI accurately states its limits.
- The repository has no configured frontend lint command. There is no claim that lint passed.
- Test runs create isolated tenants and records in the local stack. No broad cleanup of existing tenant data was performed. Failure traces can contain test credentials; do not publish them.

## P. Verification commands

Run in `frontend_02` with the existing local API stack available on port 8010:

```powershell
npm run dev -- --host 127.0.0.1
npx vitest run
npm run build
$env:E2E_BASE_URL='http://127.0.0.1:5173'
npx playwright test
git diff --check -- .
```

Vite proxies `/v1` to the local API. The old Docker-served frontend on 5180 is separate; the redesigned source preview is on 5173. Nothing was deployed publicly.

## Q. Build/test status

Final verification: **52 unit tests passed in nine files; all 14 live Chromium tests passed (1.8 minutes); production TypeScript/Vite build passed; `git diff --check` passed** using the repository's normal Windows line-ending configuration. The route audit records **97 observations, zero document overflows and zero browser page errors**. See `e2e-screens/after/routes.json`; screenshots are local generated evidence and are ignored by Git. Final bundle: 359.84 KB JavaScript / 110.45 KB gzip, 23.55 KB CSS / 5.65 KB gzip.

Earlier verification exposed a real multi-filter clearing bug, which was fixed with an atomic URL update and regression coverage. Test assertions were also updated for intentionally hidden inapplicable model actions and the actual `active_model_version_id` deployment field. The final run above includes those corrections.

## SRS integration follow-up — September 20, 2026

The current source is rebuilt and served on port 5180. Subsequent changes add team invitations, actual queued DGSR training, progress/cancellation, compact quality comparison, quota/plan controls, and persistent feedback. Verification: 52 component tests, 16 live browser tests, production build, and 87 backend integration/real-artifact tests passed. See [SRS_ACCEPTANCE.md](../SRS_ACCEPTANCE.md) for scope and remaining gaps.
