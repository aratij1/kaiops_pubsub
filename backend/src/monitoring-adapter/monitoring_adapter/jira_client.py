from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger("monitoring-adapter.jira-client")

# Jira Cloud REST API v2 (not v3) — v3 requires the description field in
# Atlassian Document Format (a structured JSON tree); v2 accepts plain
# text/wiki markup, which is all this integration needs and keeps issue
# creation a single flat payload instead of a rich-text document builder.
_API_VERSION = "2"


class JiraClientError(Exception):
    pass


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str, project_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self._auth = (email, api_token)

    async def create_issue(
        self,
        *,
        summary: str,
        description: str,
        severity: str,
        labels: dict[str, str] | None = None,
    ) -> str:
        """Creates a new Jira issue and returns its key (e.g. "KAI-123")."""
        jira_labels = [f"kaiops-severity-{severity}", "kaiops-auto-created"]
        for key, value in (labels or {}).items():
            safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", f"kaiops-{key}-{value}")[:255]
            if safe:
                jira_labels.append(safe)
        payload: dict[str, Any] = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": summary[:255],
                "description": description,
                "issuetype": {"name": "Bug"},
                "labels": jira_labels,
            }
        }
        async with httpx.AsyncClient(auth=self._auth, timeout=15.0) as client:
            response = await client.post(f"{self.base_url}/rest/api/{_API_VERSION}/issue", json=payload)
        if response.status_code >= 400:
            raise JiraClientError(f"Jira issue creation failed ({response.status_code}): {response.text[:500]}")
        issue_key = str(response.json().get("key") or "")
        if not issue_key:
            raise JiraClientError(f"Jira issue creation returned no key: {response.text[:500]}")
        logger.info("created jira issue %s", issue_key)
        return issue_key

    async def find_open_issue_by_label(self, label: str) -> str | None:
        """Finds a matching open Jira incident so dedup survives local state loss."""
        safe_label = str(label).replace('"', '\\"')
        jql = (
            f'project = "{self.project_key}" AND labels = "{safe_label}" '
            "AND statusCategory != Done ORDER BY updated DESC"
        )
        async with httpx.AsyncClient(auth=self._auth, timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/rest/api/3/search/jql",
                params={"jql": jql, "fields": "key,status", "maxResults": 1},
            )
        if response.status_code >= 400:
            raise JiraClientError(f"Jira search failed ({response.status_code}): {response.text[:500]}")
        issues = response.json().get("issues", []) if isinstance(response.json(), dict) else []
        return str(issues[0].get("key")) if issues and isinstance(issues[0], dict) else None

    async def add_comment(self, issue_key: str, body: str) -> None:
        """Comments on an existing issue — used when a duplicate (same
        fingerprint) alert arrives while the ticket is still open, so
        repeat occurrences are recorded without creating a new ticket."""
        async with httpx.AsyncClient(auth=self._auth, timeout=15.0) as client:
            response = await client.post(
                f"{self.base_url}/rest/api/{_API_VERSION}/issue/{issue_key}/comment",
                json={"body": body},
            )
        if response.status_code >= 400:
            raise JiraClientError(f"Jira comment failed on {issue_key} ({response.status_code}): {response.text[:500]}")
        logger.info("commented on jira issue %s", issue_key)

    async def get_issue_status(self, issue_key: str) -> str:
        """Returns the issue's current status name (e.g. "Open", "Done") —
        used to detect that a linked ticket has since been closed, so the
        next occurrence of the same fingerprint opens a fresh ticket
        instead of commenting on a closed one."""
        async with httpx.AsyncClient(auth=self._auth, timeout=15.0) as client:
            response = await client.get(
                f"{self.base_url}/rest/api/{_API_VERSION}/issue/{issue_key}",
                params={"fields": "status"},
            )
        if response.status_code >= 400:
            raise JiraClientError(f"Jira status lookup failed for {issue_key} ({response.status_code}): {response.text[:500]}")
        fields = response.json().get("fields", {}) if isinstance(response.json(), dict) else {}
        status = fields.get("status", {}) if isinstance(fields.get("status"), dict) else {}
        return str(status.get("name") or "")

    async def list_recent_issues(self, *, limit: int = 25) -> list[dict[str, Any]]:
        """Return recently updated issues for read-only source ingestion."""
        jql = f'project = "{self.project_key}" ORDER BY updated DESC'
        fields = "summary,description,status,priority,reporter,assignee,labels,updated,created"
        async with httpx.AsyncClient(auth=self._auth, timeout=20.0) as client:
            response = await client.get(
                f"{self.base_url}/rest/api/3/search/jql",
                params={"jql": jql, "fields": fields, "maxResults": max(1, min(limit, 100))},
            )
        if response.status_code >= 400:
            raise JiraClientError(f"Jira recent issue search failed ({response.status_code}): {response.text[:500]}")
        payload = response.json()
        issues = payload.get("issues", []) if isinstance(payload, dict) else []
        return [issue for issue in issues if isinstance(issue, dict)]
