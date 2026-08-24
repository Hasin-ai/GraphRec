"""The demo bootstrap's refusal, which is the only part of it that must not run.

Seeding the tenant needs a database and is exercised by running the script; the
guard is what protects a host where nobody ran it deliberately, so it is the
part with a test. `.env.example` publishes `DEMO_LOGIN_PASSWORD`, which means
that on any host reading the shipped default, "bootstrap the demo" and "create
a platform operator whose password is in the repository" are the same act.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def bootstrap():
    spec = importlib.util.spec_from_file_location(
        "bootstrap_demo", ROOT / "scripts" / "bootstrap_demo.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bootstrap_demo"] = module
    spec.loader.exec_module(module)
    return module


def test_the_published_default_is_the_one_in_the_example_file(bootstrap) -> None:
    """The floor. A guard comparing against a password nobody ships never fires."""
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert f"DEMO_LOGIN_PASSWORD={bootstrap.PUBLISHED_DEFAULT}" in example


def test_it_refuses_a_deployed_host_with_the_published_password(
    bootstrap, monkeypatch, capsys
) -> None:
    """Staging, not production, because production cannot get this far.

    `Settings._production_requires_real_secrets` raises while *constructing* the
    settings, `demo_login_password` among the five it names — which is why this
    test is written against staging. It is the environment that validator does
    not cover, and the one where a seeded operator with a published password is
    reachable from outside.
    """
    import asyncio

    from graphrec.common.config import Settings

    settings = Settings(environment="staging")
    assert settings.demo_login_password.get_secret_value() == bootstrap.PUBLISHED_DEFAULT
    monkeypatch.setattr(bootstrap, "get_settings", lambda: settings)

    assert asyncio.run(bootstrap.run(force=False)) == 1
    assert "refusing" in capsys.readouterr().err


def test_production_cannot_even_build_its_settings_with_the_default() -> None:
    """The upstream half of the same guard, asserted here so the pair is visible.

    If this ever stops raising, the script's own check becomes the only thing
    standing between `.env.example` and a production administrator.
    """
    import pydantic

    from graphrec.common.config import Settings

    with pytest.raises(pydantic.ValidationError, match="default secrets"):
        Settings(environment="production")
