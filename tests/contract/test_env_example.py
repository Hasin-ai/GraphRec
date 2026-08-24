"""`.env.example` against `Settings`, in both directions.

§24 asks for "`.env.example` complete and committed". Committed is easy to see;
complete is not, and it decays in the one direction nobody notices — a setting
added to `Settings` with a working default, which runs fine everywhere and is
invisible to the operator who has to configure production. Fourteen settings had
drifted out of the file by Phase 16, among them `POSTGRES_PLATFORM_USER` and
`POSTGRES_PLATFORM_PASSWORD`: an operator following the file would have brought
up a deployment where every platform-operator screen was connecting as a role
the deployment never created.

The other direction matters too. A line in `.env.example` that names no setting
is worse than a missing one, because it is confidently wrong: it gets copied
into `.env`, set to a considered value, and does nothing.

**A commented line counts as documented.** Three settings default to `None` and
must stay unset (`SMTP_HOST`, `TENANT_ID` and the SMTP credentials); writing
them as `SMTP_HOST=` would set them to the empty string, which is a different
state from unset and starts a different program. So they appear as `# NAME=`,
which is the file telling an operator the setting exists and that leaving it
alone is a choice.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from graphrec.common.config import Settings

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / ".env.example"

pytestmark = pytest.mark.contract

#: `NAME=` at the start of a line, optionally behind a comment marker.
ENTRY = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _documented() -> set[str]:
    return set(ENTRY.findall(EXAMPLE.read_text(encoding="utf-8")))


def _configurable() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def test_it_is_reading_the_file_it_thinks_it_is() -> None:
    """The floor. A regex that matched nothing would make both tests below pass
    on an empty file, and an empty `.env.example` is a plausible merge result."""
    documented = _documented()
    assert len(documented) > 50, f"only found {sorted(documented)}"
    assert "POSTGRES_HOST" in documented


def test_every_setting_is_in_the_example() -> None:
    missing = sorted(_configurable() - _documented())
    assert not missing, (
        f".env.example does not document {missing}. A setting with a working "
        "default is invisible until the deployment that needed it set is the "
        "one that broke."
    )


def test_the_example_names_no_setting_that_does_not_exist() -> None:
    stale = sorted(_documented() - _configurable())
    assert not stale, (
        f".env.example names {stale}, which `Settings` does not read. A line "
        "nobody reads gets copied into `.env` and set to a considered value."
    )
