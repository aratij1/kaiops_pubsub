from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
import jwt
from fastapi import HTTPException

from api_gateway.modules.users.models import SystemRole
from api_gateway.oidc import OidcTokenValidator
from api_gateway.modules.users.repository import UserRepository, run_in_session
from api_gateway.modules.users.schemas import UserCreate, UserUpdate
from common.config import Settings
from common.database import UserRecord


class UserService:
    def __init__(self, *, settings: Settings, session_factory) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.oidc = OidcTokenValidator(settings) if settings.auth_mode == "oidc" else None

    def _password_regex(self) -> re.Pattern[str]:
        return re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{12,}$")

    def validate_password_policy(self, password: str) -> None:
        if not self._password_regex().match(password):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Password must be at least 12 characters and include uppercase, lowercase, number, and special char"
                ),
            )

    def hash_password(self, password: str) -> str:
        self.validate_password_policy(password)
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify_password(self, plain: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
        except (TypeError, ValueError):
            return False

    def _seeded_password_for_user(self, username: str) -> str | None:
        seeded_passwords = {
            "admin": self.settings.admin_user_password,
            "executive": self.settings.executive_user_password,
            "l3user": self.settings.l3_user_password,
            "l2user": self.settings.l2_user_password,
            "l1user": self.settings.l1_user_password,
        }
        return seeded_passwords.get(username.strip().lower())

    def _normalize_local_email(self, username: str, email: str) -> str:
        env = self.settings.environment.strip().lower()
        if env not in {"local", "demo", "test"}:
            return email

        lowered = email.strip().lower()
        if lowered.endswith(".local") or lowered.endswith("@localhost"):
            return f"{username.strip().lower()}@kaiops.example.com"
        return email

    def _coerce_utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # MySQL DATETIME values may be returned as naive objects; treat them as UTC.
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _encode_token(
        self,
        *,
        user_id: int,
        role: str,
        tenant_id: str,
        token_type: str,
        expires_delta: timedelta,
        jwt_id: str,
        session_jti: str,
    ) -> str:
        now = datetime.now(UTC)
        payload = {
            "sub": str(user_id),
            "role": role,
            "tenant_id": tenant_id or "default",
            "type": token_type,
            "jti": jwt_id,
            "sid": session_jti,
            "iat": int(now.timestamp()),
            "exp": int((now + expires_delta).timestamp()),
        }
        return jwt.encode(payload, self.settings.jwt_secret_key, algorithm=self.settings.jwt_algorithm)

    def decode_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, self.settings.jwt_secret_key, algorithms=[self.settings.jwt_algorithm])
            if not isinstance(payload, dict):
                raise HTTPException(status_code=401, detail="Invalid token payload")
            return payload
        except jwt.PyJWTError as exc:
            raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc

    async def decode_access_token(self, token: str) -> dict:
        if self.oidc is not None:
            return await self.oidc.validate(token)
        return self.decode_token(token)

    async def ensure_active_session(self, *, session_jti: str, user_id: int) -> None:
        async def op(repo: UserRepository):
            session = await repo.get_session_by_jti(session_jti)
            if session is None or session.status != "active":
                raise HTTPException(status_code=401, detail="Session is invalid")
            if int(session.user_id) != int(user_id):
                raise HTTPException(status_code=401, detail="Session does not belong to this user")
            session_expiry = self._coerce_utc(session.expiry_time)
            if session_expiry is None or session_expiry < datetime.now(UTC):
                raise HTTPException(status_code=401, detail="Session expired")

        await run_in_session(self.session_factory, op)

    def _user_to_dict(self, user: UserRecord, role_name: str) -> dict:
        normalized_email = self._normalize_local_email(user.username, user.email)
        return {
            "id": user.id,
            "tenant_id": user.tenant_id,
            "username": user.username,
            "email": normalized_email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role_id": user.role_id,
            "role_name": role_name,
            "status": user.status,
            "is_active": user.is_active,
            "last_login": user.last_login,
            "failed_login_attempts": user.failed_login_attempts,
            "locked_until": user.locked_until,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }

    async def bootstrap_defaults(self) -> None:
        is_local_demo = self.settings.environment.strip().lower() in {"local", "demo", "test"}
        role_descriptions = {
            SystemRole.ADMINISTRATOR.value: "Full platform administration",
            SystemRole.EXECUTIVE.value: "Read-only executive analytics",
            SystemRole.L3_ENGINEER.value: "Advanced investigation and approvals",
            SystemRole.L2_ENGINEER.value: "Incident investigation and runbook execution",
            SystemRole.L1_OPERATOR.value: "Alert triage and escalation",
        }

        default_users = [
            (
                "admin",
                "ADMIN_USER_PASSWORD",
                SystemRole.ADMINISTRATOR.value,
                "KaiOps",
                "Admin",
                "admin@kaiops.example.com",
            ),
            (
                "executive",
                "EXECUTIVE_USER_PASSWORD",
                SystemRole.EXECUTIVE.value,
                "KaiOps",
                "Executive",
                "executive@kaiops.example.com",
            ),
            ("l3user", "L3_USER_PASSWORD", SystemRole.L3_ENGINEER.value, "KaiOps", "L3", "l3@kaiops.example.com"),
            ("l2user", "L2_USER_PASSWORD", SystemRole.L2_ENGINEER.value, "KaiOps", "L2", "l2@kaiops.example.com"),
            ("l1user", "L1_USER_PASSWORD", SystemRole.L1_OPERATOR.value, "KaiOps", "L1", "l1@kaiops.example.com"),
        ]

        async def op(repo: UserRepository):
            for role_name, desc in role_descriptions.items():
                await repo.ensure_role(name=role_name, description=desc, is_system_role=True)

            if self.settings.auth_mode != "local":
                return

            for username, env_key, role_name, first_name, last_name, email in default_users:
                role = await repo.get_role_by_name(role_name)
                if role is None:
                    continue
                password = getattr(self.settings, env_key.lower())
                existing = await repo.get_user_by_username(username)
                if existing:
                    if is_local_demo:
                        existing.password_hash = self.hash_password(password)
                        existing.email = self._normalize_local_email(username, email)
                        existing.first_name = first_name
                        existing.last_name = last_name
                        existing.role_id = role.id
                        existing.status = "active"
                        existing.is_active = True
                        existing.locked_until = None
                        existing.failed_login_attempts = 0
                    continue
                user = UserRecord(
                    username=username,
                    email=email,
                    password_hash=self.hash_password(password),
                    first_name=first_name,
                    last_name=last_name,
                    role_id=role.id,
                    status="active",
                    is_active=True,
                )
                await repo.create_user(user)
                await repo.add_audit(
                    actor="system",
                    tenant_id=user.tenant_id,
                    action="user.seeded",
                    resource_type="user",
                    resource_id=str(user.id),
                    payload={"username": username, "role": role_name},
                )

        await run_in_session(self.session_factory, op)

    async def login(self, *, username: str, password: str, ip_address: str | None, device: str | None) -> dict:
        if self.settings.auth_mode != "local" or self.settings.environment.strip().lower() not in {"local", "demo", "test"}:
            raise HTTPException(status_code=404, detail="Local password login is disabled")
        async def op(repo: UserRepository):
            user = await repo.get_user_by_username(username)
            if user is None:
                raise HTTPException(status_code=401, detail="Invalid credentials")

            role = await repo.get_role(user.role_id)
            role_name = role.name if role else "Unknown"

            now = datetime.now(UTC)
            locked_until = self._coerce_utc(user.locked_until)
            if locked_until and locked_until > now:
                raise HTTPException(status_code=423, detail="Account is locked")

            if not user.is_active or user.status.lower() != "active":
                raise HTTPException(status_code=403, detail="Account is disabled")

            password_valid = self.verify_password(password, user.password_hash)
            is_local_demo = self.settings.environment.strip().lower() in {"local", "demo", "test"}
            seeded_password = self._seeded_password_for_user(user.username)
            if not password_valid and is_local_demo and seeded_password and password == seeded_password:
                # Auto-heal stale local seeded hashes to avoid lockouts during upgrades.
                user.password_hash = self.hash_password(seeded_password)
                password_valid = True

            if not password_valid:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= self.settings.auth_failed_login_attempts:
                    user.locked_until = now + timedelta(minutes=self.settings.auth_lock_minutes)
                await repo.add_audit(
                    actor=user.username,
                    tenant_id=user.tenant_id,
                    action="login.failed",
                    resource_type="user",
                    resource_id=str(user.id),
                    payload={"ip_address": ip_address, "attempts": user.failed_login_attempts},
                )
                raise HTTPException(status_code=401, detail="Invalid credentials")

            user.failed_login_attempts = 0
            user.locked_until = None
            user.last_login = now

            access_jti = uuid4().hex
            refresh_jti = uuid4().hex
            access_expires = timedelta(minutes=self.settings.jwt_access_token_minutes)
            refresh_expires = timedelta(minutes=self.settings.jwt_refresh_token_minutes)
            access_token = self._encode_token(
                user_id=user.id,
                role=role_name,
                tenant_id=user.tenant_id,
                token_type="access",
                expires_delta=access_expires,
                jwt_id=access_jti,
                session_jti=refresh_jti,
            )
            refresh_token = self._encode_token(
                user_id=user.id,
                role=role_name,
                tenant_id=user.tenant_id,
                token_type="refresh",
                expires_delta=refresh_expires,
                jwt_id=refresh_jti,
                session_jti=refresh_jti,
            )

            await repo.create_session(
                user_id=user.id,
                jwt_id=refresh_jti,
                login_time=now,
                expiry_time=now + refresh_expires,
                ip_address=ip_address,
                device=device,
                status="active",
            )
            await repo.add_audit(
                actor=user.username,
                tenant_id=user.tenant_id,
                action="login.success",
                resource_type="user",
                resource_id=str(user.id),
                payload={"ip_address": ip_address, "device": device},
            )

            return {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": int(access_expires.total_seconds()),
                "user": self._user_to_dict(user, role_name),
            }

        return await run_in_session(self.session_factory, op)

    async def refresh(self, *, refresh_token: str) -> dict:
        payload = self.decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id = int(payload.get("sub", "0"))
        jti = str(payload.get("jti") or "")
        session_jti = str(payload.get("sid") or jti or "")

        async def op(repo: UserRepository):
            session = await repo.get_session_by_jti(session_jti)
            if session is None or session.status != "active":
                raise HTTPException(status_code=401, detail="Session is invalid")
            session_expiry = self._coerce_utc(session.expiry_time)
            if session_expiry is None or session_expiry < datetime.now(UTC):
                raise HTTPException(status_code=401, detail="Session expired")
            if int(session.user_id) != user_id:
                raise HTTPException(status_code=401, detail="Session does not belong to this user")

            user = await repo.get_user(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            role = await repo.get_role(user.role_id)
            role_name = role.name if role else "Unknown"

            session.status = "rotated"
            session.updated_at = datetime.now(UTC)

            access_jti = uuid4().hex
            new_refresh_jti = uuid4().hex
            access_expires = timedelta(minutes=self.settings.jwt_access_token_minutes)
            refresh_expires = timedelta(minutes=self.settings.jwt_refresh_token_minutes)
            access_token = self._encode_token(
                user_id=user.id,
                role=role_name,
                tenant_id=user.tenant_id,
                token_type="access",
                expires_delta=access_expires,
                jwt_id=access_jti,
                session_jti=new_refresh_jti,
            )
            rotated_refresh_token = self._encode_token(
                user_id=user.id,
                role=role_name,
                tenant_id=user.tenant_id,
                token_type="refresh",
                expires_delta=refresh_expires,
                jwt_id=new_refresh_jti,
                session_jti=new_refresh_jti,
            )

            await repo.create_session(
                user_id=user.id,
                jwt_id=new_refresh_jti,
                login_time=datetime.now(UTC),
                expiry_time=datetime.now(UTC) + refresh_expires,
                ip_address=session.ip_address,
                device=session.device,
                status="active",
            )

            await repo.add_audit(
                actor=user.username,
                tenant_id=user.tenant_id,
                action="token.refresh",
                resource_type="session",
                resource_id=str(session.id),
                payload={"jwt_id": jti, "rotated_to": new_refresh_jti},
            )
            return {
                "access_token": access_token,
                "refresh_token": rotated_refresh_token,
                "expires_in": int(access_expires.total_seconds()),
                "user": self._user_to_dict(user, role_name),
            }

        return await run_in_session(self.session_factory, op)

    async def me(self, *, user_id: int) -> dict:
        async def op(repo: UserRepository):
            user = await repo.get_user(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            role = await repo.get_role(user.role_id)
            role_name = role.name if role else "Unknown"
            return {"user": self._user_to_dict(user, role_name)}

        return await run_in_session(self.session_factory, op)

    async def logout(self, *, session_jti: str, user_id: int) -> dict:
        async def op(repo: UserRepository):
            user = await repo.get_user(user_id)
            await repo.revoke_session(session_jti)
            await repo.add_audit(
                actor=user.username if user else "unknown",
                tenant_id=user.tenant_id if user else "default",
                action="logout",
                resource_type="session",
                resource_id=session_jti,
                payload={},
            )
            return {"status": "ok"}

        return await run_in_session(self.session_factory, op)

    async def list_roles(self) -> list[dict]:
        async def op(repo: UserRepository):
            rows = await repo.list_roles()
            return [
                {
                    "id": item.id,
                    "name": item.name,
                    "description": item.description,
                    "is_system_role": item.is_system_role,
                }
                for item in rows
            ]

        return await run_in_session(self.session_factory, op)

    async def create_user(self, *, actor: str, payload: UserCreate, ip_address: str | None) -> dict:
        self.validate_password_policy(payload.password)

        async def op(repo: UserRepository):
            if await repo.get_user_by_username(payload.username):
                raise HTTPException(status_code=409, detail="Username already exists")
            if await repo.get_user_by_email(payload.email):
                raise HTTPException(status_code=409, detail="Email already exists")

            role = await repo.get_role(payload.role_id)
            if role is None:
                raise HTTPException(status_code=404, detail="Role not found")

            rec = UserRecord(
                tenant_id=payload.tenant_id or "default",
                username=payload.username,
                email=str(payload.email),
                password_hash=self.hash_password(payload.password),
                first_name=payload.first_name,
                last_name=payload.last_name,
                role_id=payload.role_id,
                status=payload.status,
                is_active=payload.is_active,
            )
            rec = await repo.create_user(rec)
            await repo.add_audit(
                actor=actor,
                tenant_id=rec.tenant_id,
                action="user.created",
                resource_type="user",
                resource_id=str(rec.id),
                payload={"ip_address": ip_address},
            )
            return self._user_to_dict(rec, role.name)

        return await run_in_session(self.session_factory, op)

    async def list_users(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        role_id: int | None,
        status: str | None,
        sort_by: str,
        sort_dir: str,
    ) -> tuple[list[dict], int]:
        async def op(repo: UserRepository):
            rows, total = await repo.list_users(
                page=page,
                page_size=page_size,
                search=search,
                role_id=role_id,
                status=status,
                sort_by=sort_by,
                sort_dir=sort_dir,
            )
            role_map = {role.id: role.name for role in await repo.list_roles()}
            return [self._user_to_dict(item, role_map.get(item.role_id, "Unknown")) for item in rows], total

        return await run_in_session(self.session_factory, op)

    async def get_user(self, user_id: int) -> dict:
        async def op(repo: UserRepository):
            user = await repo.get_user(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            role = await repo.get_role(user.role_id)
            return self._user_to_dict(user, role.name if role else "Unknown")

        return await run_in_session(self.session_factory, op)

    async def update_user(self, *, actor: str, user_id: int, payload: UserUpdate, ip_address: str | None) -> dict:
        async def op(repo: UserRepository):
            user = await repo.get_user(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            old = self._user_to_dict(user, (await repo.get_role(user.role_id)).name if await repo.get_role(user.role_id) else "Unknown")

            if payload.email is not None and str(payload.email) != user.email:
                existing = await repo.get_user_by_email(str(payload.email))
                if existing and existing.id != user.id:
                    raise HTTPException(status_code=409, detail="Email already exists")
                user.email = str(payload.email)
            if payload.first_name is not None:
                user.first_name = payload.first_name
            if payload.last_name is not None:
                user.last_name = payload.last_name
            if payload.role_id is not None:
                role = await repo.get_role(payload.role_id)
                if role is None:
                    raise HTTPException(status_code=404, detail="Role not found")
                user.role_id = payload.role_id
            if payload.status is not None:
                user.status = payload.status
            if payload.is_active is not None:
                user.is_active = payload.is_active

            role = await repo.get_role(user.role_id)
            updated = self._user_to_dict(user, role.name if role else "Unknown")
            await repo.add_audit(
                actor=actor,
                tenant_id=user.tenant_id,
                action="user.updated",
                resource_type="user",
                resource_id=str(user.id),
                payload={"old_value": old, "new_value": updated, "ip_address": ip_address},
            )
            return updated

        return await run_in_session(self.session_factory, op)

    async def set_user_status(
        self,
        *,
        actor: str,
        user_id: int,
        status: str,
        is_active: bool,
        ip_address: str | None,
    ) -> dict:
        async def op(repo: UserRepository):
            user = await repo.get_user(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            user.status = status
            user.is_active = is_active
            role = await repo.get_role(user.role_id)
            updated = self._user_to_dict(user, role.name if role else "Unknown")
            await repo.add_audit(
                actor=actor,
                tenant_id=user.tenant_id,
                action="user.status.updated",
                resource_type="user",
                resource_id=str(user.id),
                payload={"status": status, "is_active": is_active, "ip_address": ip_address},
            )
            return updated

        return await run_in_session(self.session_factory, op)

    async def reset_password(self, *, actor: str, user_id: int, new_password: str, ip_address: str | None) -> dict:
        self.validate_password_policy(new_password)

        async def op(repo: UserRepository):
            user = await repo.get_user(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            user.password_hash = self.hash_password(new_password)
            user.password_changed_at = datetime.now(UTC)
            await repo.add_audit(
                actor=actor,
                tenant_id=user.tenant_id,
                action="user.password.reset",
                resource_type="user",
                resource_id=str(user.id),
                payload={"ip_address": ip_address},
            )
            return {"status": "ok"}

        return await run_in_session(self.session_factory, op)

    async def unlock_user(self, *, actor: str, user_id: int, ip_address: str | None) -> dict:
        async def op(repo: UserRepository):
            user = await repo.get_user(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            user.failed_login_attempts = 0
            user.locked_until = None
            await repo.add_audit(
                actor=actor,
                tenant_id=user.tenant_id,
                action="user.unlocked",
                resource_type="user",
                resource_id=str(user.id),
                payload={"ip_address": ip_address},
            )
            return {"status": "ok"}

        return await run_in_session(self.session_factory, op)

    async def delete_user(self, *, actor: str, user_id: int, ip_address: str | None) -> dict:
        async def op(repo: UserRepository):
            user = await repo.get_user(user_id)
            if user is None:
                raise HTTPException(status_code=404, detail="User not found")
            await repo.session.delete(user)
            await repo.add_audit(
                actor=actor,
                tenant_id=user.tenant_id,
                action="user.deleted",
                resource_type="user",
                resource_id=str(user_id),
                payload={"ip_address": ip_address},
            )
            return {"status": "ok"}

        return await run_in_session(self.session_factory, op)

    async def list_audit_logs(self, *, page: int, page_size: int, action: str | None) -> tuple[list[dict], int]:
        async def op(repo: UserRepository):
            rows, total = await repo.list_audit_logs(page=page, page_size=page_size, action=action)
            payload_rows = [
                {
                    "id": str(row.id),
                    "actor": row.actor,
                    "action": row.action,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "payload": row.payload or {},
                    "created_at": row.created_at,
                }
                for row in rows
            ]
            return payload_rows, total

        return await run_in_session(self.session_factory, op)
