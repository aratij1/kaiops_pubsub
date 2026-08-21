from __future__ import annotations

from importlib import util
from pathlib import Path

from common.models import Incident, IncidentStatus


def _load_alert_app():
    path = Path("backend/src/alert-intelligence/app.py")
    spec = util.spec_from_file_location("alert_intelligence_persistence_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load alert-intelligence app")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_incident_domain_supports_every_persisted_lifecycle_status() -> None:
    assert IncidentStatus.APPROVED.value == "approved"
    assert IncidentStatus.RESOLVED.value == "resolved"
    assert IncidentStatus.CANCELLED.value == "cancelled"


def test_persisted_read_model_annotations_are_not_domain_model_fields() -> None:
    module = _load_alert_app()
    payload = {
        "id": "11111111-1111-4111-8111-111111111111",
        "service": "checkout",
        "environment": "prod",
        "severity": "warning",
        "status": "approved",
        "title": "Checkout incident",
        "state": "approved",
        "approval_status": "approved",
        "approval": {"decision": "approved"},
    }

    incident = module._incident_from_persisted_payload(payload)

    assert incident.status == IncidentStatus.APPROVED
    assert "state" not in incident.model_dump()
