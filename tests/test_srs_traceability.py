"""Every SRS requirement is cited by at least one test (Phase 4 definition of done).

An ID counts as cited when it appears in the *name or docstring of a test function*
(Python, under ``tests/`` and ``sdks/python/tests/``), or in the title of a
``describe``/``it``/``test`` block in the web unit and browser tests. A mention in a
comment or an unrelated string does not count, so the citation sits next to the
assertion that checks the requirement.

The list of IDs is read from the traceability tables in ``docs/GAP_ANALYSIS.md``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID_PATTERN = r"(?:NR|ER|XR)-(?:F|NF)-\d\d|BRULE-\d\d|UC-\d\d"


def srs_ids() -> set[str]:
    text = (ROOT / "docs" / "GAP_ANALYSIS.md").read_text(encoding="utf-8")
    ids = set(re.findall(rf"^\| ({ID_PATTERN})\b", text, re.M))
    for first, last in re.findall(r"^\| UC-(\d\d)[–-](\d\d)", text, re.M):
        ids.update(f"UC-{n:02d}" for n in range(int(first), int(last) + 1))
    return ids


def _variants(found: str) -> str:
    return found.upper().replace("_", "-")


def python_citations() -> dict[str, set[str]]:
    cited: dict[str, set[str]] = {}
    files = [*ROOT.glob("tests/**/*.py"), *ROOT.glob("sdks/python/tests/**/*.py")]
    pattern = re.compile(ID_PATTERN.replace("-", "[-_]"), re.I)
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                text = f"{node.name} {ast.get_docstring(node) or ''}"
                for found in pattern.findall(text):
                    cited.setdefault(_variants(found), set()).add(f"{path.relative_to(ROOT)}::{node.name}")
    return cited


def web_citations() -> dict[str, set[str]]:
    cited: dict[str, set[str]] = {}
    files = [*ROOT.glob("web/src/**/*.test.ts"), *ROOT.glob("web/src/**/*.test.tsx"), *ROOT.glob("web/e2e/*.spec.ts")]
    title = re.compile(r"""\b(?:describe|it|test)\(\s*(['"`])(.*?)\1""")
    for path in files:
        for _, name in title.findall(path.read_text(encoding="utf-8")):
            for found in re.findall(ID_PATTERN, name):
                cited.setdefault(found, set()).add(f"{path.relative_to(ROOT)}: {name}")
    return cited


def test_every_srs_id_is_cited_by_a_test():
    ids = srs_ids()
    assert len(ids) == 101, f"expected the 101 SRS IDs in docs/GAP_ANALYSIS.md, found {len(ids)}"
    cited = python_citations()
    for key, where in web_citations().items():
        cited.setdefault(key, set()).update(where)
    missing = sorted(ids - set(cited))
    assert not missing, f"SRS IDs with no citing test: {missing}"
