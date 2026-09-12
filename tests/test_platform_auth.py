from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from graphrec_core.settings import Settings, get_settings

PLATFORM_TOKEN = "unit-test-platform-administrator-token-0123456789"
PLATFORM_PATHS = (
    "/v1/platform/tenants",
    "/v1/platform/plans",
    "/v1/platform/failures",
    "/v1/platform/audit",
    "/v1/platform/status",
)


@pytest.fixture
def platform_client():
    def configured() -> Settings:
        return Settings(platform_admin_token=PLATFORM_TOKEN)

    app.dependency_overrides[get_settings] = configured
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_settings, None)


@pytest.mark.parametrize("path", PLATFORM_PATHS)
def test_platform_routes_reject_missing_credential(platform_client: TestClient, path: str) -> None:
    response = platform_client.get(path, headers={"Accept": "application/json"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_failed"


@pytest.mark.parametrize("path", PLATFORM_PATHS)
def test_platform_routes_reject_wrong_credential(platform_client: TestClient, path: str) -> None:
    response = platform_client.get(
        path,
        headers={"Accept": "application/json", "Authorization": f"Bearer {PLATFORM_TOKEN}x"},
    )
    assert response.status_code == 401


def test_platform_routes_reject_tenant_style_scheme(platform_client: TestClient) -> None:
    response = platform_client.get(
        "/v1/platform/tenants",
        headers={"Accept": "application/json", "Authorization": f"ApiKey {PLATFORM_TOKEN}"},
    )
    assert response.status_code == 401


def test_platform_routes_disabled_when_token_unset() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(platform_admin_token=None)
    try:
        with TestClient(app) as client:
            response = client.get(
                "/v1/platform/tenants",
                headers={"Accept": "application/json", "Authorization": "Bearer anything-at-all"},
            )
    finally:
        app.dependency_overrides.pop(get_settings, None)
    assert response.status_code == 401


def test_blank_platform_token_disables_platform() -> None:
    assert Settings(platform_admin_token="   ").platform_admin_token is None


def test_short_platform_token_is_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(platform_admin_token="too-short")


def test_tenant_status_update_rejects_unauthenticated_writes(platform_client: TestClient) -> None:
    response = platform_client.post(
        "/v1/platform/tenants/00000000-0000-4000-8000-000000000001/status",
        json={"status": "suspended"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 401
