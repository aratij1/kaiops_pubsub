from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


EvidenceSourceType = Literal[
    "alert", "metric", "log", "trace", "topology", "change", "code", "ticket", "runbook", "database"
]


class EvidenceRecord(BaseModel):
    """Immutable evidence admitted to deterministic resolution reasoning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str
    incident_id: UUID
    source_type: EvidenceSourceType
    source_uri: str
    observed_at: datetime
    collected_at: datetime
    service: str
    environment: str
    summary: str
    content_hash: str
    lineage_id: str
    freshness_seconds: int = Field(ge=0)
    reliability_score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceCompiler:
    SOURCE_TYPES: dict[str, EvidenceSourceType] = {
        "alert": "alert",
        "metric": "metric",
        "metrics": "metric",
        "prometheus": "metric",
        "telemetry": "metric",
        "log": "log",
        "logs": "log",
        "opensearch": "log",
        "trace": "trace",
        "topology": "topology",
        "dependency": "topology",
        "change": "change",
        "deployment": "change",
        "code": "code",
        "configuration": "code",
        "config": "code",
        "ticket": "ticket",
        "tickets": "ticket",
        "incident": "ticket",
        "rag": "ticket",
        "runbook": "runbook",
        "database": "database",
        "mysql": "database",
        "data": "database",
    }
    RELIABILITY = {
        "alert": 0.85,
        "metric": 0.9,
        "log": 0.85,
        "trace": 0.9,
        "topology": 0.8,
        "change": 0.8,
        "code": 0.75,
        "database": 0.9,
        "ticket": 0.55,
        "runbook": 0.5,
    }
    GUIDANCE_TYPES = frozenset({"ticket", "runbook"})

    @staticmethod
    def _timestamp(value: Any, fallback: datetime) -> tuple[datetime, bool]:
        if isinstance(value, datetime):
            return (value if value.tzinfo else value.replace(tzinfo=UTC)), False
        if isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
                return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)), False
            except ValueError:
                pass
        return fallback, True

    @staticmethod
    def _summary(row: dict[str, Any]) -> str:
        value = next(
            (row.get(key) for key in ("summary", "snippet", "content", "message", "title") if row.get(key)),
            "",
        )
        if isinstance(value, (dict, list)):
            value = json.dumps(value, sort_keys=True, default=str)
        return " ".join(str(value).split())[:2000]

    def compile(
        self,
        rows: list[dict[str, Any]],
        *,
        incident_id: UUID,
        service: str,
        environment: str,
        collected_at: datetime | None = None,
        incident_started_at: datetime | None = None,
    ) -> list[EvidenceRecord]:
        collected = collected_at or datetime.now(UTC)
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=UTC)
        compiled: list[EvidenceRecord] = []
        seen: set[tuple[str, str]] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            raw_source = str(row.get("source") or row.get("source_type") or "alert").strip().lower()
            source_type = self.SOURCE_TYPES.get(raw_source, "alert")
            source_uri = str(row.get("source_uri") or row.get("uri") or row.get("path") or "").strip()
            summary = self._summary(row)
            if not source_uri:
                source_uri = f"{source_type}://unknown/{index}"
            observed, timestamp_missing = self._timestamp(
                row.get("observed_at") or row.get("timestamp") or row.get("time") or row.get("created_at"),
                collected,
            )
            canonical_content = json.dumps(
                {"source_type": source_type, "summary": summary, "uri": source_uri},
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            content_hash = str(row.get("content_hash") or row.get("sha256") or "").strip().lower()
            if not content_hash:
                content_hash = hashlib.sha256(canonical_content.encode()).hexdigest()
            lineage_id = str(row.get("lineage_id") or source_uri.split("#", 1)[0]).strip()
            dedup_key = (content_hash, lineage_id)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            freshness = max(0, int((collected - observed).total_seconds()))
            outside_incident_window = bool(incident_started_at and observed < incident_started_at)
            guidance_only = source_type in self.GUIDANCE_TYPES
            reliability = float(row.get("reliability_score") or row.get("confidence") or self.RELIABILITY[source_type])
            evidence_id = str(row.get("evidence_id") or f"{source_type.upper()}-{content_hash[:16]}")
            compiled.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    incident_id=incident_id,
                    source_type=source_type,
                    source_uri=source_uri,
                    observed_at=observed,
                    collected_at=collected,
                    service=str(row.get("service") or service),
                    environment=str(row.get("environment") or environment or "unknown"),
                    summary=summary,
                    content_hash=content_hash,
                    lineage_id=lineage_id,
                    freshness_seconds=freshness,
                    reliability_score=max(0.0, min(reliability, 1.0)),
                    metadata={
                        **{key: value for key, value in row.items() if key not in {"content", "snippet"}},
                        "guidance_only": guidance_only,
                        "current_operational_evidence": not guidance_only and not outside_incident_window,
                        "timestamp_missing": timestamp_missing,
                        "outside_incident_window": outside_incident_window,
                    },
                )
            )
        return compiled

    @staticmethod
    def independent_source_count(records: list[EvidenceRecord]) -> int:
        return len({(record.source_type, record.lineage_id) for record in records if record.metadata.get("current_operational_evidence")})
