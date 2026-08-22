"""Enum parity with the console prototype.

BUILD_PROMPT §6 calls a drift between the backend enums and the prototype's
vocabulary "the single most likely regression in this project". These tests are
the mechanical guard: they re-parse the prototype and compare it against both
generated artifacts, so a change to one that is not carried to the other fails
the build rather than surfacing as an untoned badge in the console.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE = ROOT / "Design system decision pending" / "GraphRec Console.dc.html"
TYPESCRIPT = ROOT / "frontend" / "src" / "lib" / "enums.ts"

pytestmark = pytest.mark.contract


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_enums", ROOT / "scripts" / "gen_enums.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_enums"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator():
    return _load_generator()


@pytest.fixture(scope="module")
def vocabulary(generator):
    """The prototype's vocabulary, freshly parsed.

    `load_vocabulary` calls sys.exit on a mismatch, which surfaces here as a
    failure naming the disagreement.
    """
    return generator.load_vocabulary()


def test_prototype_is_present() -> None:
    assert PROTOTYPE.exists(), (
        "the console prototype is the specification for the shared vocabulary; "
        "without it the generated enums cannot be verified"
    )


def test_generated_files_are_not_stale(generator, vocabulary) -> None:
    """The committed artifacts match what the prototype generates right now."""
    python_out = ROOT / "graphrec" / "common" / "enums.py"
    assert python_out.read_text(encoding="utf-8") == generator.render_python(
        vocabulary
    ), "graphrec/common/enums.py is stale — run `python scripts/gen_enums.py`"
    assert TYPESCRIPT.read_text(encoding="utf-8") == generator.render_typescript(
        vocabulary
    ), "frontend/src/lib/enums.ts is stale — run `python scripts/gen_enums.py`"


def test_badge_groups_match_the_prototype(vocabulary) -> None:
    from graphrec.common.enums import BADGE_TONES

    assert vocabulary.groups == BADGE_TONES


@pytest.mark.parametrize(
    ("group", "expected_size"),
    [
        ("job", 12),
        ("model", 7),
        ("deploy", 6),
        ("tenant", 5),
        ("user", 4),
        ("outcome", 4),
        ("sev", 4),
    ],
)
def test_group_sizes_are_as_specified(vocabulary, group: str, expected_size: int) -> None:
    """The counts BUILD_PROMPT §6 states, independently of what the parse found."""
    assert len(vocabulary.groups[group]) == expected_size


def test_model_lifecycle_is_the_seven_values_of_d8(vocabulary) -> None:
    """D8 — the prototype's seven values are the API's `status`.

    TRAINING/EVALUATED/FAILED belong to the training job; DEPLOYING is
    model_deployments.state = 'progressing'. None of them may leak in here.
    """
    from graphrec.common.enums import ModelVersionStatus

    assert {s.value for s in ModelVersionStatus} == {
        "registered",
        "eligible",
        "active",
        "retired",
        "rejected",
        "archived",
        "failed_deployment",
    }
    for rejected in ("training", "evaluated", "deploying", "failed"):
        assert rejected not in {s.value for s in ModelVersionStatus}


def test_job_stage_rail_is_ordered_and_nine_long(vocabulary) -> None:
    """The rail's order drives the console's stage display; it is not a set."""
    from graphrec.common.enums import JOB_STAGES

    assert [s.value for s in JOB_STAGES] == vocabulary.job_stages
    assert [s.value for s in JOB_STAGES] == [
        "queued",
        "waiting_for_resources",
        "preparing_data",
        "building_graph",
        "training",
        "evaluating",
        "indexing_embeddings",
        "registering",
        "succeeded",
    ]


def test_every_stage_is_also_a_job_state(vocabulary) -> None:
    from graphrec.common.enums import JOB_STAGES, JobState

    for stage in JOB_STAGES:
        assert isinstance(stage, JobState)


def test_scopes_carry_machine_names_and_console_labels(vocabulary) -> None:
    """The wire carries a stable machine name; dialogs render the human label."""
    from graphrec.common.enums import SCOPE_LABELS, CredentialScope

    assert len(CredentialScope) == 5
    assert sorted(SCOPE_LABELS.values()) == sorted(vocabulary.scopes)
    assert SCOPE_LABELS[CredentialScope.CATALOG_WRITE] == "catalog write & synchronization"


def test_permissions_are_five_independently_grantable_values(vocabulary) -> None:
    from graphrec.common.enums import PERMISSION_LABELS, PlatformPermission

    assert len(PlatformPermission) == 5
    assert sorted(PERMISSION_LABELS.values()) == sorted(vocabulary.perms)


def test_typescript_declares_every_python_value(vocabulary) -> None:
    """Both artifacts carry the same values, so the console cannot disagree."""
    from graphrec.common.enums import BADGE_TONES

    typescript = TYPESCRIPT.read_text(encoding="utf-8")
    for group, tones in BADGE_TONES.items():
        for value in tones:
            assert f"'{value}'" in typescript, f"{group}.{value} missing from enums.ts"


def test_typescript_badge_tone_map_matches_python(vocabulary) -> None:
    from graphrec.common.enums import BADGE_TONES

    typescript = TYPESCRIPT.read_text(encoding="utf-8")
    block = re.search(r"BADGE_TONES[^=]*=\s*\{(.*?)\n\};", typescript, re.DOTALL)
    assert block, "BADGE_TONES not found in enums.ts"

    for group, tones in BADGE_TONES.items():
        line = re.search(rf"\n  {group}: \{{(.*?)\}},", block.group(1))
        assert line, f"group {group} missing from the TypeScript tone map"
        parsed = dict(re.findall(r"(\w+): '(\w+)'", line.group(1)))
        assert parsed == tones, f"tone map for {group} differs between Python and TypeScript"


def test_tones_are_drawn_from_the_prototypes_five(vocabulary) -> None:
    """An unknown tone would render as an unstyled badge."""
    valid = {"ok", "warn", "danger", "info", "neu"}
    for group, tones in vocabulary.groups.items():
        for value, tone in tones.items():
            assert tone in valid, f"{group}.{value} has unknown tone {tone!r}"
