from datetime import UTC, datetime

import httpx
import pytest
from monitoring_adapter.jira_client import JiraClient


@pytest.mark.asyncio
async def test_jira_client_uses_configured_project_issue_type_and_basic_auth(monkeypatch):
    requests = []

    async def request(self, method, url, **kwargs):
        requests.append((method, url, kwargs))
        return httpx.Response(201, json={"key": "KAN-42"}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    client = JiraClient(
        "https://kaiops-test.atlassian.net", "service@example.com", "secret-token", "KAN", "Bug"
    )
    key = await client.create_issue(
        summary="Checkout incident", description="Bound incident details", severity="critical"
    )
    assert key == "KAN-42"
    payload = requests[0][2]["json"]["fields"]
    assert payload["project"] == {"key": "KAN"}
    assert payload["issuetype"] == {"name": "Bug"}
    assert client._auth == ("service@example.com", "secret-token")


@pytest.mark.asyncio
async def test_jira_reconciliation_uses_overlapping_ordered_cursor(monkeypatch):
    captured = {}

    async def request(self, method, url, **kwargs):
        captured.update(kwargs["params"])
        return httpx.Response(200, json={"issues": []}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx.AsyncClient, "request", request)
    client = JiraClient("https://kaiops-test.atlassian.net", "svc@example.com", "token", "KAN")
    await client.search_updated_issues(updated_since=datetime(2026, 8, 30, 10, 5, tzinfo=UTC))
    assert 'project = "KAN"' in captured["jql"]
    assert 'updated >= "2026-08-30 10:05"' in captured["jql"]
    assert "ORDER BY updated ASC, key ASC" in captured["jql"]
