import pytest
from api_gateway.modules.users.schemas import UserUpdate
from api_gateway.modules.users.service import UserService
from common.config import Settings
from common.database import RoleRecord, UserRecord
from fastapi import HTTPException


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


def test_password_policy_accepts_strong_password() -> None:
    svc = _service()
    hashed = svc.hash_password("Strong@Pass123")
    assert isinstance(hashed, str)
    assert svc.verify_password("Strong@Pass123", hashed)


def test_jwt_encode_decode_round_trip() -> None:
    svc = _service()
    token = svc._encode_token(
        user_id=7,
        role="Administrator",
        tenant_id="acme",
        token_type="access",
        expires_delta=__import__("datetime").timedelta(minutes=5),
        jwt_id="abc123",
        session_jti="session-123",
    )
    payload = svc.decode_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "Administrator"
    assert payload["tenant_id"] == "acme"
    assert payload["type"] == "access"
    assert payload["sid"] == "session-123"


class _FakeLoginRepo:
    def __init__(self, password_hash: str) -> None:
        self.audits: list[dict] = []
        self.sessions: list[dict] = []
        self.user = UserRecord(
            id=1,
            username="admin",
            email="admin@kaiops.local",
            password_hash=password_hash,
            first_name="KaiOps",
            last_name="Admin",
            role_id=1,
            status="active",
            is_active=True,
        )
        self.role = RoleRecord(id=1, name="Administrator", description="Full platform administration", is_system_role=True)

    async def get_user_by_username(self, username: str):
        return self.user if username == "admin" else None

    async def get_role(self, role_id: int):
        return self.role if role_id == 1 else None

    async def add_audit(self, **kwargs):
        self.audits.append(kwargs)

    async def create_session(self, **kwargs):
        self.sessions.append(kwargs)


class _FakeSession:
    def __init__(self, *, session_id: int = 1, user_id: int = 1, jwt_id: str = "refresh-jti", status: str = "active") -> None:
        self.id = session_id
        self.user_id = user_id
        self.jwt_id = jwt_id
        self.status = status
        self.ip_address = "127.0.0.1"
        self.device = "React UI"
        self.expiry_time = __import__("datetime").datetime.now(__import__("datetime").UTC) + __import__("datetime").timedelta(minutes=30)
        self.updated_at = None


class _FakeSessionRepo(_FakeLoginRepo):
    def __init__(self, password_hash: str) -> None:
        super().__init__(password_hash)
        self.session_by_jti: dict[str, _FakeSession] = {}
        self.revoked: list[str] = []

    async def get_user(self, user_id: int):
        return self.user if user_id == self.user.id else None

    async def get_session_by_jti(self, jwt_id: str):
        return self.session_by_jti.get(jwt_id)

    async def revoke_session(self, jwt_id: str):
        self.revoked.append(jwt_id)
        session = self.session_by_jti.get(jwt_id)
        if session is not None:
            session.status = "revoked"


def test_seeded_admin_login(monkeypatch) -> None:
    svc = _service()
    password = "Admin@123456"
    fake_repo = _FakeLoginRepo(svc.hash_password(password))

    async def fake_run_in_session(factory, fn):
        return await fn(fake_repo)

    monkeypatch.setattr("api_gateway.modules.users.service.run_in_session", fake_run_in_session)

    result = __import__("asyncio").run(
        svc.login(username="admin", password=password, ip_address=None, device="React UI")
    )

    assert result["user"]["username"] == "admin"
    assert result["user"]["role_name"] == "Administrator"
    assert result["access_token"]
    assert fake_repo.sessions


def test_seeded_admin_login_repairs_malformed_hash(monkeypatch) -> None:
    svc = _service()
    password = "Admin@123456"
    fake_repo = _FakeLoginRepo("legacy-hash-format")

    async def fake_run_in_session(factory, fn):
        return await fn(fake_repo)

    monkeypatch.setattr("api_gateway.modules.users.service.run_in_session", fake_run_in_session)

    result = __import__("asyncio").run(
        svc.login(username="admin", password=password, ip_address=None, device="React UI")
    )

    assert result["user"]["username"] == "admin"
    assert result["access_token"]
    assert fake_repo.sessions
    assert svc.verify_password(password, fake_repo.user.password_hash)


