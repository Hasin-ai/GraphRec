from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes.auth import login_limiter
from apps.api.routes.api_keys import api_key_limiter
from apps.api.routes.subscriptions import subscription_limiter
from apps.api.routes.usage import usage_limiter
from apps.api.routes.tenants import registration_limiter


@pytest.fixture(autouse=True)
def clear_registration_rate_limit() -> None:
    registration_limiter.clear()
    login_limiter.clear()
    api_key_limiter.clear()
    subscription_limiter.clear()
    usage_limiter.clear()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client
