from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import create_async_engine
from common.config import get_settings
from common.database import (
    AlertRecord,
    AuditLogRecord,
    ContextSnapshotRecord,
    IncidentInvestigationBindingRecord,
    IncidentOccurrenceRecord,
    IncidentProjectionRecord,
    IncidentRecord,
    create_session_factory,
)
from common.repository import IncidentRepository

settings = get_settings()

TEST_CASES = [
    {
        "key": "HIGH",
        "alert_id": UUID("d1111111-1111-4111-8111-111111111111"),
        "incident_id": UUID("d1111111-1111-4111-8111-222222222222"),
        "recommendation_id": UUID("d1111111-1111-4111-8111-333333333333"),
        "snapshot_id": UUID("d1111111-1111-4111-8111-444444444444"),
        "analysis_request_id": UUID("d1111111-1111-4111-8111-555555555555"),
        "name": "TEST-RCA-HighConfidence-PaymentService",
        "title": "Payment Gateway Thread Pool Saturation (Test)",
        "service": "payment-service",
        "environment": "dev-test",
        "severity": "critical",
        "confidence": 0.94,
        "conclusive": True,
        "status": "conclusive",
        "rca_status": "grounded",
        "claim": "Payment gateway thread pool exhaustion during batch checkout processing",
        "evidence_ids": ["EVID-HIGH-LOG-01", "EVID-HIGH-METRIC-02"],
        "missing_evidence": [],
        "conflicting_evidence": [],
        "evidence_rows": [
            {
                "evidence_id": "EVID-HIGH-LOG-01",
                "category": "logs",
                "source_id": "elasticsearch",
                "connector": "elasticsearch",
                "tenant_id": "default",
                "project_id": "payment-service",
                "service": "payment-service",
                "snippet": "ERROR [ThreadPoolExecutor] Maximum pool size 100 reached, active tasks=100, queued=500",
                "citation": "elasticsearch://logs/payments?query=pool_exhaustion",
                "reliability_score": 0.95,
                "freshness": "fresh",
                "freshness_seconds": 45,
                "epistemic_role": "current_observation",
                "current_observation": True,
            },
            {
                "evidence_id": "EVID-HIGH-METRIC-02",
                "category": "metrics",
                "source_id": "prometheus",
                "connector": "prometheus",
                "tenant_id": "default",
                "project_id": "payment-service",
                "service": "payment-service",
                "snippet": "jvm_threads_busy_ratio{service='payment-service'} = 1.00",
                "citation": "prometheus://graph?expr=jvm_threads_busy_ratio",
                "reliability_score": 0.96,
                "freshness": "fresh",
                "freshness_seconds": 30,
                "epistemic_role": "current_observation",
                "current_observation": True,
            },
        ],
    },
    {
        "key": "MEDIUM",
        "alert_id": UUID("d2222222-2222-4222-8222-111111111111"),
        "incident_id": UUID("d2222222-2222-4222-8222-222222222222"),
        "recommendation_id": UUID("d2222222-2222-4222-8222-333333333333"),
        "snapshot_id": UUID("d2222222-2222-4222-8222-444444444444"),
        "analysis_request_id": UUID("d2222222-2222-4222-8222-555555555555"),
        "name": "TEST-RCA-MedConfidence-OrderService",
        "title": "Order Consumer Queue Processing Latency Spike (Test)",
        "service": "order-service",
        "environment": "dev-test",
        "severity": "high",
        "confidence": 0.76,
        "conclusive": True,
        "status": "conclusive",
        "rca_status": "grounded",
        "claim": "Order consumer lag elevated due to downstream database lock contention",
        "evidence_ids": ["EVID-MED-METRIC-01"],
        "missing_evidence": [],
        "conflicting_evidence": [],
        "evidence_rows": [
            {
                "evidence_id": "EVID-MED-METRIC-01",
                "category": "metrics",
                "source_id": "prometheus",
                "connector": "prometheus",
                "tenant_id": "default",
                "project_id": "order-service",
                "service": "order-service",
                "snippet": "kafka_consumer_lag_records{topic='orders.v1'} = 14500",
                "citation": "prometheus://graph?expr=kafka_consumer_lag_records",
                "reliability_score": 0.85,
                "freshness": "fresh",
                "freshness_seconds": 60,
                "epistemic_role": "current_observation",
                "current_observation": True,
            },
        ],
    },
    {
        "key": "LOW",
        "alert_id": UUID("d3333333-3333-4333-8333-111111111111"),
        "incident_id": UUID("d3333333-3333-4333-8333-222222222222"),
        "recommendation_id": UUID("d3333333-3333-4333-8333-333333333333"),
        "snapshot_id": UUID("d3333333-3333-4333-8333-444444444444"),
        "analysis_request_id": UUID("d3333333-3333-4333-8333-555555555555"),
        "name": "TEST-RCA-LowConfidence-InventorySync",
        "title": "Inventory Sync Transient Timeout - Insufficient Telemetry (Test)",
        "service": "inventory-service",
        "environment": "dev-test",
        "severity": "medium",
        "confidence": 0.28,
        "conclusive": False,
        "status": "budget_exhausted",
        "rca_status": "ungrounded",
        "claim": "Observed signal requiring causal confirmation: inventory warehouse sync timeout",
        "evidence_ids": ["EVID-LOW-LOG-01"],
        "missing_evidence": ["telemetry:warehouse-sync-latency", "logs:inventory-db-replica"],
        "conflicting_evidence": [],
        "evidence_rows": [
            {
                "evidence_id": "EVID-LOW-LOG-01",
                "category": "logs",
                "source_id": "loki",
                "connector": "loki",
                "tenant_id": "default",
                "project_id": "inventory-service",
                "service": "inventory-service",
                "snippet": "WARN [SyncClient] Read timed out after 5000ms connecting to warehouse-gw",
                "citation": "loki://logs/inventory?query=timeout",
                "reliability_score": 0.40,
                "freshness": "fresh",
                "freshness_seconds": 120,
                "epistemic_role": "current_observation",
                "current_observation": True,
            },
        ],
    },
]


