#!/usr/bin/env python3
"""Generate the Ed25519 signing keypair used for tenant and platform tokens.

D5 chose EdDSA over HS256 so that a per-tenant inference process can verify a
token against a published JWKS without calling the control plane on every
recommendation request. That only holds if the private key stays in the control
plane: this script writes it `0600` and refuses to overwrite an existing key,
because rotating out from under live tokens is a deliberate act, not a rerun.

    python scripts/gen_jwt_keys.py                 # writes to secrets/
    python scripts/gen_jwt_keys.py --kid prod-2 --force
    python scripts/gen_jwt_keys.py --print-jwks    # the public document only
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def _b64url(raw: bytes) -> str:
    """base64url with the padding stripped, as RFC 7515 §2 requires."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def public_jwk(public_key: Ed25519PublicKey, kid: str) -> dict[str, str]:
    """The JWKS entry an inference process fetches to verify locally.

    `use` and `alg` are stated rather than left to the verifier's default: a key
    document that does not pin its algorithm invites an `alg` confusion attack.
    """
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "use": "sig",
        "alg": "EdDSA",
        "kid": kid,
        "x": _b64url(raw),
    }


def write_keypair(private_path: Path, public_path: Path, kid: str, force: bool) -> dict[str, str]:
    existing = [p for p in (private_path, public_path) if p.exists()]
    if existing and not force:
        names = ", ".join(str(p) for p in existing)
        raise SystemExit(
            f"refusing to overwrite {names}.\n"
            "Replacing a signing key invalidates every token already issued under it. "
            "Pass --force only if that is what you mean."
        )

    private_key = Ed25519PrivateKey.generate()

    private_path.parent.mkdir(parents=True, exist_ok=True)
    # Create with 0600 from the outset rather than chmod-ing afterwards; the
    # window between the two is a window in which the key is world-readable.
    fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "wb") as handle:
        handle.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    public_key = private_key.public_key()
    public_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    public_path.chmod(0o644)

    return public_jwk(public_key, kid)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, default=Path("secrets/jwt_ed25519_private.pem"))
    parser.add_argument("--public", type=Path, default=Path("secrets/jwt_ed25519_public.pem"))
    parser.add_argument("--kid", default="graphrec-local-1", help="key id published in the JWKS")
    parser.add_argument("--force", action="store_true", help="overwrite an existing keypair")
    parser.add_argument(
        "--print-jwks",
        action="store_true",
        help="print the JWKS for an existing public key and write nothing",
    )
    args = parser.parse_args(argv)

    if args.print_jwks:
        loaded = serialization.load_pem_public_key(args.public.read_bytes())
        if not isinstance(loaded, Ed25519PublicKey):
            raise SystemExit(f"{args.public} is not an Ed25519 public key")
        print(json.dumps({"keys": [public_jwk(loaded, args.kid)]}, indent=2))
        return 0

    jwk = write_keypair(args.private, args.public, args.kid, args.force)
    print(f"wrote {args.private} (0600) and {args.public}", file=sys.stderr)
    print(f"set JWT_KEY_ID={args.kid}", file=sys.stderr)
    print(json.dumps({"keys": [jwk]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
