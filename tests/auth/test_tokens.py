"""The token service, attacked rather than merely exercised.

A happy-path test proves a token round-trips. These aim at the things that make a
JWT verifier dangerous: algorithm confusion, realm crossing, type confusion and
tenant identity arriving from anywhere but a verified signature.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from graphrec.auth.tokens import (
    ALGORITHM,
    PlatformClaims,
    Realm,
    TenantClaims,
    TokenError,
    TokenService,
    TokenType,
    digest_token,
)

pytestmark = pytest.mark.authz


@pytest.fixture
def service(settings) -> TokenService:
    return TokenService(
        private_key_path=settings.jwt_private_key_path,
        public_key_path=settings.jwt_public_key_path,
        key_id=settings.jwt_key_id,
        issuer=settings.jwt_issuer,
        access_ttl_seconds=settings.access_token_ttl_seconds,
        refresh_ttl_seconds=settings.refresh_token_ttl_seconds,
    )


@pytest.fixture
def tenant_token(service) -> tuple[str, uuid.UUID, uuid.UUID]:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    token, _ = service.issue_tenant_access(
        tenant_id=tenant_id, user_id=user_id, role="tenant_administrator"
    )
    return token, tenant_id, user_id


# ------------------------------------------------------------ round trips


def test_a_tenant_token_carries_its_tenant_and_role(service, tenant_token) -> None:
    token, tenant_id, user_id = tenant_token
    claims = service.verify_tenant_access(token)
    assert isinstance(claims, TenantClaims)
    assert claims.tenant_id == tenant_id
    assert claims.user_id == user_id
    assert claims.role == "tenant_administrator"
    assert claims.realm is Realm.TENANT


def test_a_platform_token_carries_permissions_and_no_tenant(service) -> None:
    user_id = uuid.uuid4()
    token, _ = service.issue_platform_access(user_id=user_id, permissions={"platform", "audit"})
    claims = service.verify_platform_access(token)
    assert isinstance(claims, PlatformClaims)
    assert claims.permissions == frozenset({"platform", "audit"})
    assert claims.realm is Realm.PLATFORM
    assert "tid" not in jwt.decode(token, options={"verify_signature": False})


# ------------------------------------------------------- algorithm attacks


def test_an_unsigned_token_is_rejected(service, tenant_token) -> None:
    """`alg: none` — the first thing anyone tries."""
    _, tenant_id, user_id = tenant_token
    forged = jwt.encode(
        {
            "iss": "https://api.graphrec.example",
            "sub": str(user_id),
            "tid": str(tenant_id),
            "role": "tenant_administrator",
            "realm": "tenant",
            "typ": "access",
            "iat": int(dt.datetime.now(tz=dt.UTC).timestamp()),
            "exp": int((dt.datetime.now(tz=dt.UTC) + dt.timedelta(hours=1)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        key="",
        algorithm="none",
    )
    with pytest.raises(TokenError):
        service.verify_tenant_access(forged)


def test_a_token_signed_with_the_public_key_as_an_hmac_secret_is_rejected(
    service, settings, tenant_token
) -> None:
    """The classic RS/HS confusion, adapted.

    Our verification key is published at /.well-known/jwks.json, so an attacker
    holds it. If the verifier honoured the token's own `alg` header, they could
    sign an HMAC token with that public key and be believed.

    The forgery is assembled by hand because PyJWT refuses to *sign* HS256 with a
    PEM. That refusal is PyJWT's guard on the issuing side and proves nothing
    about ours — the attacker is not using our library. Building the three
    segments directly is what actually presents the forged token to our verifier.
    """
    _, tenant_id, user_id = tenant_token
    public_pem = settings.jwt_public_key_path.read_bytes()

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    now = dt.datetime.now(tz=dt.UTC)
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(
        json.dumps(
            {
                "iss": "https://api.graphrec.example",
                "sub": str(user_id),
                "tid": str(tenant_id),
                "role": "tenant_administrator",
                "realm": "tenant",
                "typ": "access",
                "iat": int(now.timestamp()),
                "exp": int((now + dt.timedelta(hours=1)).timestamp()),
                "jti": str(uuid.uuid4()),
            }
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode()
    signature = b64(hmac.new(public_pem, signing_input, hashlib.sha256).digest())

    with pytest.raises(TokenError):
        service.verify_tenant_access(f"{header}.{payload}.{signature}")


def test_a_token_signed_by_a_different_key_is_rejected(service, tmp_path) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    other = Ed25519PrivateKey.generate()
    pem = other.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    forged = jwt.encode(
        {
            "iss": "https://api.graphrec.example",
            "sub": str(uuid.uuid4()),
            "tid": str(uuid.uuid4()),
            "role": "tenant_administrator",
            "realm": "tenant",
            "typ": "access",
            "iat": int(dt.datetime.now(tz=dt.UTC).timestamp()),
            "exp": int((dt.datetime.now(tz=dt.UTC) + dt.timedelta(hours=1)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        key=pem.decode("ascii"),
        algorithm=ALGORITHM,
    )
    with pytest.raises(TokenError):
        service.verify_tenant_access(forged)


def test_a_tampered_payload_is_rejected(service, tenant_token) -> None:
    """Flipping a byte in the claims must break the signature, not the parse."""
    token, _, _ = tenant_token
    header, payload, signature = token.split(".")
    mutated = payload[:-4] + ("AAAA" if payload[-4:] != "AAAA" else "BBBB")
    with pytest.raises(TokenError):
        service.verify_tenant_access(f"{header}.{mutated}.{signature}")


# ----------------------------------------------------------- realm crossing


def test_a_platform_token_cannot_be_verified_as_a_tenant_token(service) -> None:
    token, _ = service.issue_platform_access(user_id=uuid.uuid4(), permissions={"platform"})
    with pytest.raises(TokenError):
        service.verify_tenant_access(token)


def test_a_tenant_token_cannot_be_verified_as_a_platform_token(service, tenant_token) -> None:
    token, _, _ = tenant_token
    with pytest.raises(TokenError):
        service.verify_platform_access(token)


def test_the_issuer_never_puts_a_tenant_in_a_platform_token(service) -> None:
    """Asserted on the wire, not on the dataclass, so a future edit is caught."""
    token, _ = service.issue_platform_access(
        user_id=uuid.uuid4(), permissions={"platform", "plan_management"}
    )
    raw = jwt.decode(token, options={"verify_signature": False})
    assert "tid" not in raw
    assert raw["realm"] == "platform"


# ------------------------------------------------------------- type confusion


def test_a_refresh_token_is_not_accepted_as_an_access_token(service) -> None:
    """It lives for a week; spending it as a bearer credential must not work."""
    session = service.issue_session_token(
        token_type=TokenType.REFRESH,
        realm=Realm.TENANT,
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )
    with pytest.raises(TokenError):
        service.verify_tenant_access(session.token)


def test_a_recovery_token_is_not_accepted_as_a_refresh_token(service) -> None:
    session = service.issue_session_token(
        token_type=TokenType.RECOVERY,
        realm=Realm.TENANT,
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        ttl=dt.timedelta(minutes=30),
    )
    with pytest.raises(TokenError):
        service.verify_session_token(session.token, token_type=TokenType.REFRESH)


def test_an_access_token_is_not_accepted_as_a_refresh_token(service, tenant_token) -> None:
    token, _, _ = tenant_token
    with pytest.raises(TokenError):
        service.verify_session_token(token, token_type=TokenType.REFRESH)


# ------------------------------------------------------------ session tokens


def test_a_session_token_carries_the_tenant_that_binds_the_lookup(service) -> None:
    """The `tid` here is what sets `app.tenant_id` before the row is read."""
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    session = service.issue_session_token(
        token_type=TokenType.REFRESH,
        realm=Realm.TENANT,
        user_id=user_id,
        tenant_id=tenant_id,
    )
    realm, got_user, got_session, got_tenant = service.verify_session_token(
        session.token, token_type=TokenType.REFRESH
    )
    assert realm is Realm.TENANT
    assert got_user == user_id
    assert got_tenant == tenant_id
    assert got_session == session.session_id


def test_a_platform_session_token_has_no_tenant(service) -> None:
    session = service.issue_session_token(
        token_type=TokenType.REFRESH,
        realm=Realm.PLATFORM,
        user_id=uuid.uuid4(),
        tenant_id=None,
    )
    realm, _, _, tenant_id = service.verify_session_token(
        session.token, token_type=TokenType.REFRESH
    )
    assert realm is Realm.PLATFORM
    assert tenant_id is None


def test_a_tenant_session_without_a_tenant_cannot_be_issued(service) -> None:
    with pytest.raises(TokenError):
        service.issue_session_token(
            token_type=TokenType.REFRESH,
            realm=Realm.TENANT,
            user_id=uuid.uuid4(),
            tenant_id=None,
        )


def test_a_platform_session_with_a_tenant_cannot_be_issued(service) -> None:
    with pytest.raises(TokenError):
        service.issue_session_token(
            token_type=TokenType.REFRESH,
            realm=Realm.PLATFORM,
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        )


def test_the_stored_digest_is_not_the_token(service) -> None:
    """A database dump must not yield usable sessions."""
    session = service.issue_session_token(
        token_type=TokenType.REFRESH,
        realm=Realm.TENANT,
        user_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )
    assert session.digest != session.token
    assert session.token not in session.digest
    assert session.digest == digest_token(session.token)
    assert len(session.digest) == 64


# --------------------------------------------------------------- expiry & iss


def test_an_expired_token_is_rejected(settings) -> None:
    from graphrec.common.clock import FrozenClock

    past = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    stale = TokenService(
        private_key_path=settings.jwt_private_key_path,
        public_key_path=settings.jwt_public_key_path,
        key_id=settings.jwt_key_id,
        issuer=settings.jwt_issuer,
        access_ttl_seconds=60,
        refresh_ttl_seconds=60,
        clock=FrozenClock(past),
    )
    token, _ = stale.issue_tenant_access(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role="tenant_developer"
    )
    live = TokenService(
        private_key_path=settings.jwt_private_key_path,
        public_key_path=settings.jwt_public_key_path,
        key_id=settings.jwt_key_id,
        issuer=settings.jwt_issuer,
        access_ttl_seconds=60,
        refresh_ttl_seconds=60,
    )
    with pytest.raises(TokenError):
        live.verify_tenant_access(token)


def test_a_token_from_another_issuer_is_rejected(settings, service) -> None:
    foreign = TokenService(
        private_key_path=settings.jwt_private_key_path,
        public_key_path=settings.jwt_public_key_path,
        key_id=settings.jwt_key_id,
        issuer="https://not-us.example",
        access_ttl_seconds=900,
        refresh_ttl_seconds=900,
    )
    token, _ = foreign.issue_tenant_access(
        tenant_id=uuid.uuid4(), user_id=uuid.uuid4(), role="tenant_developer"
    )
    with pytest.raises(TokenError):
        service.verify_tenant_access(token)


# ---------------------------------------------------------------------- JWKS


def test_jwks_publishes_a_pinned_algorithm_and_no_private_material(service) -> None:
    jwks = service.public_jwks()
    (key,) = jwks["keys"]
    assert key["kty"] == "OKP"
    assert key["crv"] == "Ed25519"
    assert key["alg"] == ALGORITHM
    assert key["use"] == "sig"
    # `d` is the private scalar. Its presence would publish the signing key.
    assert "d" not in key


def test_jwks_key_verifies_a_real_token(service, tenant_token) -> None:
    """The published key must actually be the one in use, not a stale copy."""
    token, _, _ = tenant_token
    key = service.public_jwks()["keys"][0]
    verified = jwt.decode(
        token,
        jwt.PyJWK.from_dict({**key, "alg": ALGORITHM}).key,
        algorithms=[ALGORITHM],
        issuer="https://api.graphrec.example",
    )
    assert verified["realm"] == "tenant"
