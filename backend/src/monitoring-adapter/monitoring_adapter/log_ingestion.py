from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
        service = default_service
        alert_name = line[:120] or "log alert"
        severity = "high" if "critical" in line.lower() or "fatal" in line.lower() else "warning"
        labels = {
            "alert_status": "firing",
            "log_source_path": source_path,
            "log_level": "ERROR",
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
