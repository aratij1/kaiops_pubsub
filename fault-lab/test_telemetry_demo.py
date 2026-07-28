from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("fault_lab.py")
SPEC = importlib.util.spec_from_file_location("fault_lab", MODULE_PATH)
assert SPEC and SPEC.loader
fault_lab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fault_lab)


def make_lab() -> fault_lab.FaultLab:
    return fault_lab.FaultLab(
        Path(__file__).parent / "data" / "kaiops_jira_1000_tickets.csv",
        tick_seconds=60,
    )


def stop_lab(lab: fault_lab.FaultLab) -> None:
    lab.stop_event.set()
    lab.worker.join(timeout=1)


def test_telemetry_fault_keeps_workload_available() -> None:
    lab = make_lab()
    try:
        ok, _ = lab.start_fault("kaiops-scenario-43", duration=30)
        assert ok

        status, body, _ = lab.exercise("datadog-agent")

        assert status == 200
        assert body["status"] == "ok"
        assert body["warning"] == "telemetry degraded"
    finally:
        stop_lab(lab)


def test_fault_event_contains_agent_evidence_and_resolution_context() -> None:
    lab = make_lab()
    try:
        ok, _ = lab.start_fault("kaiops-scenario-42", duration=30)
        assert ok

        event = lab.events[-1]

        assert event["scenario_id"] == "kaiops-scenario-42"
        assert event["root_cause"]
        assert event["resolution_steps"]
        assert event["validation"]
        assert event["runbook_id"]
        assert event["trace_id"]
    finally:
        stop_lab(lab)


def test_telemetry_demo_scenarios_are_bounded_nonfatal_profiles() -> None:
    lab = make_lab()
    try:
        assert fault_lab.TELEMETRY_DEMO_SCENARIOS == (
            "kaiops-scenario-42",
            "kaiops-scenario-43",
            "kaiops-scenario-22",
        )
        behaviors = {
            lab.scenarios[scenario_id]["profile"]["behavior"]
            for scenario_id in fault_lab.TELEMETRY_DEMO_SCENARIOS
        }
        assert behaviors == {"telemetry", "backlog"}
    finally:
        stop_lab(lab)
