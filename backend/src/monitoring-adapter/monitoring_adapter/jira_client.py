from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
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


def jira_rich_text_to_plain_text(value: Any) -> str:
    """Flatten Jira ADF into readable text while preserving paragraph breaks."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(filter(None, (jira_rich_text_to_plain_text(item) for item in value))).strip()
    if not isinstance(value, dict):
        return str(value).strip()

    node_type = str(value.get("type") or "").strip().lower()
    if node_type == "text":
        return str(value.get("text") or "").strip()
    if node_type == "hardbreak":
        return "\n"

    children = value.get("content") if isinstance(value.get("content"), list) else []
    child_text = [jira_rich_text_to_plain_text(item) for item in children]
    separator = "\n" if node_type in {"doc", "heading", "paragraph", "bulletlist", "orderedlist", "listitem"} else " "
    return separator.join(item for item in child_text if item).strip()


class JiraClient:
    def __init__(
        self,
        base_url: str,
        email: str,
        api_token: str,
        project_key: str,
        issue_type: str = "Bug",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self.issue_type = issue_type
        self._auth = (email, api_token)

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        async with httpx.AsyncClient(auth=self._auth, timeout=20.0) as client:
            response = await client.request(method, f"{self.base_url}{path}", **kwargs)
        if response.status_code >= 400:
            raise JiraClientError(
                f"Jira {method} {path} failed ({response.status_code}): {response.text[:500]}"
            )
        return response

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
                "issuetype": {"name": self.issue_type},
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

    async def create_or_update_incident(
        self,
        *,
        incident_id: str,
        summary: str,
        description: str,
        severity: str,
        labels: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        binding_label = f"kaiops-incident-{incident_id}"
        existing = await self.find_open_issue_by_label(binding_label)
        if existing:
            await self.add_comment(existing, description)
            return existing, "updated"
        issue_key = await self.create_issue(
            summary=summary,
            description=description,
            severity=severity,
            labels={**(labels or {}), "incident": incident_id},
        )
        return issue_key, "created"

    async def assign_issue(self, issue_key: str, *, account_id: str) -> None:
        await self._request(
            "PUT",
            f"/rest/api/3/issue/{issue_key}/assignee",
            json={"accountId": account_id},
        )

    async def transition_issue(self, issue_key: str, *, transition_id: str) -> None:
        await self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/transitions",
            json={"transition": {"id": transition_id}},
        )

    async def get_issue(self, issue_key: str) -> dict[str, Any]:
        response = await self._request(
            "GET",
            f"/rest/api/3/issue/{issue_key}",
            params={
                "fields": "summary,status,assignee,labels,updated,resolution,project,issuetype"
            },
        )
        payload = response.json()
        if not isinstance(payload, dict):
            raise JiraClientError(f"Jira issue {issue_key} returned an invalid payload")
        return payload

    async def search_updated_issues(
        self,
        *,
        updated_since: datetime,
        after_issue_key: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        since = updated_since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        boundary = f' AND key > "{after_issue_key}"' if after_issue_key else ""
        jql = (
            f'project = "{self.project_key}" AND updated >= "{since}"{boundary} '
            "ORDER BY updated ASC, key ASC"
        )
        response = await self._request(
            "GET",
            "/rest/api/3/search/jql",
            params={
                "jql": jql,
                "fields": "summary,status,assignee,labels,updated,resolution,project",
                "maxResults": max(1, min(limit, 100)),
            },
        )
        payload = response.json()
        issues = payload.get("issues", []) if isinstance(payload, dict) else []
        return [issue for issue in issues if isinstance(issue, dict)]

    async def add_remote_link(self, issue_key: str, *, url: str, title: str) -> None:
        await self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/remotelink",
            json={"object": {"url": url, "title": title}},
        )

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
        fields = "summary,description,status,priority,reporter,assignee,labels,components,updated,created"
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
