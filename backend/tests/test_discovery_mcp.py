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
    assert names == {"logs.search", "tickets.search", "code.search", "mysql.search"}


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