async def seed_test_alerts() -> None:
    engine = create_async_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=7)

    async with session_factory() as session:
        repo = IncidentRepository(session)
        for tc in TEST_CASES:
            fingerprint = f"{tc['key'].lower()}-fp-{tc['alert_id'].hex[:16]}"
            context_fingerprint = f"ctx-fp-{tc['snapshot_id'].hex}"

            # 1. ContextSnapshotRecord
            snapshot = ContextSnapshotRecord(
                snapshot_id=tc["snapshot_id"],
                tenant_id="default",
                incident_id=str(tc["incident_id"]),
                source_incident_id=str(tc["incident_id"]),
                alert_signature=f"sig-{tc['name']}",
                subject_fingerprint="a" * 64,
                context_fingerprint=context_fingerprint,
                contract_version="kaiops.context.v2",
                quality_score=tc["confidence"],
                reusable=True,
                source_manifest={
                    "logs": {"result_count": len([r for r in tc["evidence_rows"] if r["category"] == "logs"])},
                    "metrics": {"result_count": len([r for r in tc["evidence_rows"] if r["category"] == "metrics"])},
                },
                payload={
                    "alert": {
                        "id": str(tc["alert_id"]),
                        "name": tc["name"],
                        "service": tc["service"],
                        "severity": tc["severity"],
                        "description": tc["title"],
                    },
                    "metadata": {
                        "alert_id": str(tc["alert_id"]),
                        "project_id": tc["service"],
                        "context_quality": {
                            "coverage_score": tc["confidence"],
                            "freshness_score": 1.0,
                            "provenance_score": 1.0,
                            "reusable": True,
                        },
                        "context_sources": {
                            "elasticsearch": {"status": "connected", "evidence_count": len(tc["evidence_rows"])},
                        },
                        "context_evidence": {
                            "items": tc["evidence_rows"],
                        },
                    },
                },
                collected_at=now,
                expires_at=expires,
            )
            await session.merge(snapshot)

            # 2. Recommendation in AuditLogRecord
            iterative_investigation = {
                "investigation_id": str(uuid4()),
                "status": tc["status"],
                "conclusive": tc["conclusive"],
                "steps_used": len(tc["evidence_rows"]) + 1,
                "conclusion": {
                    "claim": tc["claim"],
                    "confidence": tc["confidence"],
                    "status": "confirmed" if tc["conclusive"] else "unconfirmed",
                    "evidence_ids": tc["evidence_ids"],
                    "corroborating_sources": [r["source_id"] for r in tc["evidence_rows"]],
                },
                "hypotheses": [
                    {
                        "claim": tc["claim"],
                        "status": "confirmed" if tc["conclusive"] else "unconfirmed",
                        "confidence": tc["confidence"],
                        "supporting_evidence_ids": tc["evidence_ids"],
                    }
                ],
                "rca_result": {
                    "root_cause": tc["claim"] if tc["conclusive"] else None,
                    "outcome": "CONFIRMED" if tc["conclusive"] else "INSUFFICIENT_EVIDENCE",
                    "confidence": tc["confidence"],
                    "supporting_evidence_ids": tc["evidence_ids"],
                },
                "evidence": tc["evidence_rows"],
            }

            rca_analysis = {
                "root_cause": tc["claim"] if tc["conclusive"] else "Undetermined - insufficient telemetry evidence",
                "evidence_used": tc["evidence_ids"],
                "missing_evidence": tc["missing_evidence"],
                "conflicting_evidence": tc["conflicting_evidence"],
                "confidence_score": tc["confidence"],
                "reasoning": f"Automated test investigation evaluation for {tc['name']}",
            }

            investigation_report = {
                "investigation_id": str(uuid4()),
                "status": tc["status"],
                "conclusive": tc["conclusive"],
            }

            recommendation_payload = {
                "id": str(tc["recommendation_id"]),
                "incident_id": str(tc["incident_id"]),
                "tenant_id": "default",
                "recommended_action": f"Remediation action for {tc['name']}",
                "confidence": tc["confidence"],
                "metadata": {
                    "alert_id": str(tc["alert_id"]),
                    "project_id": tc["service"],
                    "analysis_request_id": str(tc["analysis_request_id"]),
                    "context_snapshot_id": str(tc["snapshot_id"]),
                    "context_fingerprint": context_fingerprint,
                    "evidence_ids": tc["evidence_ids"],
                    "rca_version": 1,
                    "rca_status": tc["rca_status"],
                    "rca_analysis": rca_analysis,
                    "iterative_investigation": iterative_investigation,
                    "investigation_report": investigation_report,
                    "execution_plan": {
                        "execution_ready": tc["conclusive"],
                        "mutating": False,
                        "readiness_blocks": [] if tc["conclusive"] else ["insufficient_evidence"],
                    },
                },
            }

            rec_audit = AuditLogRecord(
                id=tc["recommendation_id"],
                tenant_id="default",
                actor="resolution-agent",
                action="recommendation.generated",
                resource_type="incident",
                resource_id=str(tc["incident_id"]),
                payload=recommendation_payload,
            )
            await session.merge(rec_audit)

            # 3. IncidentInvestigationBindingRecord
            binding = IncidentInvestigationBindingRecord(
                binding_id=tc["recommendation_id"],
                tenant_id="default",
                project_id=tc["service"],
                incident_id=tc["incident_id"],
                alert_id=tc["alert_id"],
                analysis_request_id=tc["analysis_request_id"],
                context_snapshot_id=tc["snapshot_id"],
                context_fingerprint=context_fingerprint,
                recommendation_id=tc["recommendation_id"],
                rca_version=1,
                resolution_plan_id=None,
                plan_fingerprint=None,
                status=tc["rca_status"],
                created_at=now,
                expires_at=expires,
            )
            await session.merge(binding)

            # 4. AlertRecord
            alert_rec = AlertRecord(
                id=tc["alert_id"],
                tenant_id="default",
                source="prometheus",
                name=tc["name"],
                service=tc["service"],
                environment=tc["environment"],
                severity=tc["severity"],
                fingerprint=fingerprint,
                created_at=now,
                payload={
                    "id": str(tc["alert_id"]),
                    "tenant_id": "default",
                    "name": tc["name"],
                    "project_id": tc["service"],
                    "service": tc["service"],
                    "severity": tc["severity"],
                    "environment": tc["environment"],
                    "description": tc["title"],
                    "labels": {
                        "alertname": tc["name"],
                        "service": tc["service"],
                        "severity": tc["severity"],
                        "environment": tc["environment"],
                    },
                    "annotations": {
                        "summary": tc["title"],
                        "description": tc["title"],
                    },
                },
            )
            await session.merge(alert_rec)

            # 5. IncidentRecord
            incident_rec = IncidentRecord(
                id=tc["incident_id"],
                tenant_id="default",
                service=tc["service"],
                environment=tc["environment"],
                severity=tc["severity"],
                status="investigating" if not tc["conclusive"] else "mitigating",
                title=tc["title"],
                ticket_id=f"TEST-{tc['key']}-101",
                created_at=now,
                updated_at=now,
                payload={
                    "id": str(tc["incident_id"]),
                    "tenant_id": "default",
                    "title": tc["title"],
                    "service": tc["service"],
                    "severity": tc["severity"],
                    "status": "investigating" if not tc["conclusive"] else "mitigating",
                    "project_id": tc["service"],
                    "alert_ids": [str(tc["alert_id"])],
                    "recommendation_id": str(tc["recommendation_id"]),
                },
            )
            await session.merge(incident_rec)

            # 6. IncidentProjectionRecord
            projection = IncidentProjectionRecord(
                incident_id=tc["incident_id"],
                alert_id=tc["alert_id"],
                recommendation_id=tc["recommendation_id"],
                tenant_id="default",
                service=tc["service"],
                environment=tc["environment"],
                severity=tc["severity"],
                status="investigating" if not tc["conclusive"] else "mitigating",
                first_seen_at=now,
                latest_event_at=now,
                updated_at=now,
                projection_payload={
                    "incident_id": str(tc["incident_id"]),
                    "alert_id": str(tc["alert_id"]),
                    "recommendation_id": str(tc["recommendation_id"]),
                    "title": tc["title"],
                    "service": tc["service"],
                    "severity": tc["severity"],
                    "status": "investigating" if not tc["conclusive"] else "mitigating",
                    "investigation_integrity": {"status": "verified"},
                },
            )
            await session.merge(projection)

            # 7. IncidentOccurrenceRecord (Links alert to canonical incident so it's not unlinked signal)
            occurrence = IncidentOccurrenceRecord(
                id=uuid4(),
                tenant_id="default",
                project_id=tc["service"],
                environment=tc["environment"],
                service=tc["service"],
                correlation_family_id=uuid4(),
                correlation_generation=1,
                canonical_incident_id=tc["incident_id"],
                occurrence_id=tc["alert_id"],
                idempotency_key=f"occ-{tc['alert_id'].hex}",
                causation_id=None,
                payload={"alert_id": str(tc["alert_id"]), "incident_id": str(tc["incident_id"])},
                observed_at=now,
            )
            await session.merge(occurrence)

        await session.commit()
        print("Successfully seeded 3 test alerts and incident investigations into local database.")


if __name__ == "__main__":
    import traceback
    try:
        asyncio.run(seed_test_alerts())
    except Exception:
        traceback.print_exc()
