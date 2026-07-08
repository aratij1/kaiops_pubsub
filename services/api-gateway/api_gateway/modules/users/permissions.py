from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api_gateway.modules.users.service import UserService

security = HTTPBearer(auto_error=True)


@dataclass(slots=True)
class AuthContext:
    user_id: int
    role: str
    jwt_id: str
    token_type: str


def get_user_service(request: Request) -> UserService:
    service = getattr(request.app.state, "user_service", None)
    if service is None:
        raise HTTPException(status_code=500, detail="User service is not configured")
    return service


async def current_auth_context(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_service: UserService = Depends(get_user_service),
) -> AuthContext:
    payload = user_service.decode_token(credentials.credentials)
    token_type = str(payload.get("type") or "")
    if token_type != "access":
        raise HTTPException(status_code=401, detail="Access token required")

    return AuthContext(
        user_id=int(payload.get("sub", "0")),
        role=str(payload.get("role") or ""),
        jwt_id=str(payload.get("jti") or ""),
        token_type=token_type,
    )


def require_roles(*allowed_roles: str):
    async def _dependency(auth: AuthContext = Depends(current_auth_context)) -> AuthContext:
        if auth.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient role permissions")
        return auth

    return _dependency