def test_seeded_admin_login_normalizes_reserved_email_for_response(monkeypatch) -> None:
    svc = _service()
    password = "Admin@123456"
    fake_repo = _FakeLoginRepo(svc.hash_password(password))
    fake_repo.user.email = "admin@kaiops.local"

    async def fake_run_in_session(factory, fn):
        return await fn(fake_repo)

    monkeypatch.setattr("api_gateway.modules.users.service.run_in_session", fake_run_in_session)

    __import__("asyncio").run(svc.login(username="admin", password=password, ip_address=None, device="React UI"))
    normalized = svc._user_to_dict(fake_repo.user, "Administrator")

    assert normalized["email"] == "admin@kaiops.example.com"


def test_ensure_active_session_rejects_revoked_session(monkeypatch) -> None:
    svc = _service()
    fake_repo = _FakeSessionRepo(svc.hash_password("Admin@123456"))
    fake_repo.session_by_jti["refresh-jti"] = _FakeSession(status="revoked")

    async def fake_run_in_session(factory, fn):
        return await fn(fake_repo)

    monkeypatch.setattr("api_gateway.modules.users.service.run_in_session", fake_run_in_session)

    try:
        __import__("asyncio").run(svc.ensure_active_session(session_jti="refresh-jti", user_id=1))
        assert False, "Expected ensure_active_session to reject revoked sessions"
    except HTTPException as exc:
        assert exc.status_code == 401


def test_refresh_rotates_session_and_tokens(monkeypatch) -> None:
    svc = _service()
    fake_repo = _FakeSessionRepo(svc.hash_password("Admin@123456"))
    fake_repo.session_by_jti["refresh-jti"] = _FakeSession(jwt_id="refresh-jti", status="active")
    refresh_token = svc._encode_token(
        user_id=1,
        role="Administrator",
        tenant_id="default",
        token_type="refresh",
        expires_delta=__import__("datetime").timedelta(minutes=30),
        jwt_id="refresh-jti",
        session_jti="refresh-jti",
    )

    async def fake_run_in_session(factory, fn):
        return await fn(fake_repo)

    monkeypatch.setattr("api_gateway.modules.users.service.run_in_session", fake_run_in_session)

    result = __import__("asyncio").run(svc.refresh(refresh_token=refresh_token))
    rotated_payload = svc.decode_token(result["refresh_token"])
    access_payload = svc.decode_token(result["access_token"])

    assert fake_repo.session_by_jti["refresh-jti"].status == "rotated"
    assert len(fake_repo.sessions) == 1
    assert rotated_payload["jti"] != "refresh-jti"
    assert rotated_payload["sid"] == rotated_payload["jti"]
    assert access_payload["sid"] == rotated_payload["jti"]


def test_logout_revokes_bound_session(monkeypatch) -> None:
    svc = _service()
    fake_repo = _FakeSessionRepo(svc.hash_password("Admin@123456"))
    fake_repo.session_by_jti["refresh-jti"] = _FakeSession(jwt_id="refresh-jti", status="active")

    async def fake_run_in_session(factory, fn):
        return await fn(fake_repo)

    monkeypatch.setattr("api_gateway.modules.users.service.run_in_session", fake_run_in_session)

    result = __import__("asyncio").run(svc.logout(session_jti="refresh-jti", user_id=1))

    assert result["status"] == "ok"
    assert fake_repo.revoked == ["refresh-jti"]
    assert fake_repo.session_by_jti["refresh-jti"].status == "revoked"


def _service_with_db(session_factory) -> UserService:
    settings = Settings(
        DATABASE_ENABLED=True,
        JWT_SECRET_KEY="test-secret-key-that-is-at-least-32-bytes",
        ADMIN_USER_PASSWORD="Admin@123456",
        EXECUTIVE_USER_PASSWORD="Executive@123456",
        L3_USER_PASSWORD="L3Engineer@123456",
        L2_USER_PASSWORD="L2Engineer@123456",
        L1_USER_PASSWORD="L1Operator@123456",
    )
    return UserService(settings=settings, session_factory=session_factory)


_next_seed_id = iter(range(1, 10_000))


