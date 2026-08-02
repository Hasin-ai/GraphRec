from __future__ import annotations

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError

password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
DUMMY_PASSWORD_HASH = password_hasher.hash("graphrec-constant-time-dummy-password")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    candidate_hash = password_hash or DUMMY_PASSWORD_HASH
    try:
        return password_hasher.verify(candidate_hash, password) and password_hash is not None
    except VerificationError:
        return False
