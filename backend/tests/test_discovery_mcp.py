from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "discovery-mcp" / "app.py"
SPEC = importlib.util.spec_from_file_location("discovery_mcp_app", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_mcp_lists_read_only_discovery_tools() -> None:
    names = {row["name"] for row in module.TOOLS}
    assert names == {
        "logs.search",
        "tickets.search",
        "code.search",
        "mysql.search",
        "telemetry.search",
        "external.search",
    }


def test_code_tool_returns_cited_redacted_evidence(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "service.py"
    source.write_text("payment-gateway failed password=super-secret\n", encoding="utf-8")
    monkeypatch.setenv("DISCOVERY_MCP_CODE_ROOTS", str(tmp_path))

    result = module._call_tool("code.search", {"terms": ["payment-gateway"], "limit": 4})

    assert result["result_count"] == 1
    row = result["evidence"][0]
    assert row["evidence_id"].startswith("CODE-")
    assert row["uri"].startswith("code://")
    assert "super-secret" not in row["snippet"]
    assert "[REDACTED]" in row["snippet"]


def test_ticket_tool_searches_jira_csv(tmp_path: Path, monkeypatch) -> None:
    ticket = tmp_path / "jira.csv"
    ticket.write_text("key,summary,service\nOPS-9,Pod crash loop,user-profile\n", encoding="utf-8")
    monkeypatch.setenv("DISCOVERY_MCP_TICKET_ROOTS", str(tmp_path))

    result = module._call_tool("tickets.search", {"terms": ["user-profile"], "limit": 4})

    assert result["result_count"] == 1
    assert result["evidence"][0]["evidence_id"].startswith("TICKET-")


def test_code_search_uses_service_path_as_relevance_signal(tmp_path: Path, monkeypatch) -> None:
    service_root = tmp_path / "otel-collector"
    service_root.mkdir()
    (service_root / "collector-config.yaml").write_text("receivers:\n  otlp:\n", encoding="utf-8")
    monkeypatch.setenv("DISCOVERY_MCP_CODE_ROOTS", str(tmp_path))

    result = module._call_tool("code.search", {"terms": ["otel-collector"], "limit": 4})

    assert result["result_count"] > 0
    assert "otel-collector" in result["evidence"][0]["uri"]


def test_code_search_prioritizes_kaiops_service_alias_directory(tmp_path: Path, monkeypatch) -> None:
    backend_root = tmp_path / "backend" / "src"
    service_root = backend_root / "context-agent"
    service_root.mkdir(parents=True)
    (service_root / "app.py").write_text("def collect_context():\n    return 'context'\n", encoding="utf-8")
    projects = tmp_path / "projects.json"
    projects.write_text(
        '{"projects":{"kaiops":{"aliases":["kaiops-platform"],"code_roots":["%s"]}}}'
        % backend_root.as_posix(),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCOVERY_MCP_PROJECTS_FILE", str(projects))

    roots = module._code_roots({"project": "kaiops-platform", "service": "kaiops-context-agent"})

    assert roots[0] == service_root


def test_code_search_discards_volatile_alert_tokens() -> None:
    terms = module._code_search_terms(
        {
            "service": "monitoring-adapter",
            "terms": [
                "2026-07-28T13:09:12Z",
                "9a3726be-7e80-4521-8166-5f81f41ae4f1",
                "0123456789abcdef0123456789abcdef",
                "failed",
                "log_ingestion.py",
                "monitoring-adapter",
            ],
        }
    )

    assert terms == ["monitoring-adapter", "log_ingestion.py"]


def test_log_diagnosis_extracts_structured_signals() -> None:
    evidence = [
        module._evidence(
            "log",
            Path("runtime/service.log"),
            1,
            "dependency connection refused after request timeout",
            ["service"],
        )
    ]

    diagnosis = module._log_diagnosis(evidence, "api-gateway")

    assert diagnosis is not None
    assert diagnosis["signal_type"] == "log_diagnosis"
    assert {"connection_refused", "timeout"} <= set(diagnosis["diagnostic_signals"])
    assert diagnosis["supporting_evidence"] == [evidence[0]["evidence_id"]]


def test_docker_multiplexed_log_stream_is_decoded() -> None:
    line = b"2026-07-26T06:18:49Z Failed to export metrics: Deadline Exceeded\n"
    frame = bytes([2, 0, 0, 0]) + len(line).to_bytes(4, "big") + line

    assert module._decode_docker_log_stream(frame) == line.decode()
