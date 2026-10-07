# Changelog

All notable changes to GraphRec. Entries reference the anomaly register in
`docs/GAP_ANALYSIS.md` (A-xx) and the decisions in `docs/DECISIONS.md` (D-xx).

## Unreleased

### Fixed
- A-04: `POST /v1/platform/tenants/{id}/plan` has a typed response (`PlatformPlanAssignmentResult`: the stored quota plus `warnings`); the acceptance test now checks both. Platform quota, recovery and status responses are typed in OpenAPI.
