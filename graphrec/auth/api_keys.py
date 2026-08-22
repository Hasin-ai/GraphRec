"""Generation and verification of API credential secrets.

Three decisions are worth stating, because each is the opposite of what the
password code next door does and the difference is not arbitrary.

**HMAC-SHA-256, not Argon2id.** A password is low-entropy and human-chosen, so
it needs a slow KDF to make guessing expensive. A credential secret is 256 bits
from `secrets.token_bytes`; there is no guessing surface to defend, and it is
verified on every authenticated API request. A deliberately slow hash on that
path would add latency to every call and buy nothing. SRS §5.2.4 and
BACKEND_PLAN §17 both specify HMAC here.

**A server-side pepper, not a per-row salt.** A salt defends against precomputed
tables across a stolen database; that threat does not apply to a 256-bit random
value, which cannot be precomputed. What a pepper defends against is the stolen
database *alone* — the digests are useless without a secret that lives in the
process environment and not in the table. `hash_version` records which pepper
produced each digest so a compromised pepper can be replaced by writing a new
one and re-hashing on next use, rather than invalidating every credential in the
estate simultaneously.

**Constant-time comparison, always.** `hmac.compare_digest` on every path,
including the paths that are going to fail, because a verifier that returns
early on a mismatched prefix leaks the prefix through timing.

The secret is returned by exactly two functions, `issue` and the rotation that
calls it, and neither the digest nor the pepper is ever rendered.
"""

from __future__ import annotations

import dataclasses
import hmac
import secrets
from hashlib import sha256

#: The prototype's credentials seed all carry this shape (dc.html L673-677):
#: `gr_live_7Kq4`. The environment segment is fixed at `live` because this
#: system has one; a `gr_test_` lane would be a product decision, not a naming
#: one.
PREFIX_NAMESPACE = "gr_live_"

#: Four characters, drawn from the same alphabet the prototype uses. This is an
#: identifier, not a secret: it is printed in the console table and in logs, and
#: it exists so a person can tell two credentials apart. All the entropy lives
#: in the part after the separator.
_PREFIX_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_PREFIX_RANDOM_LENGTH = 4

#: 256 bits. The separator matters: it lets the verifier split a presented
#: credential into a prefix it can look up and a secret it must verify, without
#: either part having to be fixed-width.
_SECRET_BYTES = 32
_SEPARATOR = "."


@dataclasses.dataclass(frozen=True, slots=True)
class GeneratedSecret:
    """A freshly minted credential, in the only moment it exists in full.

    `secret` is the one field that is never persisted and never returned again.
    It is handed to the caller once — at creation or at rotation — and then it
    is gone, which is why `__repr__` is suppressed below.
    """

    visible_prefix: str
    secret: str
    digest: bytes
    hash_version: int

    def __repr__(self) -> str:
        """Deliberately lossy.

        A dataclass repr would put the secret into every stack trace, log line
        and debugger frame that touched it. NR-NF-06 forbids exactly that, and
        the failure mode is silent, so the defence belongs on the type rather
        than in the discipline of each call site.
        """
        return f"GeneratedSecret(visible_prefix={self.visible_prefix!r}, secret=<redacted>)"


def _random_prefix() -> str:
    suffix = "".join(secrets.choice(_PREFIX_ALPHABET) for _ in range(_PREFIX_RANDOM_LENGTH))
    return f"{PREFIX_NAMESPACE}{suffix}"


def digest_secret(secret: str, *, pepper: str, hash_version: int) -> bytes:
    """`HMAC-SHA-256(pepper, secret)`.

    `hash_version` is not mixed into the digest; it is recorded beside it. That
    is the point of versioning — the stored value must remain verifiable by the
    pepper that produced it, and the version says which one that was.
    """
    del hash_version  # recorded by the caller, not an input to the digest
    return hmac.new(pepper.encode("utf-8"), secret.encode("utf-8"), sha256).digest()


def issue(*, pepper: str, hash_version: int) -> GeneratedSecret:
    """Mint a prefix and a secret, and return them with the digest to store.

    The full presented credential is `{visible_prefix}.{random}`, so the prefix
    is recoverable from what the caller later sends without the caller having to
    send it separately.
    """
    visible_prefix = _random_prefix()
    random_part = secrets.token_urlsafe(_SECRET_BYTES)
    secret = f"{visible_prefix}{_SEPARATOR}{random_part}"
    return GeneratedSecret(
        visible_prefix=visible_prefix,
        secret=secret,
        digest=digest_secret(secret, pepper=pepper, hash_version=hash_version),
        hash_version=hash_version,
    )


def split_presented(presented: str) -> str | None:
    """Recover the prefix from a presented credential, or `None` if malformed.

    Returns only the prefix. The remainder is not returned because no caller
    needs it separately — verification is against the whole presented string,
    so there is no opportunity to compare the parts independently and no code
    path where half a credential is meaningful.
    """
    prefix, separator, remainder = presented.partition(_SEPARATOR)
    if not separator or not remainder:
        return None
    if not prefix.startswith(PREFIX_NAMESPACE):
        return None
    return prefix


def verify(presented: str, *, digest: bytes, pepper: str, hash_version: int) -> bool:
    """Constant-time check of a presented credential against a stored digest."""
    candidate = digest_secret(presented, pepper=pepper, hash_version=hash_version)
    return hmac.compare_digest(candidate, digest)


def dummy_verify(presented: str, *, pepper: str) -> None:
    """Burn the same work when no credential was found.

    Without this, an unknown prefix returns measurably faster than a known
    prefix with a wrong secret, which turns the API into an oracle for which
    prefixes exist. The same reasoning as the dummy Argon2id digest in
    `passwords.py`, and the same shape.
    """
    hmac.compare_digest(
        digest_secret(presented, pepper=pepper, hash_version=1),
        digest_secret("", pepper=pepper, hash_version=1),
    )


__all__ = [
    "PREFIX_NAMESPACE",
    "GeneratedSecret",
    "digest_secret",
    "dummy_verify",
    "issue",
    "split_presented",
    "verify",
]
