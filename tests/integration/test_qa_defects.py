"""Regression tests for defects found during QA (one test group per defect)."""
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from graphrec_core.auth.passwords import hash_password
from graphrec_core.auth.setup_tokens import issue_setup_token
from graphrec_core.database.models import TenantUser
from graphrec_core.database.session import SessionLocal
from graphrec_core.database.tenancy import set_local_tenant

pytestmark = pytest.mark.integration
JSON = {"Accept": "application/json"}


def provision(client, name=None):
    tag = uuid4().hex
    email = f"{tag}@example.org"
    created = client.post('/v1/tenants', json={'name': name or f'QA {tag}', 'admin_email': email},
                          headers={**JSON, 'Idempotency-Key': tag})
    assert created.status_code == 201, created.text
    password = f'Test-{tag}!'
    auth = client.post('/v1/auth/setup-password', json={'setup_token': created.json()['setup_token'],
                       'password': password}, headers=JSON)
    assert auth.status_code == 200, auth.text
    return created.json()['id'], email, password, {**JSON, 'Authorization': f"Bearer {auth.json()['access_token']}"}


def developer_headers(client, tenant):
    email, password = f'dev-{uuid4().hex[:10]}@example.org', 'qa developer password'
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant))
        db.add(TenantUser(id=uuid4(), tenant_id=UUID(tenant), email=email, display_name='Dev',
            credential_digest=hash_password(password), role='tenant_developer', status='active',
            created_at=datetime.now(timezone.utc)))
    token = client.post('/v1/auth/login', json={'email': email, 'password': password}, headers=JSON).json()['access_token']
    return {**JSON, 'Authorization': f'Bearer {token}'}


# ---- D12: cross-tenant invitation lockout --------------------------------
def test_invite_rejects_an_email_that_belongs_to_another_tenant(client):
    _, _, _, admin_a = provision(client)
    _, email_b, password_b, _ = provision(client)
    invite = client.post('/v1/tenant/users', json={'email': email_b, 'role': 'tenant_developer'}, headers=admin_a)
    assert invite.status_code == 409, invite.text
    assert invite.json()['error']['code'] == 'duplicate_resource'
    assert 'another tenant' not in invite.text.lower()          # does not reveal where it exists
    login = client.post('/v1/auth/login', json={'email': email_b, 'password': password_b}, headers=JSON)
    assert login.status_code == 200


def test_pre_existing_cross_tenant_invitation_cannot_be_accepted(client):
    tenant_a, _, _, _ = provision(client)
    _, email_b, password_b, _ = provision(client)
    # Simulate an invitation created before the fix.
    with SessionLocal() as db, db.begin():
        set_local_tenant(db, UUID(tenant_a))
        user = TenantUser(id=uuid4(), tenant_id=UUID(tenant_a), email=email_b, display_name='x',
                          credential_digest=None, role='tenant_developer', status='invited',
                          created_at=datetime.now(timezone.utc))
        db.add(user)
        db.flush()
        token, _ = issue_setup_token(db, tenant_id=UUID(tenant_a), user_id=user.id, ttl_seconds=3600,
                                     now=datetime.now(timezone.utc))
    accepted = client.post('/v1/auth/setup-password', json={'setup_token': token, 'password': 'Hijack-Password-1!'}, headers=JSON)
    assert accepted.status_code == 401
    assert client.post('/v1/auth/login', json={'email': email_b, 'password': password_b}, headers=JSON).status_code == 200


def test_revoke_invitation_disables_the_link_and_is_tenant_scoped(client):
    tenant_a, _, _, admin_a = provision(client)
    _, _, _, admin_b = provision(client)
    invited = client.post('/v1/tenant/users', json={'email': f'inv-{uuid4().hex[:8]}@example.org'}, headers=admin_a)
    assert invited.status_code == 201
    user_id, token = invited.json()['id'], invited.json()['setup_token']
    assert client.delete(f'/v1/tenant/users/{user_id}/invitation', headers=admin_b).status_code == 404
    assert client.delete(f'/v1/tenant/users/{user_id}/invitation', headers=developer_headers(client, tenant_a)).status_code == 403
    revoked = client.delete(f'/v1/tenant/users/{user_id}/invitation', headers=admin_a)
    assert revoked.status_code == 200 and revoked.json()['status'] == 'disabled'
    assert client.post('/v1/auth/setup-password', json={'setup_token': token, 'password': 'Some-Password-1!'}, headers=JSON).status_code == 401
    assert client.delete(f'/v1/tenant/users/{user_id}/invitation', headers=admin_a).status_code == 409