async def _seed_user(sqlite_session_factory, *, username: str, email: str) -> int:
    from api_gateway.modules.users.repository import UserRepository, run_in_session

    async def op(repo: UserRepository):
        role = await repo.get_role_by_name("Administrator")
        if role is None:
            role = RoleRecord(id=1, name="Administrator", description="Full platform administration", is_system_role=True)
            repo.session.add(role)
            await repo.session.flush()
        user = UserRecord(
            id=next(_next_seed_id),
            tenant_id="default",
            username=username,
            email=email,
            password_hash="unused-hash",
            first_name="Original",
            last_name="Name",
            role_id=role.id,
            status="active",
            is_active=True,
        )
        created = await repo.create_user(user)
        return created.id

    return await run_in_session(sqlite_session_factory, op)


@pytest.mark.asyncio
async def test_update_user_changes_username(sqlite_session_factory) -> None:
    """Regression test: editing a user's username previously had no effect
    at all -- the field was read-only in the UI, the frontend never sent it,
    and UserUpdate had no username field (extra="forbid" would have
    rejected it anyway). This proves the service layer now actually
    persists a username change end to end.
    """
    svc = _service_with_db(sqlite_session_factory)
    user_id = await _seed_user(sqlite_session_factory, username="old-name", email="old-name@kaiops.example.com")

    updated = await svc.update_user(
        actor="admin",
        tenant_id="default",
        user_id=user_id,
        payload=UserUpdate(username="new-name"),
        ip_address=None,
    )

    assert updated["username"] == "new-name"

    refetched = await svc.get_user(user_id, tenant_id="default")
    assert refetched["username"] == "new-name"


@pytest.mark.asyncio
async def test_update_user_writes_json_safe_audit_payload(sqlite_session_factory) -> None:
    """Regression test: update_user's audit write previously embedded the
    raw before/after user dicts -- including bare datetime fields like
    created_at/last_login -- directly into a JSON column, which raises a
    TypeError from json.dumps on every single user edit (any field, not
    just username). This proves the persisted audit_logs row actually
    contains JSON-serializable (string) datetimes, matching what a real
    MySQL/SQLite JSON column round-trips.
    """
    import json

    from common.database import AuditLogRecord
    from sqlalchemy import select

    svc = _service_with_db(sqlite_session_factory)
    user_id = await _seed_user(sqlite_session_factory, username="audited-user", email="audited@kaiops.example.com")

    await svc.update_user(
        actor="admin",
        tenant_id="default",
        user_id=user_id,
        payload=UserUpdate(first_name="Updated"),
        ip_address="127.0.0.1",
    )

    async with sqlite_session_factory() as session:
        rows = (
            await session.execute(select(AuditLogRecord).where(AuditLogRecord.action == "user.updated"))
        ).scalars().all()

    assert len(rows) == 1
    payload = rows[0].payload
    # Round-tripping through json.dumps here is the same operation the real
    # JSON column driver performs on write -- if any field were still a raw
    # datetime, this would raise TypeError exactly like the original bug.
    json.dumps(payload)
    assert isinstance(payload["old_value"]["created_at"], str)
    assert isinstance(payload["new_value"]["created_at"], str)
    assert payload["new_value"]["first_name"] == "Updated"


@pytest.mark.asyncio
async def test_update_user_rejects_duplicate_username(sqlite_session_factory) -> None:
    svc = _service_with_db(sqlite_session_factory)
    await _seed_user(sqlite_session_factory, username="taken-name", email="taken@kaiops.example.com")
    user_id = await _seed_user(sqlite_session_factory, username="other-name", email="other@kaiops.example.com")

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_user(
            actor="admin",
            tenant_id="default",
            user_id=user_id,
            payload=UserUpdate(username="taken-name"),
            ip_address=None,
        )
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_update_user_leaves_username_unchanged_when_omitted(sqlite_session_factory) -> None:
    """UserUpdate.username is optional -- omitting it (the existing edit
    flows for email/role/status/etc. that don't touch the name) must not
    accidentally clear or alter the stored username."""
    svc = _service_with_db(sqlite_session_factory)
    user_id = await _seed_user(sqlite_session_factory, username="stays-the-same", email="stays@kaiops.example.com")

    updated = await svc.update_user(
        actor="admin",
        tenant_id="default",
        user_id=user_id,
        payload=UserUpdate(first_name="Renamed"),
        ip_address=None,
    )

    assert updated["username"] == "stays-the-same"
    assert updated["first_name"] == "Renamed"
