from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel


def payload_hash(payload: BaseModel) -> str:
    """Hash caller-supplied values, excluding server-filled optional defaults."""
    value = payload.model_dump(mode="json", exclude_unset=True, exclude={"request_id"})
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
