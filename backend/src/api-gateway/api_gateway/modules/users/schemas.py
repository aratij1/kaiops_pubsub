from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RoleRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    description: str | None = None
    is_system_role: bool


class UserRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    username: str
    email: EmailStr
    first_name: str
    last_name: str
    role_id: int
    role_name: str
    status: str
    is_active: bool
    last_login: datetime | None = None
    failed_login_attempts: int
    locked_until: datetime | None = None
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=12, max_length=255)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    role_id: int
    status: str = Field(default="active", max_length=32)
    is_active: bool = True


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    role_id: int | None = None
    status: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None


class UserStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(max_length=32)
    is_active: bool


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=12, max_length=255)


class AuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str
    device: str | None = None


class AuthRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class AuthTokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead


class AuthMeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: UserRead


class UsersListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[UserRead]
    count: int
    page: int
    page_size: int


class AuditLogRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    payload: dict
    created_at: datetime


class AuditLogsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[AuditLogRead]
    count: int
    page: int
    page_size: int
