"""current_tenant_id must keep working for callers that don't send a bearer
token (e.g. the frontend's own alert-stream poll, which never attaches one
for /alerts/all, /incidents/closed, /landing-pad/recent, etc.), while still
resolving the real tenant for an authenticated caller. A regression in
2de0def switched this to unconditionally require the auto_error=True
`security` dependency, so a caller with no Authorization header at all got a
401 before this function's body ever ran -- silently breaking every
unauthenticated caller of those routes, including the UI itself."""

from fastapi import HTTPException
import pytest

from api_gateway.modules.users.permissions import current_tenant_id


class _FakeCredentials:
    def __init__(self, token: str) -> None:
        self.credentials = token


class _FakeUserService:
    def __init__(self, *, payload: dict | None = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    async def decode_access_token(self, token: str) -> dict:
        if self._error is not None:
            raise self._error
        return self._payload or {}


@pytest.mark.asyncio
async def test_returns_default_when_no_credentials_are_sent() -> None:
    """The exact regression case: no Authorization header at all must not
    raise 401 for these read-only, effectively-public routes."""
    tenant_id = await current_tenant_id(credentials=None, user_service=_FakeUserService())

    assert tenant_id == "default"


@pytest.mark.asyncio
async def test_returns_default_for_a_garbled_or_expired_token() -> None:
    """An invalid token degrades to 'default' rather than rejecting the
    request -- these routes don't otherwise require auth, so a request with
    a bad token should not be treated more strictly than one with none."""
    service = _FakeUserService(error=HTTPException(status_code=401, detail="Token expired"))

    tenant_id = await current_tenant_id(credentials=_FakeCredentials("garbled"), user_service=service)

    assert tenant_id == "default"


@pytest.mark.asyncio
async def test_returns_verified_tenant_for_a_valid_token() -> None:
    """An authenticated caller must still resolve to their own tenant, not
    silently downgrade to 'default'."""
    service = _FakeUserService(payload={"tenant_id": "acme-corp"})

    tenant_id = await current_tenant_id(credentials=_FakeCredentials("valid-token"), user_service=service)

    assert tenant_id == "acme-corp"


@pytest.mark.asyncio
async def test_returns_default_when_valid_token_has_no_tenant_claim() -> None:
    service = _FakeUserService(payload={})

    tenant_id = await current_tenant_id(credentials=_FakeCredentials("valid-token"), user_service=service)

    assert tenant_id == "default"
