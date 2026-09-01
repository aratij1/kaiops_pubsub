from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "discovery-mcp" / "app.py"
SPEC = importlib.util.spec_from_file_location("discovery_mcp_app", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
module.MCPRequest.model_rebuild(_types_namespace=vars(module))


def test_mcp_lists_read_only_discovery_tools() -> None:
    names = {row["name"] for row in module.TOOLS}
    assert names == {
        "logs.search",
        "tickets.search",
        "code.search",
        "mysql.search",
        "telemetry.search",
        "traces.search",
        "topology.search",
        "dependency-health.search",
        "changes.search",
        "runbooks.search",
        "external.search",
    }


def test_mcp_tools_call_dispatches_every_local_listed_tool_without_unknown_tool_error(monkeypatch, tmp_path) -> None:
    # Regression test: every tool advertised by tools/list that does not
    # depend on live external infrastructure (mysql, docker, jaeger, jira,
    # etc.) must still be routable through the tools/call JSON-RPC dispatch
    # in mcp(), rather than raising "unknown MCP tool". Previously
    # "changes.search" and "runbooks.search" were listed as available tools
    # but were not wired into the explicit if/elif chain in mcp() and only
    # worked via the catch-all _call_tool() branch -- correct on disk, but a
    # stale deployed container running an older pairing of mcp()/_call_tool()
    # silently raised "unknown MCP tool" for these two names, which zeroed
    # out every hypothesis's supporting evidence and, in turn, RCA
    # confidence. This exercises the real HTTP-facing mcp() coroutine
    # end-to-end so a similar omission is caught by the suite instead of
    # only surfacing as a silent zero-confidence RCA investigation.
    monkeypatch.setenv("DISCOVERY_MCP_PLAYBOOKS_FILE", str(Path(__file__).resolve()))
    monkeypatch.setenv("DISCOVERY_MCP_CODE_ROOTS", str(tmp_path))
    monkeypatch.setenv("DISCOVERY_MCP_TICKET_ROOTS", str(tmp_path))
    local_tools = {"code.search", "tickets.search", "changes.search", "runbooks.search"}

    for row in module.TOOLS:
        name = row["name"]
        if name not in local_tools:
            continue
        request = module.MCPRequest(id="1", method="tools/call", params={"name": name, "arguments": {"terms": ["payment"], "limit": 2}})
        response = asyncio.run(module.mcp(request))
        assert "error" not in response, f"{name} tools/call dispatch failed: {response.get('error')}"
        assert response["result"].get("tool", name) is not None


def test_changes_and_runbooks_tools_call_resolve_via_call_tool_fallback() -> None:
    # These two tool names are intentionally NOT given an explicit elif
    # branch in mcp(); they must fall through to the generic _call_tool()
    # dispatcher rather than raising "unknown MCP tool".
    for name in ("changes.search", "runbooks.search"):
        request = module.MCPRequest(id="1", method="tools/call", params={"name": name, "arguments": {"terms": ["payment"], "limit": 2}})
        response = asyncio.run(module.mcp(request))
        assert "error" not in response, f"{name} incorrectly raised: {response.get('error')}"
        assert response["result"]["tool"] == name


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
