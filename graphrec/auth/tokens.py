"""Token issuing and verification (EdDSA / Ed25519), for both realms.

Why asymmetric at all, when one process both signs and verifies today: the
inference service verifies tokens it never issues, and giving it the signing key
would let a compromised inference node mint administrator sessions. Ed25519 keeps
the private key in the control API and hands everything else a public JWK.

Three properties are deliberate and must survive refactoring:

* **The algorithm is pinned on both sides.** `decode` is called with
  `algorithms=["EdDSA"]` and never with a list derived from the token's own
  header. A verifier that trusts the header accepts `alg: none`, or accepts an
  HMAC signed with the public key it published — the classic algorithm-confusion
  forgeries.
* **The realm is a claim, not an inference.** A platform token carries
  `realm: "platform"` and no `tid`; a tenant token carries `realm: "tenant"` and
  a `tid`. Neither is deduced from the absence of the other, so a token that
  somehow carries both is rejected rather than silently treated as one of them.
* **Tenant identity comes only from `tid`.** Nothing in this module accepts a
  tenant identifier from a caller, and nothing outside it should either.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from graphrec.common.clock import Clock, utcnow
from graphrec.common.ids import uuid7

#: The only algorithm this system will sign or verify with.
ALGORITHM = "EdDSA"


class TokenError(Exception):
    """Any failure to verify. Deliberately undifferentiated at the boundary.

    Callers turn this into one message ("The credentials supplied are not
    valid..."). The distinction between expired, malformed, wrong-issuer and
    wrong-realm is useful in a log line and is an oracle in a response body.
    """


class Realm(StrEnum):
    TENANT = "tenant"
    PLATFORM = "platform"


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    RECOVERY = "recovery"


@dataclass(frozen=True, slots=True)
class TenantClaims:
    """A verified tenant credential. `tenant_id` here is trustworthy; nothing else is."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    token_id: uuid.UUID
    expires_at: dt.datetime
    realm: Realm = Realm.TENANT


@dataclass(frozen=True, slots=True)
class PlatformClaims:
    """A verified operator credential. Has no tenant, and cannot acquire one."""

    user_id: uuid.UUID
    permissions: frozenset[str]
    token_id: uuid.UUID
    expires_at: dt.datetime
    realm: Realm = Realm.PLATFORM


@dataclass(frozen=True, slots=True)
class SessionToken:
    """A refresh or recovery token: the string to hand out, and what to store.

    `token` is returned to the caller once. `digest` is what goes in the database
    — the raw string is never persisted, so a database dump does not yield usable
    sessions.
    """

    token: str
    digest: str
    session_id: uuid.UUID
    expires_at: dt.datetime


@lru_cache(maxsize=4)
def _load_private_key(path: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TokenError("the configured signing key is not an Ed25519 private key")
    return key


@lru_cache(maxsize=4)
def _load_public_key(path: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(Path(path).read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise TokenError("the configured verification key is not an Ed25519 public key")
    return key


class TokenService:
    """Issues and verifies every token in the system.

    Constructed from settings once per process. Holding it rather than reaching
    for module-level functions means the key paths and TTLs are configuration
    rather than constants scattered through handlers.
    """

    def __init__(
        self,
        *,
        private_key_path: Path,
        public_key_path: Path,
        key_id: str,
        issuer: str,
        access_ttl_seconds: int,
        refresh_ttl_seconds: int,
        clock: Clock | None = None,
    ) -> None:
        self._private_path = str(private_key_path)
        self._public_path = str(public_key_path)
        self._kid = key_id
        self._issuer = issuer
        self._access_ttl = dt.timedelta(seconds=access_ttl_seconds)
        self._refresh_ttl = dt.timedelta(seconds=refresh_ttl_seconds)
        self._clock = clock

    # ------------------------------------------------------------ issuing

    def _now(self) -> dt.datetime:
        return self._clock.now() if self._clock is not None else utcnow()

    def _sign(self, claims: dict[str, Any]) -> str:
        return jwt.encode(
            claims,
            _load_private_key(self._private_path),
            algorithm=ALGORITHM,
            headers={"kid": self._kid},
        )

    def issue_tenant_access(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, role: str
    ) -> tuple[str, dt.datetime]:
        now = self._now()
        expires = now + self._access_ttl
        token = self._sign(
            {
                "iss": self._issuer,
                "sub": str(user_id),
                "tid": str(tenant_id),
                "role": role,
                "realm": Realm.TENANT.value,
                "typ": TokenType.ACCESS.value,
                "iat": int(now.timestamp()),
                "exp": int(expires.timestamp()),
                "jti": str(uuid7()),
            }
        )
        return token, expires

    def issue_platform_access(
        self, *, user_id: uuid.UUID, permissions: frozenset[str] | set[str]
    ) -> tuple[str, dt.datetime]:
        now = self._now()
        expires = now + self._access_ttl
        token = self._sign(
            {
                "iss": self._issuer,
                "sub": str(user_id),
                # No `tid`, and no branch anywhere that would add one. An operator
                # acts on a tenant by naming it in a request the platform routes
                # authorize — never by carrying tenancy in their credential.
                "perms": sorted(permissions),
                "realm": Realm.PLATFORM.value,
                "typ": TokenType.ACCESS.value,
                "iat": int(now.timestamp()),
                "exp": int(expires.timestamp()),
                "jti": str(uuid7()),
            }
        )
        return token, expires

    def issue_session_token(
        self,
        *,
        token_type: TokenType,
        realm: Realm,
        user_id: uuid.UUID,
        tenant_id: uuid.UUID | None,
        ttl: dt.timedelta | None = None,
    ) -> SessionToken:
        """Mint a refresh or recovery token.

        These are signed rather than opaque for one specific reason: the row that
        records them is under RLS, so a tenant context has to be bound *before*
        the lookup, and the only trustworthy source for it is a verified claim in
        the token itself. An opaque random string would force a lookup with no
        context bound — which is exactly the query RLS is there to prevent.
        """
        if (realm is Realm.TENANT) != (tenant_id is not None):
            raise TokenError("a tenant session requires a tenant, a platform session forbids one")

        now = self._now()
        expires = now + (ttl if ttl is not None else self._refresh_ttl)
        session_id = uuid7()
        claims: dict[str, Any] = {
            "iss": self._issuer,
            "sub": str(user_id),
            "sid": str(session_id),
            "realm": realm.value,
            "typ": token_type.value,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": str(uuid7()),
        }
        if tenant_id is not None:
            claims["tid"] = str(tenant_id)
        token = self._sign(claims)
        return SessionToken(
            token=token,
            digest=digest_token(token),
            session_id=session_id,
            expires_at=expires,
        )

    # ---------------------------------------------------------- verifying

    def _decode(self, token: str, *, expected_type: TokenType) -> dict[str, Any]:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                _load_public_key(self._public_path),
                # Pinned. Never `jwt.get_unverified_header(token)["alg"]`, which
                # is the attacker's field, not ours.
                algorithms=[ALGORITHM],
                issuer=self._issuer,
                options={"require": ["exp", "iat", "iss", "sub", "typ", "realm", "jti"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenError("token is not valid") from exc

        if claims.get("typ") != expected_type.value:
            # A refresh token presented as a bearer credential must not work:
            # it outlives an access token by days precisely because it can only
            # be exchanged, not spent.
            raise TokenError("token is not valid")
        return claims

    def verify_tenant_access(self, token: str) -> TenantClaims:
        claims = self._decode(token, expected_type=TokenType.ACCESS)
        if claims.get("realm") != Realm.TENANT.value or "perms" in claims:
            raise TokenError("token is not valid")
        try:
            return TenantClaims(
                tenant_id=uuid.UUID(claims["tid"]),
                user_id=uuid.UUID(claims["sub"]),
                role=str(claims["role"]),
                token_id=uuid.UUID(claims["jti"]),
                expires_at=dt.datetime.fromtimestamp(claims["exp"], tz=dt.UTC),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise TokenError("token is not valid") from exc

    def verify_platform_access(self, token: str) -> PlatformClaims:
        claims = self._decode(token, expected_type=TokenType.ACCESS)
        if claims.get("realm") != Realm.PLATFORM.value or "tid" in claims:
            # A platform token carrying a `tid` is not a platform token acting on
            # a tenant — it is a forgery attempt or a bug, and either way the
            # only safe answer is refusal.
            raise TokenError("token is not valid")
        try:
            return PlatformClaims(
                user_id=uuid.UUID(claims["sub"]),
                permissions=frozenset(str(p) for p in claims.get("perms", ())),
                token_id=uuid.UUID(claims["jti"]),
                expires_at=dt.datetime.fromtimestamp(claims["exp"], tz=dt.UTC),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise TokenError("token is not valid") from exc

    def verify_session_token(
        self, token: str, *, token_type: TokenType
    ) -> tuple[Realm, uuid.UUID, uuid.UUID, uuid.UUID | None]:
        """Return `(realm, user_id, session_id, tenant_id)` from a verified token.

        The `tenant_id` returned here is what binds the database context for the
        lookup that follows. It comes from a signature-verified claim and from
        nowhere else — not from a path segment, a query parameter or a body.
        """
        claims = self._decode(token, expected_type=token_type)
        try:
            realm = Realm(claims["realm"])
            user_id = uuid.UUID(claims["sub"])
            session_id = uuid.UUID(claims["sid"])
            raw_tenant = claims.get("tid")
            tenant_id = uuid.UUID(raw_tenant) if raw_tenant is not None else None
        except (KeyError, ValueError, TypeError) as exc:
            raise TokenError("token is not valid") from exc

        if (realm is Realm.TENANT) != (tenant_id is not None):
            raise TokenError("token is not valid")
        return realm, user_id, session_id, tenant_id

    # ------------------------------------------------------------- JWKS

    def public_jwks(self) -> dict[str, list[dict[str, str]]]:
        """The public key set, for verifiers that never hold the private key."""
        import base64

        raw = _load_public_key(self._public_path).public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return {
            "keys": [
                {
                    "kty": "OKP",
                    "crv": "Ed25519",
                    "use": "sig",
                    # `alg` is published so a verifier can pin from the key set
                    # rather than from the token it is about to check.
                    "alg": ALGORITHM,
                    "kid": self._kid,
                    "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"),
                }
            ]
        }


def digest_token(token: str) -> str:
    """SHA-256 of a token, for storage and lookup.

    Not Argon2: this is a 200-bit-plus random-equivalent value, not a
    human-chosen password, so there is nothing for a memory-hard function to
    defend against and a per-request Argon2 verification would be a denial of
    service against ourselves. SHA-256 of a high-entropy secret is not
    brute-forceable.
    """
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()
