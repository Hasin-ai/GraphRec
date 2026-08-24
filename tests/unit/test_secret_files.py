"""Secrets read from mounted files, not from the environment.

BACKEND_PLAN §22.2: "root-owned `0400` files as Docker secrets; rotation is file
replace + restart". `Settings.model_config.secrets_dir` is the code half of
that, and it is worth a test because the failure is invisible: a deployment that
mounts `/run/secrets/api_key_hmac_pepper` and does *not* read it starts
perfectly well on the shipped default pepper, and every credential on the
platform is then hashed with a value that is in this repository.

The environment-variable alternative is not equivalent. An environment variable
is visible in `docker inspect`, in `/proc/<pid>/environ` to anything running as
the same uid, and in any traceback from a library that prints the environment.
"""

from __future__ import annotations

import importlib
import pathlib
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from graphrec.common import config as config_module


@pytest.fixture
def secrets_dir(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[pathlib.Path]:
    """Point the module at a directory of secret files and reload it.

    `secrets_dir` is baked into `model_config` at class-construction time, so
    setting the variable afterwards does nothing — which is itself why the path
    is read at import and not somewhere later.
    """
    directory = tmp_path / "secrets"
    directory.mkdir()
    monkeypatch.setenv("GRAPHREC_SECRETS_DIR", str(directory))
    importlib.reload(config_module)
    yield directory
    monkeypatch.delenv("GRAPHREC_SECRETS_DIR", raising=False)
    importlib.reload(config_module)


def test_a_mounted_file_populates_the_setting(secrets_dir: pathlib.Path) -> None:
    (secrets_dir / "api_key_hmac_pepper").write_text("a-real-pepper-from-the-secret-store")
    settings = config_module.Settings()
    assert settings.api_key_hmac_pepper.get_secret_value() == "a-real-pepper-from-the-secret-store"


def test_the_file_name_is_the_setting_name(secrets_dir: pathlib.Path) -> None:
    """No mapping table between secret names and setting names.

    A table is a second thing to keep in step, and the way it goes wrong is that
    a renamed setting keeps reading the old file — silently, on the default.
    """
    (secrets_dir / "postgres_app_password").write_text("from-the-mount")
    (secrets_dir / "audit_hash_secret").write_text("also-from-the-mount")
    settings = config_module.Settings()
    assert settings.postgres_app_password.get_secret_value() == "from-the-mount"
    assert settings.audit_hash_secret.get_secret_value() == "also-from-the-mount"


def test_a_trailing_newline_does_not_become_part_of_the_secret(secrets_dir: pathlib.Path) -> None:
    """`echo 'x' > secret` is how these files get written by hand.

    A pepper with a stray newline hashes differently from the same pepper
    without one, and the symptom is every credential failing to verify after a
    rotation that looked fine.
    """
    (secrets_dir / "api_key_hmac_pepper").write_text("pepper-value\n")
    assert config_module.Settings().api_key_hmac_pepper.get_secret_value() == "pepper-value"


def test_the_environment_still_wins(
    secrets_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test or a one-off override must be able to beat the mount."""
    (secrets_dir / "s3_bucket").write_text("from-the-mount")
    monkeypatch.setenv("S3_BUCKET", "from-the-environment")
    assert config_module.Settings().s3_bucket == "from-the-environment"


def test_the_mount_beats_a_leftover_dotenv(secrets_dir: pathlib.Path) -> None:
    """The one pair `settings_customise_sources` reorders, and why.

    pydantic-settings puts `.env` above secret files by default. This repository
    ships a `.env` and it is on every developer's machine, so under the default
    order a node with one left behind would come up on the values in that file
    and override every secret the deployment mounted — with nothing in any log
    to say so.

    Asserted against `api_key_hmac_pepper`, which the repository's own `.env`
    sets, so this test is reading the real conflict rather than a constructed
    one.
    """
    assert "API_KEY_HMAC_PEPPER" in pathlib.Path(".env").read_text()
    (secrets_dir / "api_key_hmac_pepper").write_text("from-the-mount")
    assert config_module.Settings().api_key_hmac_pepper.get_secret_value() == "from-the-mount"


def test_no_mount_is_the_local_default() -> None:
    """Unset means unused. pydantic-settings warns on a `secrets_dir` that does
    not exist, and on a laptop it does not — which is why the path is read from
    the environment rather than hard-coded to `/run/secrets`."""
    assert config_module.SECRETS_DIR is None
    assert config_module.Settings().s3_bucket == "graphrec"


def test_production_still_refuses_a_default_pepper(secrets_dir: pathlib.Path) -> None:
    """The mount is a delivery mechanism, not an exemption.

    A deployment that mounts the *shipped* pepper is exactly as compromised as
    one that sets it in the environment, and `_production_requires_real_secrets`
    must fail either way.
    """
    (secrets_dir / "api_key_hmac_pepper").write_text("local-api-key-hmac-pepper-change-me")
    with pytest.raises(ValueError, match="default secrets"):
        config_module.Settings(environment="production")
