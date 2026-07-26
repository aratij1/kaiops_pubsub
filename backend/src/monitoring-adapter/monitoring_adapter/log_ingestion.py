from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("monitoring-adapter.log-ingestion")

_FAILURE_KEYWORDS = ("error", "exception", "critical", "fatal", "fail")
_LEVEL_TO_SEVERITY = {
    "critical": "critical",
    "fatal": "critical",
    "error": "high",
    "warning": "warning",
    "warn": "warning",
    "info": "info",
    "debug": "info",
}
_VOLATILE_TOKEN = re.compile(
    r"(?i)(?:\b\d{4}-\d{2}-\d{2}[T ][0-9:.+\-Z]+\b|\b0x[0-9a-f]+\b|\b[0-9a-f]{16,}\b|\b\d+\b)"
)
_QUOTED_LOG_FIELD = re.compile(r'\b(?P<key>msg|message|err|error)="(?P<value>(?:\\.|[^"])*)"')


@dataclass
class LogWatchState:
    """Byte-offset checkpoint per watched file, persisted to disk so a
    restart doesn't either replay the whole file or silently skip lines
    written while the worker was down."""

    state_path: Path

    def load(self) -> dict[str, int]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, offsets: dict[str, int]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(offsets), encoding="utf-8")
        except OSError:
            logger.exception("failed to persist log ingestion offsets")


@dataclass
class OpenSearchLogState:
    """Bounded ID checkpoint for overlapping OpenSearch lookback queries."""

    state_path: Path
    max_entries: int = 10_000

    def load(self) -> dict[str, str]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, seen: dict[str, str]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            ordered = sorted(seen.items(), key=lambda item: item[1], reverse=True)[: self.max_entries]
            self.state_path.write_text(json.dumps(dict(ordered)), encoding="utf-8")
        except OSError:
            logger.exception("failed to persist OpenSearch log ingestion state")


def stable_error_signature(text: str) -> str:
    """Remove volatile timestamps, IDs and counters so recurring errors group."""

    normalized = _VOLATILE_TOKEN.sub("<n>", str(text or "").lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:240]


def readable_error_title(text: str, service: str, severity: str) -> str:
    """Build a concise Jira title instead of copying machine-formatted log fields."""

    raw = str(text or "").strip()
    fields = {
        match.group("key").lower(): match.group("value").replace(r"\"", '"')
        for match in _QUOTED_LOG_FIELD.finditer(raw)
    }
    lowered = raw.lower()
    message = fields.get("msg") or fields.get("message") or ""
    error = fields.get("err") or fields.get("error") or ""

    if "connection refused" in lowered:
        problem = f"{message.rstrip('.,;:')}: connection refused" if message else "Connection refused"
    elif "otel export failure" in lowered or "export failure" in lowered:
        problem = "OpenTelemetry export failed"
    elif "backend_unavailable" in lowered or "backend service is starting or unavailable" in lowered:
        problem = "Backend service unavailable"
    elif message:
        problem = message
    elif error:
        problem = error
    else:
        # Remove the noisy structured prefix commonly produced by Go loggers.
        problem = re.sub(r"^(?:\w+=[^\s]+\s+)+", "", raw).strip() or "Application error"

    problem = re.sub(r"\s+", " ", problem).strip(" -:")[:140]
    service_name = str(service or "unknown-service").strip()
    level = str(severity or "warning").strip().upper()
    return f"[{level}] {service_name}: {problem}"[:255]


def _source_value(source: dict[str, Any], *paths: str) -> str:
    for path in paths:
        if path in source and source[path] not in (None, ""):
            return str(source[path])
        value: Any = source
        for part in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value not in (None, ""):
            return str(value)
    return ""


def _resource_attributes(source: dict[str, Any]) -> dict[str, Any]:
    resource = source.get("resource") if isinstance(source.get("resource"), dict) else {}
    embedded = resource.get("attributes")
    if isinstance(embedded, dict):
        return embedded
    if isinstance(embedded, str):
        try:
            parsed = json.loads(embedded)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}


