# Changelog

All notable changes to GraphRec. Entries reference the anomaly register in
`docs/GAP_ANALYSIS.md` (A-xx) and the decisions in `docs/DECISIONS.md` (D-xx).

## Unreleased

### Fixed
- A-04: `POST /v1/platform/tenants/{id}/plan` has a typed response (`PlatformPlanAssignmentResult`: the stored quota plus `warnings`); the acceptance test now checks both. Platform quota, recovery and status responses are typed in OpenAPI.
- A-15: every database connection uses `timezone=UTC`, so replayed responses keep identical timestamps whatever the server's TimeZone. Connections also get a statement timeout and configurable pool/connect timeouts (A-22).
- A-16: training-worker integration tests drain foreign queued jobs first, so they no longer depend on test order or leftover data.
- A-04: the Python SDK covers `GET /v1/events` (`events.list`) and `AuthTokenPair.email`; the contract test also checks the new platform response models. `GET /v1/events` declares `event_type` as a query parameter.
