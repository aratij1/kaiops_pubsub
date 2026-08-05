"""current_tenant_id (backend/src/api-gateway/api_gateway/modules/users/permissions.py)
backs tenant scoping on read endpoints that don't otherwise require auth
(e.g. GET /alerts/all). It must resolve the caller's real tenant when a
valid token is present, and degrade to 'default' — not raise — when no
token or a garbled token is presented, since these endpoints stayed
open-by-design (api_gateway.auth_policy only gates specific write routes).
"""

from datetime import timedelta

import pytest
from api_gateway.modules.users.permissions import current_tenant_id
from api_gateway.modules.users.service import UserService
from common.config import Settings
from fastapi.security import HTTPAuthorizationCredentials


def _service() -> UserService:
    settings = Settings(
        DATABASE_ENABLED=False,
        JWT_SECRET_KEY="test-secret-key-that-is-at-least-32-bytes",
        ADMIN_USER_PASSWORD="Admin@123456",
        EXECUTIVE_USER_PASSWORD="Executive@123456",
        L3_USER_PASSWORD="L3Engineer@123456",
        L2_USER_PASSWORD="L2Engineer@123456",
        L1_USER_PASSWORD="L1Operator@123456",
    )
    return UserService(settings=settings, session_factory=None)


@pytest.mark.asyncio
async def test_returns_default_when_no_credentials_supplied() -> None:
    svc = _service()

    tenant_id = await current_tenant_id(credentials=None, user_service=svc)

    assert tenant_id == "default"


@pytest.mark.asyncio
async def test_resolves_real_tenant_from_a_valid_token() -> None:
    svc = _service()
    token = svc._encode_token(
        user_id=1,
        role="Administrator",
        tenant_id="acme-corp",
        token_type="access",
        expires_delta=timedelta(minutes=5),
        jwt_id="jti-1",
        session_jti="sid-1",
    )
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    tenant_id = await current_tenant_id(credentials=credentials, user_service=svc)

    assert tenant_id == "acme-corp"


@pytest.mark.asyncio
async def test_degrades_to_default_for_a_garbled_token_instead_of_raising() -> None:
    svc = _service()
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-real-jwt")

    tenant_id = await current_tenant_id(credentials=credentials, user_service=svc)

    assert tenant_id == "default"
