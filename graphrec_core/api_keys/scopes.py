from __future__ import annotations

API_KEY_COMPATIBLE_SCOPES = frozenset(
    {
        "billing:read",
        "usage:read",
        "catalog:read",
        "catalog:write",
        "events:read",
        "events:write",
        "training:read",
        "training:write",
        "models:read",
        "models:write",
        "models:deploy",
        "recommendations:read",
        "deployments:read",
        "metrics:read",
    }
)

ADMIN_DELEGATED_SCOPES = API_KEY_COMPATIBLE_SCOPES
DEVELOPER_DELEGATED_SCOPES = frozenset(
    {"catalog:read", "catalog:write", "events:read", "events:write"}
)
