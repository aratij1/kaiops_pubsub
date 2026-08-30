import importlib.util
from pathlib import Path

from ai_workbench_common.models import Context
from common.models import Alert, AlertSeverity, Recommendation

_APP_PATH = Path(__file__).resolve().parents[2] / "ai-workbench" / "src" / "resolution-agent" / "app.py"
_APP_SPEC = importlib.util.spec_from_file_location("readiness_handoff_resolution_app", _APP_PATH)
assert _APP_SPEC and _APP_SPEC.loader
resolution_app = importlib.util.module_from_spec(_APP_SPEC)
_APP_SPEC.loader.exec_module(resolution_app)


def test_catalog_handoff_preserves_evidence_readiness_block() -> None:
    alert = Alert(
        tenant_id="tenant-a",
        source="prometheus",
        name="KaiOpsServiceDown",
        service="kaiops-discovery-mcp",
        environment="prod",
        severity=AlertSeverity.CRITICAL,
        description="service is unreachable",
    )
    context = Context(tenant_id="tenant-a", incident_id=alert.id, alert=alert)
    recommendation = Recommendation(
        tenant_id="tenant-a",
        incident_id=context.incident_id,
        root_cause="Investigation inconclusive",
        confidence=0.38,
        impact="Impact is not established",
        recommended_action="Collect evidence",
        severity=AlertSeverity.CRITICAL,
        rationale="Causal evidence is incomplete",
        commands=[],
        risk="high",
        metadata={
            "rca_analysis": {
                "context_readiness": {"score": 0.38, "ready": False, "source_coverage": 0.25},
            },
            "execution_plan": {
                "execution_ready": False,
                "readiness_blocks": [],
            },
        },
    )

    plan = resolution_app._apply_catalog_plan(recommendation, context)

    assert plan["execution_ready"] is False
    assert any("38% RCA-ready" in reason for reason in plan["readiness_blocks"])