async def _docker_container_metadata(client: httpx.AsyncClient, endpoint: str, container_id: str) -> dict[str, str]:
    if not endpoint or not container_id:
        return {}
    try:
        response = await client.get(f"{endpoint.rstrip('/')}/containers/{container_id}/json")
        response.raise_for_status()
        payload = response.json()
        config = payload.get("Config") if isinstance(payload.get("Config"), dict) else {}
        labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
        name = str(payload.get("Name") or "").lstrip("/")
        compose_project = str(labels.get("com.docker.compose.project") or "")
        compose_service = str(labels.get("com.docker.compose.service") or "")
        if name.startswith("telemetry-"):
            project_name = "Telemetry"
        elif name.startswith("kaiops_") or name.startswith("kaiops-") or compose_project.startswith("kaiops"):
            project_name = "KaiOps"
        else:
            project_name = compose_project or "Telemetry"
        return {
            "container_name": name,
            "service": compose_service or name,
            "project_name": project_name,
        }
    except (httpx.HTTPError, ValueError):
        logger.debug("unable to resolve Docker metadata for %s", container_id)
        return {}


async def fetch_opensearch_error_logs(
    *,
    endpoint: str,
    index_pattern: str,
    state: OpenSearchLogState,
    lookback_seconds: int = 300,
    batch_size: int = 100,
    timeout_seconds: float = 15.0,
    docker_api_endpoint: str = "",
) -> list[dict[str, Any]]:
    """Fetch fresh error documents with an overlapping window and ID checkpoint."""

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=max(30, lookback_seconds))
    body = {
        "size": max(1, min(batch_size, 500)),
        "sort": [{"@timestamp": {"order": "asc", "unmapped_type": "date"}}],
        "query": {
            "bool": {
                "filter": [{"range": {"@timestamp": {"gte": cutoff.isoformat()}}}],
                "must": [
                    {
                        "simple_query_string": {
                            "query": "error | exception | critical | fatal | failed | failure",
                            "fields": ["body", "message", "severity.text", "attributes.level"],
                            "default_operator": "or",
                        }
                    }
                ],
            }
        },
    }
    url = f"{endpoint.rstrip('/')}/{index_pattern.strip() or 'otel-*'}/_search"
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(url, json=body)
        response.raise_for_status()
        hits = response.json().get("hits", {}).get("hits", [])
        container_ids = {
            str(_resource_attributes(hit.get("_source") or {}).get("container.id") or "")
            for hit in hits
            if isinstance(hit, dict) and isinstance(hit.get("_source"), dict)
        }
        docker_metadata = {
            container_id: await _docker_container_metadata(client, docker_api_endpoint, container_id)
            for container_id in container_ids
            if container_id
        }

    seen = state.load()
    records: list[dict[str, Any]] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        document_id = str(hit.get("_id") or "")
        if not document_id or document_id in seen:
            continue
        source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
        resource_attributes = _resource_attributes(source)
        container_id = str(resource_attributes.get("container.id") or "")
        container_metadata = docker_metadata.get(container_id, {})
        line = _source_value(source, "body", "message")
        if not line or not _is_failure_line(line):
            continue
        timestamp = _source_value(source, "@timestamp", "observedTimestamp") or datetime.now(timezone.utc).isoformat()
        service = str(container_metadata.get("service") or "") or _source_value(
            source,
            "service.name",
            "resource.attributes.service.name",
            "attributes.service.name",
            "resource.service.name",
        )
        records.append(
            {
                "document_id": document_id,
                "source_path": f"opensearch://{index_pattern}/{document_id}",
                "line": line,
                "service": service,
                "project_name": str(
                    container_metadata.get("project_name")
                    or resource_attributes.get("project.name")
                    or "Telemetry"
                ),
                "container_name": str(container_metadata.get("container_name") or ""),
                "container_id": container_id,
                "timestamp": timestamp,
                "trace_id": _source_value(source, "traceId", "trace_id", "trace.id"),
                "raw_source": source,
            }
        )
        seen[document_id] = timestamp
    state.save(seen)
    return records


