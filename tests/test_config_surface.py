"""One configuration surface (Phase 3): every setting is documented in
.env.example and passed to the services by Compose."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from graphrec_core.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
#: Settings Compose derives itself instead of reading from .env.
DERIVED = {"DATABASE_URL"}


def _documented() -> set[str]:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", text, re.M))


def test_every_setting_is_documented_in_env_example():
    missing = sorted(n.upper() for n in Settings.model_fields if n.upper() not in _documented())
    assert missing == []


def test_compose_passes_every_setting_to_the_api():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    passed = set(compose["services"]["api"]["environment"])
    missing = sorted(n.upper() for n in Settings.model_fields if n.upper() not in passed)
    assert missing == []
