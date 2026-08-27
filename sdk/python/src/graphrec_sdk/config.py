"""Where the two hosts come from, and why there are two.

GraphRec publishes two ports (`BACKEND_PLAN` §9.1): N1 answers the control plane
on one hostname shared by every tenant, and N3 answers the data plane on a
hostname **per tenant**. N3's edge resolves the upstream from the subdomain —
``graphrec-serve-{http.request.host.labels.3}-inference``, `deploy/n3/Caddyfile`
— and the label it reads is the tenant's UUID in hex without dashes, the same
value `graphrec/serving_driver/compose.py` uses as its Compose project name.

So a single `base_url` is not merely inelegant, it is wrong, and wrong in the
quietest way available: ``POST https://api.example/v1/recommendations`` is a 404
with nothing in the body to explain it, because that route does not exist on
that application. Nothing in this SDK's surface lets a caller choose a host —
each namespace is bound to one at construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .credential import Credential
from .errors import ConfigurationError

#: Kept in one place so the `User-Agent` and the package cannot disagree.
VERSION = "0.1.0"

_UUID = re.compile(
    r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$",
    re.IGNORECASE,
)

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_RETRIES = 2


def normalise_tenant_id(raw: str) -> str:
    """A tenant id in the form the data-plane hostname needs.

    The console shows the dashed UUID and the hostname takes the hex. A customer
    copying from one into the other gets a host that does not resolve and an
    error from their DNS resolver rather than from us, so both forms are
    accepted here and normalised in one place.
    """
    if not isinstance(raw, str) or not _UUID.match(raw.strip()):
        raise ConfigurationError(
            "tenant_id must be the tenant UUID shown on the console's Tenant page, "
            "dashed or as 32 hex characters."
        )
    return raw.strip().replace("-", "").lower()


def _origin(url: str, field: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise ConfigurationError(f"{field} must be an absolute URL, e.g. https://api.example.com")
    if parts.scheme != "https" and parts.hostname not in ("localhost", "127.0.0.1"):
        # Not a style rule. The credential is a bearer token with no origin
        # binding and no proof-of-possession: on http it is readable by anything
        # on the path, and it is valid until somebody revokes it.
        raise ConfigurationError(
            f"{field} must be https. A GraphRec credential is a bearer token and plaintext "
            "transport gives it away to everything between you and the server."
        )
    return f"{parts.scheme}://{parts.netloc}"


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """Everything the transport needs, with the hosts already decided."""

    credential: Credential
    tenant_hex: str
    control_origin: str
    data_origin: str
    timeout: float
    max_retries: int
    user_agent: str


def resolve_config(
    *,
    api_key: str,
    tenant_id: str,
    domain: str | None = None,
    console_domain: str | None = None,
    api_domain: str | None = None,
    control_url: str | None = None,
    data_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_retries: int = DEFAULT_MAX_RETRIES,
    user_agent: str | None = None,
) -> ResolvedConfig:
    """Resolve both hosts. Explicit URL beats explicit domain beats the shorthand.

    Each layer has a real caller: `control_url`/`data_url` for a local stack on a
    port, `console_domain`/`api_domain` for a self-hosted estate that names its
    two hosts independently — which is how the deploy is actually parameterised,
    as `GRAPHREC_CONSOLE_DOMAIN` and `GRAPHREC_API_DOMAIN` — and `domain` for the
    common case where they follow the published convention.
    """
    tenant_hex = normalise_tenant_id(tenant_id)

    console = console_domain or (f"api.{domain}" if domain else None)
    api = api_domain or (f"serve.{domain}" if domain else None)

    if control_url:
        control_origin = _origin(control_url, "control_url")
    elif console:
        control_origin = _origin(f"https://{console}", "console_domain")
    else:
        control_origin = ""

    if data_url:
        data_origin = _origin(data_url, "data_url")
    elif api:
        data_origin = _origin(f"https://{tenant_hex}.{api}", "api_domain")
    else:
        data_origin = ""

    if not control_origin or not data_origin:
        raise ConfigurationError(
            "Both hosts must be resolvable: pass `domain`, or `console_domain` and "
            "`api_domain`, or `control_url` and `data_url`. There are two public hosts and "
            "the data plane is reached on a hostname that contains your tenant id."
        )

    if not isinstance(timeout, int | float) or isinstance(timeout, bool) or timeout <= 0:
        raise ConfigurationError("timeout must be a positive number of seconds.")
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise ConfigurationError("max_retries must be a non-negative integer.")

    base = f"graphrec-python/{VERSION}"
    return ResolvedConfig(
        credential=Credential(api_key),
        tenant_hex=tenant_hex,
        control_origin=control_origin,
        data_origin=data_origin,
        timeout=float(timeout),
        max_retries=max_retries,
        user_agent=f"{base} {user_agent}" if user_agent else base,
    )
