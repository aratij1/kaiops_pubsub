"""Tenant-sensitive reads must use a verified authentication context."""

import pytest

from api_gateway.modules.users.permissions import AuthContext, current_tenant_id


@pytest.mark.asyncio
async def test_returns_verified_auth_tenant() -> None:
    auth = AuthContext(
        user_id=1,
        role="Administrator",
        tenant_id="acme-corp",
        token_type="access",
        jwt_id="jti-1",
        session_jti="sid-1",
    )

    assert await current_tenant_id(auth=auth) == "acme-corp"
