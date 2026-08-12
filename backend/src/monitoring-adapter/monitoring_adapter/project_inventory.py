from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any


def alert_application_candidates(row: dict[str, Any]) -> list[str]:
    labels = row.get("labels", {}) if isinstance(row.get("labels"), dict) else {}
    candidates = [
        row.get("application"), row.get("project"), row.get("project_name"), row.get("service"),
        labels.get("application"), labels.get("project"), labels.get("project_name"),
        labels.get("deployment"), labels.get("namespace"), labels.get("job"),
    ]
    return [str(item or "").strip() for item in candidates if str(item or "").strip()]


def is_displayable_alert_application(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized or "/" in normalized or ":" in normalized:
        return False
    token = normalized.casefold()
    if any(marker in token for marker in ("smoke-test", "ux-test", "ux test", "e2e-", "-e2e", "onboarding-test")):
        return False
    if re.match(r"^(test\d*|demo(?:-|$))", normalized, re.IGNORECASE):
        return False
    if re.match(r"^(unknown|default|prod|dev|staging|warning|critical|high|info)$", normalized, re.IGNORECASE):
        return False
    return not re.match(
        r"^(prometheus|alertmanager|blackbox|node-exporter|mysql|redis|rabbitmq|kafka|zookeeper)$",
        normalized,
        re.IGNORECASE,
    )


def collect_alert_applications(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        for candidate in alert_application_candidates(row):
            key = candidate.casefold()
            if not is_displayable_alert_application(candidate) or key in seen:
                continue
            seen.add(key)
            result.append(candidate)
    return result


async def record_successful_test_alert(repo: Any, *, integration_id: str, provider: str, alert_id: str) -> None:
    now = datetime.now(timezone.utc)
    await repo.save_monitoring_connection_health(
        health_id=str(uuid.uuid4()), integration_id=integration_id, provider=provider, status="healthy",
        connectivity_ok=True, authentication_ok=True, webhook_ok=True, last_received_alert_at=now,
        last_successful_test_at=now, rate_limit_remaining=None,
        payload={"test_alert_id": alert_id, "test_alert_processed": True},
    )


def activation_readiness_blockers(integration: dict[str, Any], health: dict[str, Any] | None) -> list[str]:
    validation = integration.get("validation_payload") if isinstance(integration.get("validation_payload"), dict) else {}
    blockers = []
    if not bool(validation.get("valid")):
        blockers.append("connection validation has not passed")
    if not health or not bool((health.get("payload") or {}).get("test_alert_processed")):
        blockers.append("an end-to-end test alert has not completed")
    return blockers
