"""Permission scopes.

Tenant users receive scopes from their role; API keys receive the scopes chosen
when the key is created, limited to what the creating user may delegate
(``graphrec_core/api_keys/scopes.py`` and ``graphrec_core/auth/service.py``).
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, Tuple

__all__ = [
    "API_KEY_SCOPES",
    "CATALOG_SYNC_KEY_SCOPES",
    "DELEGATABLE_SCOPES",
    "ROLE_SCOPES",
    "STOREFRONT_KEY_SCOPES",
    "Scope",
]


class Scope(str, Enum):
    BILLING_READ = "billing:read"
    USAGE_READ = "usage:read"
    CATALOG_READ = "catalog:read"
    CATALOG_WRITE = "catalog:write"
    EVENTS_READ = "events:read"
    EVENTS_WRITE = "events:write"
    TRAINING_READ = "training:read"
    TRAINING_WRITE = "training:write"
    MODELS_READ = "models:read"
    MODELS_WRITE = "models:write"
    MODELS_DEPLOY = "models:deploy"
    RECOMMENDATIONS_READ = "recommendations:read"
    DEPLOYMENTS_READ = "deployments:read"
    METRICS_READ = "metrics:read"
    #: Bearer-token only - API keys can never manage API keys.
    KEYS_WRITE = "keys:write"

    def __str__(self) -> str:
        return str(self.value)


#: Every scope an API key may carry.
API_KEY_SCOPES: FrozenSet[str] = frozenset(s.value for s in Scope if s is not Scope.KEYS_WRITE)

#: Scopes a console user's access token carries. Tokens keep the scopes granted
#: at login, so sign in again after the server changes them.
ROLE_SCOPES: Dict[str, FrozenSet[str]] = {
    "tenant_administrator": frozenset(s.value for s in Scope),
    "tenant_developer": frozenset(
        {
            "keys:write",
            "catalog:read",
            "catalog:write",
            "events:read",
            "events:write",
            "training:read",
        }
    ),
}

#: Scopes each role may grant to the API keys it creates.
DELEGATABLE_SCOPES: Dict[str, FrozenSet[str]] = {
    "tenant_administrator": API_KEY_SCOPES,
    "tenant_developer": frozenset({"catalog:read", "catalog:write", "events:read", "events:write"}),
}

#: A storefront backend: sync catalog, send events/feedback, fetch recommendations.
#: ``recommendations:read`` can only be delegated by a tenant administrator.
STOREFRONT_KEY_SCOPES: Tuple[Scope, ...] = (
    Scope.CATALOG_READ,
    Scope.CATALOG_WRITE,
    Scope.EVENTS_READ,
    Scope.EVENTS_WRITE,
    Scope.RECOMMENDATIONS_READ,
)

#: A catalog export job (PIM/ERP -> GraphRec).
CATALOG_SYNC_KEY_SCOPES: Tuple[Scope, ...] = (Scope.CATALOG_READ, Scope.CATALOG_WRITE)
