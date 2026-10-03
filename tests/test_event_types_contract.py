"""The console's event-type list must equal the API's accepted types."""
import re
from pathlib import Path
from typing import get_args

import pytest

from graphrec_core.schemas.events import EVENT_TYPES, EventType

FRONTEND = Path(__file__).resolve().parents[1] / "frontend_02" / "src" / "api" / "eventTypes.ts"


def test_literal_matches_constant():
    assert set(get_args(EventType)) == set(EVENT_TYPES)


@pytest.mark.skipif(not FRONTEND.exists(), reason="frontend sources are not in this image")
def test_console_event_types_match_api():
    listed = re.findall(r'"([a-z_]+)"', FRONTEND.read_text(encoding="utf-8"))
    assert set(listed) == set(EVENT_TYPES)
