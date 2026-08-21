from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from fastapi import APIRouter, Depends, Header, HTTPException, Request

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
    if settings.auth_mode != "local":
        raise HTTPException(status_code=404, detail="Local token refresh is disabled")
    data = await user_service.refresh(refresh_token=payload.refresh_token)
    return AuthTokenResponse(**data)


@router.post("/auth/logout")
async def auth_logout(
    auth: AuthContext = Depends(current_auth_context),
    user_service: UserService = Depends(get_user_service),
):
    if auth.external:
        return {"status": "signed_out", "provider_session": "must be ended at the identity provider"}
    return await user_service.logout(session_jti=auth.session_jti, user_id=auth.user_id)


@router.get("/auth/me", response_model=AuthMeResponse)
async def auth_me(
    auth: AuthContext = Depends(current_auth_context),
    user_service: UserService = Depends(get_user_service),
):
    if auth.external:
        now = datetime.now(UTC)
        role_ids = {role.value: index + 1 for index, role in enumerate(SystemRole)}
        stable_id = int.from_bytes(sha256(str(auth.user_id).encode()).digest()[:4], "big")
        return AuthMeResponse(user={
            "id": stable_id, "tenant_id": auth.tenant_id, "username": auth.username,
            "email": auth.email, "first_name": auth.first_name, "last_name": auth.last_name,
            "role_id": role_ids.get(auth.role, 0), "role_name": auth.role, "status": "active",
            "is_active": True, "last_login": now, "failed_login_attempts": 0,
            "locked_until": None, "created_at": now, "updated_at": now,
        })
    return AuthMeResponse(**(await user_service.me(user_id=auth.user_id)))


@router.get("/auth/config")
async def auth_config():
    return {
        "mode": settings.auth_mode,
        "local_development_only": settings.auth_mode == "local",
        "issuer": settings.oidc_issuer if settings.auth_mode == "oidc" else None,
        "client_id": settings.oidc_client_id if settings.auth_mode == "oidc" else None,
        "audience": settings.oidc_audience if settings.auth_mode == "oidc" else None,
        "pkce_required": settings.auth_mode == "oidc",
    }


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
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
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
        tenant_id=auth.tenant_id,
    )
    return UsersListResponse(rows=[UserRead(**row) for row in rows], count=total, page=safe_page, page_size=safe_page_size)


@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    return UserRead(**(await user_service.get_user(user_id, tenant_id=auth.tenant_id)))


@router.post("/users", response_model=UserRead)
async def create_user(
    request: Request,
    payload: UserCreate,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    ip_address = request.client.host if request.client else None
    return UserRead(
        **(
            await user_service.create_user(
                actor=str(auth.user_id), tenant_id=auth.tenant_id, payload=payload, ip_address=ip_address
            )
        )
    )


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
        **(
            await user_service.update_user(
                actor=str(auth.user_id),
                tenant_id=auth.tenant_id,
                user_id=user_id,
                payload=payload,
                ip_address=ip_address,
            )
        )
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    ip_address = request.client.host if request.client else None
    return await user_service.delete_user(
        actor=str(auth.user_id), tenant_id=auth.tenant_id, user_id=user_id, ip_address=ip_address
    )


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
                tenant_id=auth.tenant_id,
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
        tenant_id=auth.tenant_id,
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
    return await user_service.unlock_user(
        actor=str(auth.user_id), tenant_id=auth.tenant_id, user_id=user_id, ip_address=ip_address
    )


@router.get("/audit-logs", response_model=AuditLogsListResponse)
async def list_audit_logs(
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    auth: AuthContext = Depends(require_roles(SystemRole.ADMINISTRATOR.value)),
    user_service: UserService = Depends(get_user_service),
):
    safe_page = max(1, int(page))
    safe_page_size = max(1, min(int(page_size), 100))
    rows, total = await user_service.list_audit_logs(
        page=safe_page, page_size=safe_page_size, action=action, tenant_id=auth.tenant_id
    )
    return AuditLogsListResponse(rows=rows, count=total, page=safe_page, page_size=safe_page_size)
