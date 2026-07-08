from __future__ import annotations

import json

from common.config import Settings
from common.models import AlertSeverity
from common.orchestration import PolicyEngine, WorkflowEngine


def test_policy_engine_reads_approval_from_external_config(tmp_path) -> None:
    config_path = tmp_path / "orchestration.json"
    config_path.write_text(
        json.dumps(
            {
                "approval_severities": ["warning"],
                "workflow_definitions": {
                    "critical-auto-remediation": {
                        "steps": ["alert-intelligence-agent"],
                        "next_action": "collect-context",
                    },
                    "guided-remediation": {
                        "steps": ["alert-intelligence-agent"],
                        "next_action": "collect-context",
                    },
                    "triage-only": {
                        "steps": ["alert-intelligence-agent"],
                        "next_action": "collect-context",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(ORCHESTRATION_CONFIG_PATH=str(config_path))
    engine = PolicyEngine(settings=settings)

    decision = engine.evaluate(severity=AlertSeverity.WARNING, confidence=0.99)
    assert decision.requires_approval is True
    assert decision.execution_mode == "human-approval"


def test_workflow_engine_reads_message_bus_and_definitions_from_external_config(tmp_path) -> None:
    config_path = tmp_path / "orchestration.json"
    config_path.write_text(
        json.dumps(
            {
                "message_bus": {
                    "dynamic_routing": False,
                    "default_provider": "kafka",
                    "stream_threshold": 25,
                },
                "workflow_definitions": {
                    "critical-auto-remediation": {
                        "steps": ["alert-intelligence-agent", "closure-agent"],
                        "next_action": "collect-context",
                    },
                    "guided-remediation": {
                        "steps": ["alert-intelligence-agent"],
                        "next_action": "collect-context",
                    },
                    "triage-only": {
                        "steps": ["alert-intelligence-agent", "notification-agent"],
                        "next_action": "collect-context",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    settings = Settings(ORCHESTRATION_CONFIG_PATH=str(config_path))
    engine = WorkflowEngine(settings=settings)

    critical_selection = engine.select(severity=AlertSeverity.CRITICAL, stream_count=1)
    warning_selection = engine.select(severity=AlertSeverity.WARNING, stream_count=1)

    assert critical_selection.message_bus_provider == "kafka"
    assert critical_selection.stream_threshold == 25
    assert critical_selection.definition.steps[-1] == "closure-agent"
    assert warning_selection.definition.name == "triage-only"
    assert warning_selection.definition.steps == ["alert-intelligence-agent", "notification-agent"]
