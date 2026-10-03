"""Lowering an inventory limit below current usage needs explicit acknowledgement."""
from uuid import uuid4

import pytest

from graphrec_core.errors import ApiError
from graphrec_core.usage import limits as quota


class _Session:
    rolled_back = False

    def rollback(self):
        self.rolled_back = True


def test_reports_only_inventory_limits_already_exceeded(monkeypatch):
    monkeypatch.setattr(quota, "inventory_usage", lambda db, tid: {"stored_products": 57_289, "active_model_versions": 1, "artifact_storage_bytes": 10})
    conflicts = quota.limits_below_inventory(None, uuid4(), {"stored_products": 50_000, "active_model_versions": 1, "artifact_storage_bytes": 100, "accepted_events": 0})
    assert conflicts == [{"limit_name": "stored_products", "limit": 50_000, "used": 57_289, "over_by": 7_289}]


def test_guard_refuses_and_rolls_back_without_acknowledgement():
    from apps.api.routes.platform import _guard_below_usage
    session = _Session()
    conflict = [{"limit_name": "stored_products", "limit": 1, "used": 2, "over_by": 1}]
    with pytest.raises(ApiError) as raised:
        _guard_below_usage(session, conflict, acknowledged=False)
    assert raised.value.status_code == 409 and raised.value.code == "limit_below_usage"
    assert raised.value.details == {"conflicts": conflict}
    assert session.rolled_back


def test_guard_applies_with_acknowledgement_and_returns_warnings():
    from apps.api.routes.platform import _guard_below_usage
    session = _Session()
    conflict = [{"limit_name": "stored_products", "limit": 1, "used": 2, "over_by": 1}]
    assert _guard_below_usage(session, conflict, acknowledged=True) == conflict
    assert _guard_below_usage(session, [], acknowledged=False) == []
    assert not session.rolled_back
