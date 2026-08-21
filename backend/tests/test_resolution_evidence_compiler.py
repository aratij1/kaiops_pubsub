from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from resolution_agent.evidence import EvidenceCompiler


def test_real_discovery_rows_compile_to_immutable_evidence() -> None:
    compiler = EvidenceCompiler()
    collected = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)
    records = compiler.compile(
        [
            {
                "evidence_id": "LOG-123",
                "source": "log",
                "uri": "log://containers/api-gateway#L42",
                "snippet": "2026-08-20T09:59:30Z upstream connection refused",
                "sha256": "a" * 64,
                "timestamp": "2026-08-20T09:59:30Z",
                "service": "api-gateway",
            }
        ],
        incident_id=uuid4(),
        service="api-gateway",
        environment="prod",
        collected_at=collected,
        incident_started_at=collected - timedelta(minutes=5),
    )

    assert len(records) == 1
    record = records[0]
    assert record.source_type == "log"
    assert record.source_uri == "log://containers/api-gateway#L42"
    assert record.freshness_seconds == 30
    assert record.metadata["current_operational_evidence"] is True
    assert record.metadata["guidance_only"] is False


def test_duplicate_content_and_lineage_does_not_increase_independent_sources() -> None:
    compiler = EvidenceCompiler()
    incident_id = uuid4()
    rows = [
        {
            "evidence_id": "LOG-1",
            "source": "log",
            "uri": "log://containers/api#L1",
            "snippet": "connection refused",
            "sha256": "b" * 64,
            "lineage_id": "container://api",
        },
        {
            "evidence_id": "LOG-COPY",
            "source": "log",
            "uri": "log://archive/api#L900",
            "snippet": "connection refused",
            "sha256": "b" * 64,
            "lineage_id": "container://api",
        },
    ]

    records = compiler.compile(rows, incident_id=incident_id, service="api", environment="prod")

    assert len(records) == 1
    assert compiler.independent_source_count(records) == 1


def test_historical_ticket_is_guidance_not_current_proof() -> None:
    compiler = EvidenceCompiler()
    records = compiler.compile(
        [{"source": "ticket", "uri": "jira://OPS-42", "summary": "Prior outage used a restart."}],
        incident_id=uuid4(),
        service="api",
        environment="prod",
    )

    assert records[0].metadata["guidance_only"] is True
    assert records[0].metadata["current_operational_evidence"] is False
    assert compiler.independent_source_count(records) == 0