def fetch_new_log_lines(paths: list[Path], state: LogWatchState, *, max_lines_per_file: int = 200) -> list[dict[str, Any]]:
    """Reads any bytes appended to each watched file since the last checkpoint
    (tail -f semantics — a brand-new path starts at end-of-file, not from the
    beginning, so enabling this doesn't flood on historical log content).
    """
    offsets = state.load()
    records: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        key = str(path)
        size = path.stat().st_size
        start = offsets.get(key, size)  # first time seeing this file: start at EOF
        if size < start:
            start = 0  # file was rotated/truncated
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(start)
                lines = handle.readlines()
                offsets[key] = handle.tell()
        except OSError:
            logger.exception("failed to read log file %s", path)
            continue
        for line in lines[:max_lines_per_file]:
            stripped = line.strip()
            if stripped:
                records.append({"source_path": str(path), "line": stripped})
    state.save(offsets)
    return records


def _severity_from_level(level: str) -> str:
    return _LEVEL_TO_SEVERITY.get(level.strip().lower(), "warning")


def _is_failure_line(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _FAILURE_KEYWORDS)


def log_line_to_alert_payload(record: dict[str, Any], *, default_service: str) -> dict[str, Any] | None:
    """Converts one watched log line into the same mapped-payload shape
    every other ingestion path produces. Returns None for lines that don't
    represent a failure (INFO/DEBUG noise) — only real problems become
    alerts, since each one will create or comment on a Jira ticket.

    Structured JSON lines (fault-lab's emit() format: level/service/
    component/message/exception/alert_name/scenario_id/ticket_example) are
    parsed directly. Plain-text lines fall back to a failure-keyword match.
    """
    line = str(record.get("line") or "")
    source_path = str(record.get("source_path") or "")

    parsed: dict[str, Any] = {}
    try:
        candidate = json.loads(line)
        if isinstance(candidate, dict):
            parsed = candidate
    except (ValueError, TypeError):
        parsed = {}

    if parsed:
        level = str(parsed.get("level") or parsed.get("severity") or "").strip()
        if level and level.lower() not in {"error", "critical", "fatal"}:
            return None
        service = str(parsed.get("service") or default_service)
        message = str(parsed.get("message") or parsed.get("event") or "log alert")
        exception_text = str(parsed.get("exception") or "")
        alert_name = str(parsed.get("alert_name") or message)
        severity = _severity_from_level(level or "error")
        labels = {
            "alert_status": "firing",
            "log_source_path": source_path,
            "log_level": level or "ERROR",
            "component": str(parsed.get("component") or ""),
            "trace_id": str(parsed.get("trace_id") or ""),
            "scenario_id": str(parsed.get("scenario_id") or ""),
            "ticket_example": str(parsed.get("ticket_example") or ""),
        }
        description = f"{message}\n{exception_text}".strip()
    else:
        if not _is_failure_line(line):
            return None
        service = str(record.get("service") or default_service)
        signature = stable_error_signature(line)
        severity = "high" if "critical" in line.lower() or "fatal" in line.lower() else "warning"
        alert_name = readable_error_title(line, service, severity)
        labels = {
            "alert_status": "firing",
            "log_source_path": source_path,
            "log_level": "ERROR",
            "error_signature": signature,
            "opensearch_document_id": str(record.get("document_id") or ""),
            "trace_id": str(record.get("trace_id") or ""),
            "project_name": str(record.get("project_name") or ""),
            "application": str(record.get("project_name") or ""),
            "container_name": str(record.get("container_name") or ""),
            "container_id": str(record.get("container_id") or ""),
        }
        description = line

    return {
        "source": "logs",
        "name": alert_name,
        "service": service,
        "environment": "prod",
        "severity": severity,
        "description": description,
        "labels": labels,
        "annotations": {
            "summary": alert_name,
            "description": description,
        },
    }
