from __future__ import annotations

import pytest
from common.models import Alert, AlertSeverity
from common.repository import IncidentRepository


@pytest.mark.asyncio
async def test_source_balanced_alerts_reserve_inactive_low_volume_sources(sqlite_session_factory) -> None:
    async with sqlite_session_factory() as session:
        repo = IncidentRepository(session)
        email = Alert(
            source="email",
            name="Resolved email incident",
            service="checkout",
            severity=AlertSeverity.INFO,
            description="The email incident is resolved",
            labels={"alert_status": "resolved", "ingestion_channel": "email"},
        )
        await repo.save_alert(email)
        for index in range(10):
            await repo.save_alert(
                Alert(
                    source="logs",
                    name=f"Log burst {index}",
                    service="checkout",
                    severity=AlertSeverity.WARNING,
                    description="Repeated log error",
                    labels={"alert_status": "firing", "ingestion_channel": "log"},
                )
            )
        await repo.save_alert(
            Alert(
                source="jira",
                name="Inactive Jira issue",
                service="checkout",
                severity=AlertSeverity.INFO,
                description="Ticket moved to inactive",
                labels={"alert_status": "inactive", "ingestion_channel": "ticket"},
            )
        )
        await session.commit()

        rows = await repo.list_alerts_source_balanced(limit=3)

    assert {row["source"] for row in rows} == {"email", "logs", "jira"}
    assert next(row for row in rows if row["source"] == "email")["labels"]["alert_status"] == "resolved"
    assert next(row for row in rows if row["source"] == "jira")["labels"]["alert_status"] == "inactive"
