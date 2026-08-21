"""A query scoped to one tenant must never return another tenant's rows.

Covers the core alert/incident data model (schema-level tenant_id added in
backend/database/migrations/20260806_core_tenant_isolation.sql) and the
alert-intelligence correlation candidate pool, which must not let a
tenant-A alert correlate against tenant-B's history.

Also covers the api-gateway user-management module (UserRepository), where
Administrator-only endpoints (/users*, /audit-logs) previously checked role
but not tenant_id -- an Administrator token from tenant-a could read,
modify, or delete a user record (or read an audit-log entry) belonging to
any other tenant. See UserRepository.get_user/list_users/list_audit_logs.
"""

from __future__ import annotations

import pytest
from alert_intelligence import AlertIntelligenceAgent
from api_gateway.modules.users.repository import UserRepository
from common.database import RoleRecord, UserRecord
from common.models import Alert, AlertSeverity, Incident, RemediationAction, RemediationStatus
from common.repository import IncidentRepository
from common.repository_interfaces import SqlAlertHistoryRepository


def make_alert(tenant_id: str, service: str = "payments", environment: str = "prod") -> Alert:
    return Alert(
        tenant_id=tenant_id,
        source="prometheus",
        name="PaymentLatencyHigh",
        service=service,
        environment=environment,
        severity=AlertSeverity.WARNING,
        description="payment latency above threshold",
        labels={"deployment": "payments-api"},
    )


@pytest.mark.asyncio
async def test_list_alerts_source_balanced_scopes_by_tenant(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_alert(make_alert("tenant-a"))
        await repo.save_alert(make_alert("tenant-b"))
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        tenant_a_rows = await repo.list_alerts_source_balanced(limit=10, tenant_id="tenant-a")
        tenant_b_rows = await repo.list_alerts_source_balanced(limit=10, tenant_id="tenant-b")
        unscoped_rows = await repo.list_alerts_source_balanced(limit=10)

    assert len(tenant_a_rows) == 1
    assert all(row.get("tenant_id") == "tenant-a" for row in tenant_a_rows)
    assert len(tenant_b_rows) == 1
    assert all(row.get("tenant_id") == "tenant-b" for row in tenant_b_rows)
    # No tenant filter is an explicit opt-in for internal/trusted callers only.
    assert len(unscoped_rows) == 2


@pytest.mark.asyncio
async def test_alert_correlation_candidate_pool_is_tenant_scoped(sqlite_session_factory) -> None:
    repository = SqlAlertHistoryRepository(session_factory=sqlite_session_factory, max_items=100)
    agent = AlertIntelligenceAgent(alert_history_repository=repository, correlation_threshold=0.2)

    tenant_a_first, _ = await agent.process(make_alert("tenant-a"))
    tenant_b_alert, _ = await agent.process(make_alert("tenant-b"))

    # Same service/environment/description as tenant_a_first, but a different
    # tenant: must never correlate or count toward dedup, even though the
    # correlation score would otherwise be a near-perfect match.
    assert tenant_b_alert.correlation_id != tenant_a_first.correlation_id
    assert tenant_b_alert.deduplicated_count == 1


@pytest.mark.asyncio
async def test_actions_table_tenant_id_persists_and_is_isolated(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        incident = Incident(tenant_id="tenant-a", service="payments", title="test incident")
        await repo.save_incident(incident)
        action = RemediationAction(
            tenant_id="tenant-a",
            incident_id=incident.id,
            action_type="rollback_deployment",
            target="payments",
            status=RemediationStatus.SUCCEEDED,
        )
        await repo.save_action(action)
        await session.commit()

    async with sqlite_session_factory() as session:
        from common.database import ActionRecord
        from sqlalchemy import select

        rows = (await session.execute(select(ActionRecord))).scalars().all()

    assert len(rows) == 1
    assert rows[0].tenant_id == "tenant-a"


@pytest.mark.asyncio
async def test_get_user_is_tenant_scoped(sqlite_session_factory) -> None:
    """An Administrator token from tenant-a must not be able to fetch a tenant-b user by id."""
    async with sqlite_session_factory() as session:
        repo = UserRepository(session)
        role = RoleRecord(id=1, name="Administrator", description="Full platform administration", is_system_role=True)
        session.add(role)
        await session.flush()
        user_b = UserRecord(
            id=1,
            tenant_id="tenant-b",
            username="admin-tenant-b",
            email="admin-tenant-b@kaiops.example.com",
            password_hash="unused-hash",
            first_name="Admin",
            last_name="B",
            role_id=role.id,
            status="active",
            is_active=True,
        )
        user_b = await repo.create_user(user_b)
        await session.commit()
        user_b_id = user_b.id

    async with sqlite_session_factory() as session:
        repo = UserRepository(session)
        cross_tenant_lookup = await repo.get_user(user_b_id, tenant_id="tenant-a")
        same_tenant_lookup = await repo.get_user(user_b_id, tenant_id="tenant-b")

    assert cross_tenant_lookup is None
    assert same_tenant_lookup is not None
    assert same_tenant_lookup.id == user_b_id


@pytest.mark.asyncio
async def test_list_users_is_tenant_scoped(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = UserRepository(session)
        role = RoleRecord(id=1, name="Administrator", description="Full platform administration", is_system_role=True)
        session.add(role)
        await session.flush()
        for index, tenant in enumerate(("tenant-a", "tenant-b"), start=1):
            await repo.create_user(
                UserRecord(
                    id=index,
                    tenant_id=tenant,
                    username=f"user-{tenant}",
                    email=f"user-{tenant}@kaiops.example.com",
                    password_hash="unused-hash",
                    first_name="User",
                    last_name=tenant,
                    role_id=role.id,
                    status="active",
                    is_active=True,
                )
            )
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = UserRepository(session)
        tenant_a_rows, tenant_a_total = await repo.list_users(
            page=1, page_size=20, search=None, role_id=None, status=None,
            sort_by="created_at", sort_dir="desc", tenant_id="tenant-a",
        )
        unscoped_rows, unscoped_total = await repo.list_users(
            page=1, page_size=20, search=None, role_id=None, status=None,
            sort_by="created_at", sort_dir="desc", tenant_id=None,
        )

    assert tenant_a_total == 1
    assert all(row.tenant_id == "tenant-a" for row in tenant_a_rows)
    # No tenant filter is an explicit opt-in for internal/trusted callers only.
    assert unscoped_total == 2


@pytest.mark.asyncio
async def test_list_audit_logs_is_tenant_scoped(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = UserRepository(session)
        await repo.add_audit(
            actor="admin-a", action="user.created", resource_type="user", resource_id="1",
            payload={}, tenant_id="tenant-a",
        )
        await repo.add_audit(
            actor="admin-b", action="user.created", resource_type="user", resource_id="2",
            payload={}, tenant_id="tenant-b",
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        repo = UserRepository(session)
        tenant_a_rows, tenant_a_total = await repo.list_audit_logs(
            page=1, page_size=50, action=None, tenant_id="tenant-a"
        )

    assert tenant_a_total == 1
    assert all(row.tenant_id == "tenant-a" for row in tenant_a_rows)
