"""Shared helpers for the demo scripts (argument parsing, env loading, output)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict

PACKAGE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_DIR))  # make `fixtures` importable when run as a script


def load_env(path: Path = PACKAGE_DIR / ".env") -> Dict[str, str]:
    """Read KEY=VALUE lines from .env without overriding variables already exported."""

    values: Dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return values


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def require(name: str) -> str:
    value = env(name)
    if not value:
        raise SystemExit(f"{name} is not set. Copy .env.example to .env and fill it in (or run scripts/bootstrap_tenant.py).")
    return value


def step(title: str) -> None:
    print(f"\n== {title}", flush=True)
