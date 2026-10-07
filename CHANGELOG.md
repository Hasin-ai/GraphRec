# Changelog

All notable changes to GraphRec. Entries reference the anomaly register in
`docs/GAP_ANALYSIS.md` (A-xx) and the decisions in `docs/DECISIONS.md` (D-xx).

## Unreleased

### Fixed
- A-04: `POST /v1/platform/tenants/{id}/plan` has a typed response (`PlatformPlanAssignmentResult`: the stored quota plus `warnings`); the acceptance test now checks both. Platform quota, recovery and status responses are typed in OpenAPI.
- A-15: every database connection uses `timezone=UTC`, so replayed responses keep identical timestamps whatever the server's TimeZone. Connections also get a statement timeout and configurable pool/connect timeouts (A-22).
- A-16: training-worker integration tests drain foreign queued jobs first, so they no longer depend on test order or leftover data.
- A-04: the Python SDK covers `GET /v1/events` (`events.list`) and `AuthTokenPair.email`; the contract test also checks the new platform response models. `GET /v1/events` declares `event_type` as a query parameter.
- A-03: unexpected server errors return the standard error envelope (`internal_error`, retryable) with a correlation id instead of a plain-text 500; the console shows that reference.
- A-23: `405` is reported as `method_not_allowed` instead of `400 malformed_request`.
- A-10: new `GRAPHREC_ENV` (`development` | `production`). In production the API, worker and scheduler refuse to start with default, placeholder or short secrets, a development database password, or no Redis.
- A-24: one product version (`VERSION`, now 1.1.0) shared by the API, the console build and the Python SDK. Public `GET /v1/meta` reports version, environment and development features; the console sidebar shows the version.
