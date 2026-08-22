"""Argon2id password hashing.

Argon2id rather than bcrypt or PBKDF2 because it is memory-hard: an attacker with
a GPU farm gains far less against it, and the SRS treats the credential digest as
the last line of defence if the database is exfiltrated.

Two properties here are load-bearing and easy to lose in a refactor:

* `verify` takes constant-ish time whether or not the account exists. A caller
  that skips the hash comparison when the email is unknown turns sign-in into an
  account-enumeration oracle, measurable over the network.
* `needs_rehash` lets parameters be raised later without a mass reset — the
  digest is upgraded on the next successful sign-in, when the plaintext is
  briefly in hand and nowhere else.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

#: OWASP's second recommended profile (19 MiB, t=2, p=1). Memory is the parameter
#: that matters against custom hardware; iterations are the cheap dial.
_HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=19 * 1024,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

#: Verified when no user matched, so that a miss costs the same as a hit. This is
#: a real digest of a value no one holds; the comparison always fails.
_DUMMY_DIGEST = _HASHER.hash("a-password-no-account-uses-0d0f4b9c")


def hash_password(password: str) -> str:
    """Return an Argon2id digest. The plaintext is not retained anywhere."""
    return _HASHER.hash(password)


def verify_password(digest: str | None, password: str) -> bool:
    """Check a password against a digest, in the same time either way.

    `digest=None` means "no such user", and is answered by verifying against a
    dummy rather than returning early. The cost of one Argon2 verification is
    what makes the timing of a miss indistinguishable from the timing of a wrong
    password; returning early would leak the account's existence.
    """
    candidate = digest if digest is not None else _DUMMY_DIGEST
    try:
        _HASHER.verify(candidate, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return digest is not None


def needs_rehash(digest: str) -> bool:
    """Whether the digest predates the current parameters."""
    try:
        return _HASHER.check_needs_rehash(digest)
    except InvalidHashError:
        # An unparseable digest cannot be verified against either, so the account
        # cannot sign in. Reporting it as needing a rehash is the honest answer
        # and avoids a crash on a corrupted row.
        return True
