"""Fail if any SDK call shown on the docs site or homepage does not exist in the SDK.

    sdks/python/.venv/Scripts/python scripts/check_doc_sdk_calls.py

Scans web/src for Python snippets of the form ``<var>.storefront|tenant|platform.<res>.<method>(``
and ``from graphrec_sdk[.ecommerce] import X``, and resolves each against the real SDK.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sdks" / "python" / "src"))

import graphrec_sdk as g  # noqa: E402

client = g.GraphRec(api_key="gr_live_check", base_url="http://check.invalid", use_env=False)
CALL = re.compile(r"\b\w+\.(storefront|tenant|platform)((?:\.\w+)+)\(")
IMPORT = re.compile(r"from graphrec_sdk((?:\.\w+)*) import ([\w, ]+)")

files = [p for p in (ROOT / "web" / "src").rglob("*.ts*") if "sdkData" not in p.name and ".test." not in p.name]
problems: list[str] = []
checked = 0
for path in files:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT)
    for m in CALL.finditer(text):
        chain = [m.group(1)] + m.group(2).strip(".").split(".")
        obj = client
        for part in chain:
            obj = getattr(obj, part, None)
            if obj is None:
                break
        checked += 1
        if obj is None or not callable(obj):
            problems.append(f"{rel}: client.{'.'.join(chain)}() does not exist")
    for m in IMPORT.finditer(text):
        modname = "graphrec_sdk" + (m.group(1) or "")
        try:
            mod = importlib.import_module(modname)
        except ImportError:
            problems.append(f"{rel}: module {modname} does not exist")
            continue
        for name in (n.strip() for n in m.group(2).split(",")):
            checked += 1
            if name and not hasattr(mod, name):
                problems.append(f"{rel}: {modname}.{name} does not exist")

print(f"checked {checked} SDK references in {len(files)} files")
for p in sorted(set(problems)):
    print("  ✗", p)
sys.exit(1 if problems else 0)
