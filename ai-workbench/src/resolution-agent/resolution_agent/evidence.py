from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


EvidenceSourceType = Literal[
    "alert", "metric", "log", "trace", "topology", "dependency", "change", "code", "ticket", "runbook", "database"
]


class EvidenceRecord(BaseModel):
    """Immutable evidence admitted to deterministic resolution reasoning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str
    tenant_id: str
    project_id: str
    incident_id: UUID
    source_type: EvidenceSourceType
    source_system: str
    connector_id: str
    target_resource_id: str
    source_uri: str
    observed_at: datetime
    collected_at: datetime
    observation_window_start: datetime | None
    observation_window_end: datetime
    service: str
    environment: str
    summary: str
    content_hash: str
    lineage_id: str
    incident_window_relation: Literal["before", "during", "after", "unknown"]
    freshness_status: Literal["fresh", "stale", "unknown"]
    query_reference: str
    retrieval_tool: str
    result_checksum: str
    citation_provenance: str
    relevant_content: str
    confidence_contribution: float = Field(ge=0.0, le=1.0)
    contradiction_status: Literal["supporting", "contradicting", "neutral", "unknown"]
    current_operational_evidence: bool
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
        "dependency": "dependency",
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
        "dependency": 0.85,
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
        tenant_id: str,
        service: str,
        environment: str,
        collected_at: datetime | None = None,
        incident_started_at: datetime | None = None,
        incident_ended_at: datetime | None = None,
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
            before_incident_window = bool(incident_started_at and observed < incident_started_at)
            after_incident_window = bool(incident_ended_at and observed > incident_ended_at)
            outside_incident_window = before_incident_window or after_incident_window
            guidance_only = source_type in self.GUIDANCE_TYPES
            reliability = float(row.get("reliability_score") or row.get("confidence") or self.RELIABILITY[source_type])
            reliability = max(0.0, min(reliability, 1.0))
            current_operational = not timestamp_missing and not guidance_only and not outside_incident_window
            contradiction_status = str(row.get("contradiction_status") or "unknown").strip().lower()
            if contradiction_status not in {"supporting", "contradicting", "neutral", "unknown"}:
                contradiction_status = "unknown"
            contribution = float(row.get("confidence_contribution") or 0.0)
            evidence_id = str(row.get("evidence_id") or f"{source_type.upper()}-{content_hash[:16]}")
            compiled.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    tenant_id=tenant_id,
                    project_id=str(row.get("project_id") or row.get("project") or "unavailable"),
                    incident_id=incident_id,
                    source_type=source_type,
                    source_system=str(row.get("source_system") or raw_source),
                    connector_id=str(row.get("connector_id") or "unavailable"),
                    target_resource_id=str(row.get("target_resource_id") or row.get("service") or service),
                    source_uri=source_uri,
                    observed_at=observed,
                    collected_at=collected,
                    observation_window_start=incident_started_at,
                    observation_window_end=incident_ended_at or collected,
                    service=str(row.get("service") or service),
                    environment=str(row.get("environment") or environment or "unknown"),
                    summary=summary,
                    content_hash=content_hash,
                    lineage_id=lineage_id,
                    incident_window_relation=(
                        "unknown" if timestamp_missing
                        else "before" if before_incident_window
                        else "after" if after_incident_window or observed > collected
                        else "during"
                    ),
                    freshness_status="unknown" if timestamp_missing else "fresh" if freshness <= 900 else "stale",
                    query_reference=str(row.get("query_reference") or row.get("query") or source_uri),
                    retrieval_tool=str(
                        row.get("retrieval_tool")
                        or row.get("tool")
                        or row.get("source_system")
                        or raw_source
                    ),
                    result_checksum=f"sha256:{content_hash.removeprefix('sha256:')}",
                    citation_provenance=str(row.get("citation") or row.get("provenance") or source_uri),
                    relevant_content=summary,
                    confidence_contribution=max(0.0, min(contribution, 1.0)) if current_operational else 0.0,
                    contradiction_status=contradiction_status,
                    current_operational_evidence=current_operational,
                    freshness_seconds=freshness,
                    reliability_score=reliability,
                    metadata={
                        **{key: value for key, value in row.items() if key not in {"content", "snippet"}},
                        "guidance_only": guidance_only,
                        "current_operational_evidence": current_operational,
                        "timestamp_missing": timestamp_missing,
                        "outside_incident_window": outside_incident_window,
                    },
                )
            )
        return compiled

    @staticmethod
    def independent_source_count(records: list[EvidenceRecord]) -> int:
        return len({record.connector_id for record in records if record.current_operational_evidence})
