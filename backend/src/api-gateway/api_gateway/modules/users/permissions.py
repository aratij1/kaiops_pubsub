from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api_gateway.modules.users.service import UserService

security = HTTPBearer(auto_error=True)
optional_security = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class AuthContext:
    user_id: int | str
    role: str
    tenant_id: str
    jwt_id: str
    session_jti: str
    token_type: str
    external: bool = False
    username: str = ""
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    acr: str = ""
    amr: tuple[str, ...] = ()


def get_user_service(request: Request) -> UserService:
    service = getattr(request.app.state, "user_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="User service is not configured")
    return service


async def current_auth_context(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_service: UserService = Depends(get_user_service),
) -> AuthContext:
    payload = await user_service.decode_access_token(credentials.credentials)
    token_type = str(payload.get("type") or "")
    if token_type != "access":
        raise HTTPException(status_code=401, detail="Access token required")
    external = bool(payload.get("external"))
    session_jti = str(payload.get("sid") or "").strip()
    if not external:
        if not session_jti:
            raise HTTPException(status_code=401, detail="Access token is missing session binding")
        await user_service.ensure_active_session(session_jti=session_jti, user_id=int(payload.get("sub", "0")))

    return AuthContext(
        user_id=str(payload.get("sub")) if external else int(payload.get("sub", "0")),
        role=str(payload.get("role") or ""),
        tenant_id=str(payload.get("tenant_id") or "default"),
        jwt_id=str(payload.get("jti") or ""),
        session_jti=session_jti,
        token_type=token_type,
        external=external,
        username=str(payload.get("preferred_username") or payload.get("upn") or payload.get("name") or payload.get("sub") or ""),
        email=str(payload.get("email") or payload.get("preferred_username") or "unknown@kaiops.example.com"),
        first_name=str(payload.get("given_name") or payload.get("name") or "External"),
        last_name=str(payload.get("family_name") or "User"),
        acr=str(payload.get("acr") or ""),
        amr=tuple(str(item) for item in (payload.get("amr") or []) if item),
    )


async def current_tenant_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_security),
    user_service: UserService = Depends(get_user_service),
) -> str:
    """Best-effort tenant scoping for read endpoints that must keep working
    for callers that don't yet send a bearer token (e.g. the live alert
    stream poll), while still real-isolating any caller that IS
    authenticated. An invalid/expired token here degrades to 'default'
    rather than a 401, since these endpoints don't otherwise require auth —
    making a request reject on a *garbled* token would be a stricter
    behavior change than today, not just narrower results.
    """
    if credentials is None:
        return "default"
    try:
        payload = await user_service.decode_access_token(credentials.credentials)
    except HTTPException:
        return "default"
    return str(payload.get("tenant_id") or "default")


def require_roles(*allowed_roles: str):
    async def _dependency(auth: AuthContext = Depends(current_auth_context)) -> AuthContext:
        if auth.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient role permissions")
        return auth

    return _dependency
