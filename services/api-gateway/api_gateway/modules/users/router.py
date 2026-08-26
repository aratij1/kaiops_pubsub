from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Header, Request

from api_gateway.modules.users.permissions import AuthContext, current_auth_context, get_user_service, require_roles
from api_gateway.modules.users.schemas import (
    AuditLogsListResponse,
    AuthLoginRequest,
    AuthMeResponse,
    AuthRefreshRequest,
    AuthTokenResponse,
    ResetPasswordRequest,
    RoleRead,
    UserCreate,
    UserRead,
    UserStatusUpdate,
    UserUpdate,
    UsersListResponse,
)
from api_gateway.modules.users.service import UserService
from api_gateway.modules.users.models import SystemRole
from common.config import get_settings

router = APIRouter(tags=["user-management"])
settings = get_settings()


@router.get("/auth/config")
async def auth_config() -> dict:
    mode = str(os.getenv("AUTH_MODE", "local") or "local").strip().lower()
    if mode not in {"local", "oidc"}:
        mode = "local"
    return {
        "mode": mode,
        "local_development_only": mode == "local",
        "issuer": os.getenv("OIDC_ISSUER") or None,
        "client_id": os.getenv("OIDC_CLIENT_ID") or None,
        "audience": os.getenv("OIDC_AUDIENCE") or None,
        "authorization_endpoint": os.getenv("OIDC_AUTHORIZATION_ENDPOINT") or None,
        "token_endpoint": os.getenv("OIDC_TOKEN_ENDPOINT") or None,
        "redirect_uri": os.getenv("OIDC_REDIRECT_URI") or None,
        "scope": os.getenv("OIDC_SCOPE", "openid profile email"),
        "pkce_required": True,
    }


def _client_ip(request: Request, x_forwarded_for: str | None) -> str | None:
    if settings.trust_x_forwarded_for and x_forwarded_for:
        forwarded = [item.strip() for item in x_forwarded_for.split(",") if item.strip()]
        if forwarded:
            return forwarded[0][:64]
    if request.client and request.client.host:
        return str(request.client.host)[:64]
    return None


@router.post("/auth/login", response_model=AuthTokenResponse)
async def auth_login(
    request: Request,
    payload: AuthLoginRequest,
    x_forwarded_for: str | None = Header(default=None),
    user_service: UserService = Depends(get_user_service),
):
    ip_address = _client_ip(request, x_forwarded_for)
    data = await user_service.login(
        username=payload.username,
        password=payload.password,
        ip_address=ip_address,
        device=payload.device,
    )
    return AuthTokenResponse(**data)


@router.post("/auth/refresh", response_model=AuthTokenResponse)
async def auth_refresh(payload: AuthRefreshRequest, user_service: UserService = Depends(get_user_service)):
    data = await user_service.refresh(refresh_token=payload.refresh_token)
    return AuthTokenResponse(**data)


@router.post("/auth/logout")
async def auth_logout(
    auth: AuthContext = Depends(current_auth_context),
    user_service: UserService = Depends(get_user_service),
):
    return await user_service.logout(session_jti=auth.session_jti, user_id=auth.user_id)


@router.get("/auth/me", response_model=AuthMeResponse)
async def auth_me(
    auth: AuthContext = Depends(current_auth_context),
    user_service: UserService = Depends(get_user_service),
):
    return AuthMeResponse(**(await user_service.me(user_id=auth.user_id)))


@router.get("/roles", response_model=list[RoleRead])
async def list_roles(
    _: AuthContext = Depends(current_auth_context),
    user_service: UserService = Depends(get_user_service),
):
    return [RoleRead(**item) for item in await user_service.list_roles()]


@router.get("/users", response_model=UsersListResponse)
async def list_users(
    page: int = 1,
    page_size: int = 20,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    search: str | None = None,
    role_id: int | None = None,
    status: str | None = None,
    _: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    safe_page = max(1, int(page))
    safe_page_size = max(1, min(int(page_size), 100))
    rows, total = await user_service.list_users(
        page=safe_page,
        page_size=safe_page_size,
        search=search,
        role_id=role_id,
        status=status,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return UsersListResponse(rows=[UserRead(**row) for row in rows], count=total, page=safe_page, page_size=safe_page_size)


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    _: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    return UserRead(**(await user_service.get_user(user_id)))


@router.post("/users", response_model=UserRead)
async def create_user(
    request: Request,
    payload: UserCreate,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    ip_address = request.client.host if request.client else None
    return UserRead(**(await user_service.create_user(actor=str(auth.user_id), payload=payload, ip_address=ip_address)))


@router.put("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    request: Request,
    payload: UserUpdate,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    ip_address = request.client.host if request.client else None
    return UserRead(
        **(await user_service.update_user(actor=str(auth.user_id), user_id=user_id, payload=payload, ip_address=ip_address))
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    ip_address = request.client.host if request.client else None
    return await user_service.delete_user(actor=str(auth.user_id), user_id=user_id, ip_address=ip_address)


@router.patch("/users/{user_id}/status", response_model=UserRead)
async def update_user_status(
    user_id: int,
    request: Request,
    payload: UserStatusUpdate,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    ip_address = request.client.host if request.client else None
    return UserRead(
        **(
            await user_service.set_user_status(
                actor=str(auth.user_id),
                user_id=user_id,
                status=payload.status,
                is_active=payload.is_active,
                ip_address=ip_address,
            )
        )
    )


@router.patch("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    request: Request,
    payload: ResetPasswordRequest,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    ip_address = request.client.host if request.client else None
    return await user_service.reset_password(
        actor=str(auth.user_id),
        user_id=user_id,
        new_password=payload.new_password,
        ip_address=ip_address,
    )


@router.patch("/users/{user_id}/unlock")
async def unlock_user(
    user_id: int,
    request: Request,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    ip_address = request.client.host if request.client else None
    return await user_service.unlock_user(actor=str(auth.user_id), user_id=user_id, ip_address=ip_address)


@router.get("/audit-logs", response_model=AuditLogsListResponse)
async def list_audit_logs(
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    _: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    safe_page = max(1, int(page))
    safe_page_size = max(1, min(int(page_size), 100))
    rows, total = await user_service.list_audit_logs(page=safe_page, page_size=safe_page_size, action=action)
    return AuditLogsListResponse(rows=rows, count=total, page=safe_page, page_size=safe_page_size)
