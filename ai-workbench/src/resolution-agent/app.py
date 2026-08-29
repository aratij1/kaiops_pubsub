from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from ai_workbench_common.models import Context
from common.config import get_settings
from common.event_publishers import build_agent_event_contract, build_event_envelope
from common.resolution_lifecycle import ResolutionState, create_lifecycle, decide_resolution_control
from common.kafka import KafkaConsumer
from common.kafka import consume_forever as consume_kafka_forever
from common.models import Incident, Recommendation
from common.capability_registry import default_capability_registry
from common.remediation_plan import (
    AutonomyRecommendation,
    RemediationPlan,
    assess_remediation_plan,
)
from common.orchestration.execution_plan import resolve_execution_plan
from common.orchestration.execution_plan_contract import (
    ExecutionPlanV2,
    verify_plan_fingerprint,
)
from common.rabbitmq import RabbitMQConsumer
from common.rabbitmq import consume_forever as consume_rabbitmq_forever
from common.repository import IncidentRepository
from common.service import create_app
from common.telemetry import CONTEXT_KNOWLEDGE_OPERATIONS, EVENTS_PROCESSED
from common.tenant_identity import require_tenant_id
from common.topics import CONTEXT_EVENTS, RESOLUTION_EVENTS
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from resolution_agent import ResolutionIntelligenceAgent
from resolution_agent.investigation import IterativeInvestigator
from resolution_agent.contracts import ResolutionOption
from resolution_agent.policy import ResolutionPolicyInput, evaluate_resolution_policy
from resolution_agent.metrics import HITL_TOTAL, HOTL_TOTAL, PLAN_BLOCKED_TOTAL
from resolution_agent.workflow import ResolutionWorkflowState, transition_idempotency_key
from resolution_agent.catalog import (
    RESOLUTION_CATALOG,
    prepare_resolution_plan,
    register_global_knowledge,
    relevant_resolutions,
)

settings = get_settings()
settings.service_name = "resolution-agent"
logger = logging.getLogger("kaiops.resolution_agent.app")
agent = ResolutionIntelligenceAgent()
investigator = IterativeInvestigator()
tasks: list[asyncio.Task] = []
_GLOBAL_KNOWLEDGE_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_GLOBAL_KNOWLEDGE_CACHE_TTL_SECONDS = 300.0
_GLOBAL_KNOWLEDGE_CACHE_MAX_ENTRIES = 256
MESSAGE_BUS_DUAL_CONSUME_ENABLED = str(os.getenv("MESSAGE_BUS_DUAL_CONSUME_ENABLED", "false")).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

ConsumeRunner = Callable[[Any, Callable[[dict], Awaitable[None]]], Coroutine[Any, Any, None]]


def _utc_aware(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _resolution_quality_score(payload: Any) -> float:
    if not isinstance(payload, dict) or not payload:
        return 0.0
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    evaluation = metadata.get("evaluation") if isinstance(metadata.get("evaluation"), dict) else {}
    raw = evaluation.get("overall_score")
    if raw is None:
        raw = payload.get("confidence")
    try:
        score = float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(score / 100.0 if score > 1.0 else score, 1.0))


def _resolution_reuse_threshold() -> float:
    configured = float(getattr(settings, "context_resolution_reuse_min_score", 0.7) or 0.7)
    return max(0.0, min(configured, 1.0))


def _deterministic_recommendation_id(context: Context) -> UUID:
    metadata = context.metadata if isinstance(context.metadata, dict) else {}
    # A manual regeneration is a distinct governed analysis generation even
    # when the underlying evidence fingerprint is unchanged. Without this
    # request identity, polling cannot distinguish the new result from the
    # recommendation that existed before the operator clicked regenerate.
    identity = str(metadata.get("analysis_request_id") or "").strip()
    try:
        UUID(identity)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=409,
            detail="a durable UUID analysis_request_id is required before RCA generation",
        ) from None
    return uuid5(NAMESPACE_URL, f"kaims:recommendation:{context.incident_id}:{identity}:v2")


def _attach_rca_governance_binding(recommendation: Recommendation, context: Context) -> None:
    """Bind one immutable RCA generation to the context snapshot it evaluated."""

    context_metadata = context.metadata if isinstance(context.metadata, dict) else {}
    recommendation.metadata = {
        **(recommendation.metadata if isinstance(recommendation.metadata, dict) else {}),
        "analysis_request_id": str(context_metadata.get("analysis_request_id") or "") or None,
        "project_id": str(context_metadata.get("project_id") or context.alert.labels.get("project_id") or "default"),
        "alert_id": str(context.alert.id),
        "context_snapshot_id": str(context_metadata.get("context_snapshot_id") or "") or None,
        "context_fingerprint": str(context_metadata.get("context_fingerprint") or "") or None,
        "rca_version": max(1, int(context_metadata.get("rca_version") or 1)),
        "recommendation_version": str(recommendation.id),
    }


async def _require_context_snapshot_binding(context: Context) -> dict[str, Any] | None:
    """Fail closed before persisting an RCA against orphaned or stale context."""
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return None
    metadata = context.metadata if isinstance(context.metadata, dict) else {}
    snapshot_id = str(metadata.get("context_snapshot_id") or "").strip()
    if not snapshot_id:
        raise HTTPException(status_code=409, detail="context_snapshot_id is required before RCA persistence")
    async with app.state.session_factory() as session:
        snapshot = await IncidentRepository(session).context_snapshot_by_id(
            snapshot_id, tenant_id=context.tenant_id, incident_id=context.incident_id,
        )
    if snapshot is None:
        raise HTTPException(
            status_code=409,
            detail="the bound context snapshot does not exist for this tenant and incident",
        )
    persisted = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
    persisted_alert = persisted.get("alert") if isinstance(persisted.get("alert"), dict) else {}
    if str(persisted_alert.get("id") or "") != str(context.alert.id):
        raise HTTPException(status_code=409, detail="the bound context snapshot belongs to a different alert")
    if str(snapshot.get("context_fingerprint") or "") != str(metadata.get("context_fingerprint") or ""):
        raise HTTPException(status_code=409, detail="the bound context snapshot fingerprint does not match")
    freshness_mandatory = bool(metadata.get("force_full_analysis")) or str(
        metadata.get("analysis_mode") or metadata.get("context_strategy") or ""
    ).lower() in {"fresh", "realtime"}
    # MySQL may return DATETIME values without tzinfo. Normalize at the
    # service boundary before comparing them with an aware UTC clock.
    expires_at = _utc_aware(snapshot["expires_at"])
    if freshness_mandatory and expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="the bound context snapshot has expired")
    return snapshot


def _attach_resolution_options(
    recommendation: Recommendation,
    context: Context,
    investigation_report: dict[str, Any],
) -> None:
    """Project governed catalog matches into typed, non-executable options."""
    if investigation_report.get("conclusive") is not True:
        recommendation.metadata["resolution_options"] = []
        recommendation.metadata["resolution_options_status"] = str(
            investigation_report.get("outcome") or "INSUFFICIENT_EVIDENCE"
        )
        return
    conclusion = investigation_report.get("conclusion") if isinstance(investigation_report.get("conclusion"), dict) else {}
    evidence_ids = [str(value) for value in conclusion.get("evidence_ids") or [] if str(value).strip()]
    confidence = max(0.0, min(float(conclusion.get("confidence") or recommendation.confidence or 0.0), 1.0))
    matches = relevant_resolutions(
        issue=str(recommendation.root_cause or context.alert.description or context.alert.name),
        service=context.alert.service,
        recommended_action=str(recommendation.recommended_action or ""),
        limit=3,
    )
    options: list[dict[str, Any]] = []
    for rank, match in enumerate(matches, start=1):
        risk = str(match.get("risk") or "high").upper()
        option = ResolutionOption(
            option_id=str(match["id"]),
            incident_id=context.incident_id,
            correlation_id=str(context.trace_id or context.incident_id),
            title=str(match.get("title") or match["id"]),
            objective=str(match.get("applicability") or "Restore the affected service safely."),
            action_type=str(match.get("strategy") or "diagnose"),
            target={"platform": match.get("platform"), "service": context.alert.service},
            reasoning=(
                f"Rank {rank}: governed catalog match based on the evidence-supported RCA; "
                f"match reasons={', '.join(str(value) for value in match.get('match_reasons') or []) or 'catalog taxonomy'}."
            ),
            supporting_evidence_ids=evidence_ids,
            confidence=confidence,
            estimated_success_probability=min(confidence, float(match.get("relevance") or 0.0)),
            risk_level=risk,
            estimated_recovery_time=None,
            blast_radius={"affected_services": [context.alert.service], "verified": False},
            preconditions=[{"description": str(value), "required": True} for value in match.get("prerequisites") or []],
            validation_plan=[{"description": str(value), "source": "registered-validator-required"} for value in match.get("validation") or []],
            rollback_plan={"steps": list(match.get("rollback") or [])} if match.get("rollback") else None,
            automation_eligibility="HITL" if risk in {"LOW", "MEDIUM"} else "MANUAL_ONLY",
        )
        options.append(option.model_dump(mode="json"))
    recommendation.metadata["resolution_options"] = options
    recommendation.metadata["resolution_options_status"] = "RANKED" if options else "UNSUPPORTED_ACTION"
    typed_investigation = recommendation.metadata.get("iterative_investigation")
    if isinstance(typed_investigation, dict):
        rca_result = typed_investigation.get("rca_result")
        if isinstance(rca_result, dict):
            rca_result["resolution_options"] = options


async def _resolve_context(context: Context) -> Recommendation:
    metadata = context.metadata if isinstance(context.metadata, dict) else {}
    prior = metadata.get("prior_resolution") if isinstance(metadata.get("prior_resolution"), dict) else {}
    score = _resolution_quality_score(prior)
    may_reuse = (
        bool(getattr(settings, "context_resolution_reuse_enabled", True))
        and bool(metadata.get("context_reused"))
        and not bool(metadata.get("force_full_analysis"))
        and score > _resolution_reuse_threshold()
    )
    if not may_reuse:
        investigation_report: dict[str, Any] = {}
        investigation_enabled = str(os.getenv("RESOLUTION_ITERATIVE_INVESTIGATION_ENABLED", "true")).strip().lower() in {
            "1", "true", "yes", "on",
        }
        if investigation_enabled:
            async def persist_investigation(event: str, payload: dict[str, Any]) -> None:
                if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
                    return
                try:
                    async with app.state.session_factory() as session:
                        repo = IncidentRepository(session)
                        if event == "started":
                            await repo.create_resolution_investigation(payload)
                        elif event == "step":
                            await repo.append_resolution_investigation_step(payload)
                        elif event == "completed":
                            await repo.complete_resolution_investigation(payload)
                        await session.commit()
                except Exception as exc:
                    # Investigation remains useful in-memory when persistence is
                    # temporarily unavailable; expose degradation in the report.
                    logger.exception("failed to persist resolution investigation event=%s", event)
                    investigation_report.setdefault("persistence_errors", []).append(str(exc)[:300])

            investigation_report = await investigator.investigate(context, persist=persist_investigation)
            metadata = dict(context.metadata if isinstance(context.metadata, dict) else {})
            context_evidence = dict(
                metadata.get("context_evidence") if isinstance(metadata.get("context_evidence"), dict) else {}
            )
            for row in investigation_report.get("evidence", []):
                if not isinstance(row, dict):
                    continue
                source = investigator._source(row)
                bucket = {
                    "history": "tickets", "data": "database", "alert": "telemetry",
                }.get(source, source)
                rows = list(context_evidence.get(bucket) if isinstance(context_evidence.get(bucket), list) else [])
                known = {str(item.get("evidence_id") or item.get("uri") or "") for item in rows if isinstance(item, dict)}
                identity = str(row.get("evidence_id") or row.get("uri") or "")
                if identity and identity not in known:
                    rows.append(row)
                context_evidence[bucket] = rows
            metadata["context_evidence"] = context_evidence
            metadata["iterative_investigation"] = {
                key: value for key, value in investigation_report.items() if key != "evidence"
            }
            context = context.model_copy(update={"metadata": metadata})
        recommendation = await agent.resolve_with_runtime(context)
        if investigation_report:
            recommendation.metadata["iterative_investigation"] = {
                key: value for key, value in investigation_report.items() if key != "evidence"
            }
            recommendation.metadata["investigation_id"] = investigation_report.get("investigation_id")
            recommendation.metadata["investigation_status"] = investigation_report.get("status")
            if not investigation_report.get("conclusive"):
                missing = ", ".join(str(item.get("source")) for item in investigation_report.get("next_evidence", []))
                recommendation.root_cause = (
                    "Investigation inconclusive: the collected evidence does not independently corroborate a causal hypothesis."
                )
                recommendation.recommended_action = (
                    f"Collect the next required read-only evidence ({missing or 'missing application sources'}) and rerun resolution."
                )
                conclusion = (
                    investigation_report.get("conclusion")
                    if isinstance(investigation_report.get("conclusion"), dict)
                    else {}
                )
                recommendation.confidence = max(
                    0.0, min(float(conclusion.get("confidence") or recommendation.confidence or 0.0), 0.99)
                )
                recommendation.metadata["resolution_outcome"] = "inconclusive"
                recommendation.metadata["confidence_kind"] = "leading_hypothesis"
                recommendation.metadata["confidence_actionable"] = False
            _attach_resolution_options(recommendation, context, investigation_report)
        recommendation.metadata = {
            **(recommendation.metadata if isinstance(recommendation.metadata, dict) else {}),
            "analysis_reused": False,
            "analysis_source": "fresh_evidence_analysis",
        }
        recommendation.id = _deterministic_recommendation_id(context)
        return recommendation
    try:
        cached_recommendation = Recommendation.model_validate(prior)
    except Exception:
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("reuse_resolution", "invalid").inc()
        return await agent.resolve_with_runtime(context)
    recommendation = cached_recommendation.model_copy(
        update={
            "tenant_id": context.tenant_id,
            "id": _deterministic_recommendation_id(context),
            "created_at": datetime.now(UTC),
            "incident_id": context.incident_id,
            "trace_id": str(context.alert.trace_id or "") or None,
        }
    )
    recommendation.metadata = {
        **(recommendation.metadata if isinstance(recommendation.metadata, dict) else {}),
        "analysis_reused": True,
        "analysis_source": "qualified_context_resolution_cache",
        "analysis_source_incident_id": metadata.get("context_source_incident_id"),
        "analysis_source_alert_id": metadata.get("context_source_alert_id"),
        "analysis_reuse_score": score,
        "analysis_reuse_threshold": _resolution_reuse_threshold(),
        "analysis_reused_at": datetime.now(UTC).isoformat(),
    }
    CONTEXT_KNOWLEDGE_OPERATIONS.labels("reuse_resolution", "success").inc()
    return recommendation


def _catalog_plan_for(
    context: Context,
    decision: dict[str, Any] | None = None,
    recommendation: Recommendation | None = None,
) -> dict[str, Any]:
    routing = decision if isinstance(decision, dict) else {}
    supplied = routing.get("execution_plan")
    supplied_values = []
    if isinstance(supplied, dict):
        for key in ("commands", "preflight_commands", "validation_commands", "rollback_commands"):
            values = supplied.get(key, [])
            supplied_values.extend(str(value) for value in (values if isinstance(values, list) else [values]))
    legacy_compose_binding = any(
        "docker-socket-proxy:2375/containers/" in value
        and "/containers/$container_id/" not in value
        and "/containers/json?filters=" not in value
        for value in supplied_values
    )
    if (
        isinstance(supplied, dict)
        and supplied.get("schema_version") == "kaims.execution-plan.v2"
        and not legacy_compose_binding
    ):
        try:
            validated = ExecutionPlanV2.model_validate(supplied)
        except ValueError:
            pass
        else:
            if verify_plan_fingerprint(supplied):
                return validated.model_dump(mode="json")
    return resolve_execution_plan(
        alert=context.alert,
        workflow_name=str(routing.get("workflow") or "resolution-rerun"),
        requires_approval=bool(routing.get("requires_approval", True)),
        risk_tier=str(routing.get("risk_tier") or "medium"),
        execution_mode=str(routing.get("execution_mode") or "human-approval"),
        resolution_hints=" ".join(
            filter(
                None,
                (
                    str(recommendation.root_cause or "") if recommendation else "",
                    str(recommendation.recommended_action or "") if recommendation else "",
                    " ".join(
                        str(item.get("cause") or "")
                        for item in (
                            recommendation.metadata.get("hypothesis_analysis", {}).get("ranked", [])
                            if recommendation and isinstance(recommendation.metadata, dict)
                            else []
                        )
                        if isinstance(item, dict)
                    ),
                ),
            )
        )[:4000],
        evidence_basis=(
            [
                str(evidence_id)
                for evidence_ids in recommendation.metadata.get("investigation_report", {}).get("source_evidence_ids", {}).values()
                for evidence_id in (evidence_ids if isinstance(evidence_ids, list) else [])
                if str(evidence_id).strip()
            ]
            if recommendation
            and isinstance(recommendation.metadata, dict)
            and isinstance(recommendation.metadata.get("investigation_report"), dict)
            else []
        ),
        incident_id=recommendation.incident_id if recommendation else None,
        root_cause=str(recommendation.root_cause or "RCA not yet established") if recommendation else "RCA not yet established",
        confidence=float(recommendation.confidence or 0.0) if recommendation else 0.0,
    )


def _apply_catalog_plan(recommendation: Recommendation, context: Context, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = dict(_catalog_plan_for(context, decision, recommendation))
    metadata = recommendation.metadata if isinstance(recommendation.metadata, dict) else {}
    metadata["model_proposed_execution_plan"] = metadata.get("execution_plan", {})
    # The normalized investigation contract uses an integer generation, while
    # ExecutionPlanV2 carries the immutable version as a string.  Normalize at
    # this boundary so a fresh, bound RCA cannot fail after analysis merely
    # because Pydantic does not coerce numbers in strict string fields.
    plan["rca_version"] = str(metadata.get("rca_version") or "") or None
    plan["evidence_snapshot_id"] = metadata.get("context_snapshot_id")
    plan["recommendation_version"] = metadata.get("recommendation_version")
    investigation = metadata.get("investigation_report") if isinstance(metadata.get("investigation_report"), dict) else {}
    rca_analysis = metadata.get("rca_analysis") if isinstance(metadata.get("rca_analysis"), dict) else {}
    plan["evidence_basis"] = list(rca_analysis.get("evidence_used") or [])
    plan["investigation_report"] = investigation
    plan["historical_precedents"] = list(
        metadata.get("hypothesis_analysis", {}).get("ranked", [])
        if isinstance(metadata.get("hypothesis_analysis"), dict)
        else []
    )[:5]
    iterative = metadata.get("iterative_investigation") if isinstance(metadata.get("iterative_investigation"), dict) else {}
    if iterative and iterative.get("conclusive") is not True:
        candidate_plan = dict(plan)
        plan = {
            **plan,
            "plan_kind": "diagnostic",
            "diagnostic_only": True,
            "mutating": False,
            "execution_ready": False,
            "commands": [],
            "scripts": [],
            "rollback_commands": [],
            "readiness_blocks": list(dict.fromkeys([
                *(plan.get("readiness_blocks") or []),
                "Iterative investigation is inconclusive; corrective execution is not authorized.",
                *(
                    f"Missing evidence source: {source}"
                    for source in iterative.get("missing_sources", [])[:5]
                ),
            ])),
            "investigation_status": iterative.get("status"),
            "investigation_id": iterative.get("investigation_id"),
            "next_evidence": iterative.get("next_evidence", []),
        }
        metadata["candidate_execution_plan"] = candidate_plan
    confidence = float(
        (iterative.get("conclusion") or {}).get("confidence")
        or recommendation.confidence
        or 0.0
    )
    connector = plan.get("connection", {}).get("connector", {}) if isinstance(plan.get("connection"), dict) else {}
    policy_risk = str(plan.get("risk_tier") or "medium").lower()
    if policy_risk not in {"low", "medium", "high", "critical"}:
        policy_risk = "medium"
    policy = evaluate_resolution_policy(ResolutionPolicyInput(
        environment=str(context.alert.environment or "unknown").lower(),
        risk=policy_risk,
        confidence=max(0.0, min(confidence, 1.0)),
        runbook_status=str(plan.get("runbook_status") or "unregistered"),
        runbook_success_rate=float(plan.get("runbook_success_rate") or 0.0),
        mutating=bool(plan.get("mutating")),
        reversible=bool(plan.get("rollback_commands")),
        canary_supported=bool(plan.get("canary_supported")),
        blast_radius=str(plan.get("blast_radius") or "single-service"),
        target_verified=bool(str(plan.get("remediation_target") or "").strip()),
        validation_available=bool(plan.get("validation_commands")),
        rollback_available=bool(plan.get("rollback_commands")),
        contradiction_count=len((iterative.get("conclusion") or {}).get("contradicting_evidence_ids") or []),
        database_change=str(connector.get("type") or "").lower() in {"database", "mysql"},
        rca_conclusive=bool(iterative.get("conclusive")),
    ))
    plan["policy_decision"] = policy.model_dump(mode="json")
    if policy.decision == "hitl":
        HITL_TOTAL.inc()
    elif policy.decision == "hotl":
        HOTL_TOTAL.inc()
    elif policy.decision == "block":
        PLAN_BLOCKED_TOTAL.inc()
    if policy.decision in {"block", "investigate"} and plan.get("mutating"):
        metadata["candidate_execution_plan"] = dict(plan)
        plan["plan_kind"] = "diagnostic"
        plan["diagnostic_only"] = True
        plan["mutating"] = False
        plan["execution_ready"] = False
        plan["commands"] = []
        plan["rollback_commands"] = []
        plan["readiness_blocks"] = list(dict.fromkeys([
            *(plan.get("readiness_blocks") or []),
            *(f"policy:{reason}" for reason in policy.reason_codes),
        ]))
    plan["requires_approval"] = policy.decision == "hitl"
    plan["approval_required"] = policy.decision == "hitl"
    if not plan.get("commands"):
        plan["actions"] = []
    plan["preflight"] = list(plan.get("preflight_commands") or [])
    plan["validation"] = list(plan.get("validation_commands") or [])
    plan["rollback"] = list(plan.get("rollback_commands") or [])
    plan["evidence_references"] = list(plan.get("evidence_basis") or [])
    plan["approval_policy"] = {
        "decision": (
            "hitl_required"
            if policy.decision == "hitl"
            else "denied"
            if policy.decision == "block"
            else "recommend_only"
        ),
        "required_approver_role": "hitl-reviewer",
        "reason_codes": list(policy.reason_codes),
        "approval_expiry_seconds": 900,
    }
    plan = ExecutionPlanV2.model_validate(plan).finalized().model_dump(mode="json")
    _attach_typed_remediation_plan(recommendation, context, plan)
    metadata["execution_plan"] = plan
    metadata["remediation_target"] = str(plan.get("remediation_target") or context.alert.service or "")
    metadata["recommended_commands"] = list(plan.get("commands") or [])
    metadata["runbook_id"] = str(plan.get("runbook_governance_id") or "")
    metadata["runbook_slug"] = str(plan.get("playbook_id") or "")
    metadata["runbook_version"] = plan.get("playbook_version")
    metadata["runbook_status"] = str(plan.get("runbook_status") or "")
    metadata["runbook_checksum"] = str(plan.get("runbook_checksum") or "")
    routing = decision if isinstance(decision, dict) else {}
    requires_approval = bool(routing.get("requires_approval", plan.get("requires_approval", True)))
    control = decide_resolution_control(
        plan,
        requires_approval=requires_approval,
        sources=(routing, metadata, context.alert.metadata if isinstance(context.alert.metadata, dict) else {}),
    )
    metadata["resolution_control"] = control
    analysis_reused = metadata.get("analysis_reused") is True
    disposition = str(control.get("disposition") or "investigate")
    if disposition in {"watch_only", "investigate"}:
        path_id, path_label = "diagnostic", "Diagnostic completion"
        skipped = ["approval", "execution"]
    elif analysis_reused and disposition == "execution_ready":
        path_id, path_label = "verified_fast_path", "Verified context fast path"
        skipped = ["context_collection", "rca_generation", "approval"]
    elif analysis_reused:
        path_id, path_label = "guided_reuse", "Reused analysis with approval"
        skipped = ["context_collection", "rca_generation"]
    elif disposition == "execution_ready":
        path_id, path_label = "autonomous", "Fresh analysis autonomous path"
        skipped = ["approval"]
    else:
        path_id, path_label = "guided", "Fresh analysis guided path"
        skipped = []
    metadata["orchestration_path"] = {
        "schema_version": "kaims.orchestration-path.v1",
        "id": path_id,
        "label": path_label,
        "context_reused": bool(context.metadata.get("context_reused")),
        "analysis_reused": analysis_reused,
        "disposition": disposition,
        "skipped_stages": skipped,
    }
    metadata["resolution_lifecycle"] = create_lifecycle(
        tenant_id=context.tenant_id,
        incident_id=recommendation.incident_id,
        recommendation_id=recommendation.id,
        plan=plan,
        state=ResolutionState(control["initial_state"]),
        reason_code=str(control["reason_code"]),
        control=control,
    )
    recommendation.metadata = metadata
    recommendation.commands = list(plan.get("commands") or [])
    return plan


_CAPABILITY_BINDINGS: dict[tuple[str, str], str] = {
    ("kubernetes", "restart_pod"): "kubernetes.restart_workload",
    ("kubernetes", "restart_service"): "kubernetes.restart_workload",
    ("kubernetes", "rollback_deployment"): "kubernetes.rollback_deployment",
    ("kubernetes", "scale_workload"): "kubernetes.scale_workload",
    ("mysql", "read_status"): "database.collect_diagnostics",
    ("mysql", "collect_diagnostics"): "database.collect_diagnostics",
    ("mysql", "failover_database"): "database.failover",
}


def _attach_typed_remediation_plan(
    recommendation: Recommendation,
    context: Context,
    execution_plan: dict[str, Any],
) -> None:
    """Project only registered, typed catalog actions into the Resolution contract."""
    metadata = recommendation.metadata if isinstance(recommendation.metadata, dict) else {}
    actions = execution_plan.get("actions") if isinstance(execution_plan.get("actions"), list) else []
    if len(actions) != 1 or not isinstance(actions[0], dict):
        metadata["remediation_plan_status"] = {
            "valid": False,
            "execution_eligible": False,
            "reason_codes": ["single_registered_capability_required"],
        }
        recommendation.remediation_plan = None
        recommendation.metadata = metadata
        return
    action = actions[0]
    binding = action.get("safety_binding") if isinstance(action.get("safety_binding"), dict) else {}
    capability = binding.get("capability") if isinstance(binding.get("capability"), dict) else {}
    operation = str(capability.get("operation") or "").strip()
    connection = execution_plan.get("connection") if isinstance(execution_plan.get("connection"), dict) else {}
    connector = connection.get("connector") if isinstance(connection.get("connector"), dict) else {}
    connector_type = str(connector.get("type") or "").strip().lower()
    capability_id = _CAPABILITY_BINDINGS.get((connector_type, operation))
    if not capability_id:
        metadata["remediation_plan_status"] = {
            "valid": False,
            "execution_eligible": False,
            "reason_codes": ["unregistered_capability_binding"],
            "catalog_operation": operation,
            "connector_type": connector_type,
        }
        recommendation.remediation_plan = None
        recommendation.metadata = metadata
        return
    blast = binding.get("blast_radius") if isinstance(binding.get("blast_radius"), dict) else {}
    target = str(action.get("target_resource_id") or "").strip()
    affected = [str(item) for item in blast.get("affected_resource_ids", []) if str(item).strip()]
    stable_target_identity = target.startswith(("dt://", "urn:", "arn:", "k8s://", "/subscriptions/"))
    evidence = [str(item) for item in execution_plan.get("evidence_references", []) if str(item).strip()]
    registry = default_capability_registry()
    definition = registry.get(capability_id)
    raw_inputs = action.get("inputs") if isinstance(action.get("inputs"), dict) else {}
    parameters = {
        str(key): value
        for key, value in raw_inputs.items()
        if str(key).lower() not in {"catalog_command", "command", "commands", "script", "scripts"}
    }
    risk_scores = {"low": 20, "medium": 45, "high": 75, "critical": 95}
    typed_plan = RemediationPlan(
        incident_id=recommendation.incident_id,
        tenant_id=recommendation.tenant_id,
        root_cause=recommendation.root_cause,
        root_cause_confidence=recommendation.confidence,
        supporting_evidence=evidence,
        affected_resources=affected or ([target] if target else []),
        blast_radius=blast.get("scope") or "unknown",
        business_impact=recommendation.impact,
        recommended_capability=capability_id,
        target_resource_id=target,
        target_identity_verified=(
            bool(blast.get("verified"))
            and target in affected
            and stable_target_identity
        ),
        connector_id=definition.supported_connectors[0],
        required_parameters=parameters,
        preconditions=list(definition.preconditions),
        validation_plan=[str(item) for item in action.get("validation", []) if str(item).strip()],
        rollback_capability=definition.rollback_capability,
        risk_score=risk_scores.get(str(execution_plan.get("risk") or "medium").lower(), 45),
        autonomy_recommendation=(
            AutonomyRecommendation.HITL_REQUIRED
            if definition.mutating
            else AutonomyRecommendation.RECOMMEND
        ),
    )
    assessment = assess_remediation_plan(
        typed_plan,
        registry,
        environment={"prod": "production", "dev": "development"}.get(
            str(context.alert.environment or "unknown").lower(),
            str(context.alert.environment or "unknown").lower(),
        ),
    )
    recommendation.remediation_plan = typed_plan
    metadata["remediation_plan"] = typed_plan.model_dump(mode="json")
    metadata["remediation_plan_status"] = assessment.model_dump(mode="json")
    recommendation.metadata = metadata


def _build_resolution_event_payload(
    *,
    context: Context,
    incident: Incident,
    recommendation: Recommendation,
    decision_payload: dict[str, Any],
) -> dict[str, Any]:
    flow_id = str(decision_payload.get("flow_id") or incident.id)
    event_contract = build_agent_event_contract(
        flow_id=flow_id,
        incident_id=str(incident.id),
        trace_id=str(incident.trace_id or context.alert.trace_id or ""),
        correlation_id=str(context.alert.correlation_id or "") or None,
        agent="resolution-agent",
        payload={
            "recommended_action": recommendation.recommended_action,
            "risk": recommendation.risk,
            "topic": RESOLUTION_EVENTS,
        },
        metadata={
            "policy_version": recommendation.metadata.get("policy_version"),
            "policy_reason": recommendation.metadata.get("policy_reason"),
            "workflow": decision_payload.get("workflow"),
        },
        confidence=float(recommendation.confidence),
        reasoning=str(recommendation.metadata.get("reasoning") or recommendation.rationale or ""),
        citations=list(recommendation.metadata.get("citations", [])),
        evidence_ids=list(recommendation.metadata.get("evidence_ids", [])),
    )
    return {
        "recommendation": recommendation,
        "resolution_lifecycle": recommendation.metadata.get("resolution_lifecycle"),
        "context": context,
        "incident": incident,
        "decision": decision_payload,
        "event_contract": event_contract,
    }


def _resolution_projection_status(metadata: dict[str, Any], *, requires_approval: bool) -> str:
    plan = metadata.get("execution_plan") if isinstance(metadata.get("execution_plan"), dict) else {}
    iterative = (
        metadata.get("iterative_investigation")
        if isinstance(metadata.get("iterative_investigation"), dict)
        else {}
    )
    rca_analysis = metadata.get("rca_analysis") if isinstance(metadata.get("rca_analysis"), dict) else {}
    lifecycle = metadata.get("resolution_lifecycle") if isinstance(metadata.get("resolution_lifecycle"), dict) else {}
    lifecycle_state = str(lifecycle.get("state") or "").strip().lower()
    accepted_evidence = [value for value in rca_analysis.get("evidence_used", []) if str(value).strip()]
    recommendation_ready = (
        iterative.get("conclusive") is True
        and bool(accepted_evidence)
        and plan.get("execution_ready") is True
        and plan.get("mutating") is True
    )
    if recommendation_ready and (requires_approval or lifecycle_state == "awaiting_approval"):
        return "awaiting_approval"
    if recommendation_ready and lifecycle_state == "ready_to_execute":
        return "approved"
    return "investigating"


async def _persist_resolution_event(
    *,
    app: FastAPI,
    context: Context,
    incident: Incident,
    recommendation: Recommendation,
    decision_payload: dict[str, Any],
) -> None:
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        return
    metadata = recommendation.metadata if isinstance(recommendation.metadata, dict) else {}
    orchestration = (
        metadata.get("orchestration_decision") if isinstance(metadata.get("orchestration_decision"), dict) else {}
    )
    requires_approval = decision_payload.get("requires_approval")
    if requires_approval is None:
        requires_approval = orchestration.get("requires_approval")
    status = _resolution_projection_status(metadata, requires_approval=bool(requires_approval))
    provider = decision_payload.get("message_bus_provider") or orchestration.get("message_bus_provider") or "unknown"
    async with app.state.session_factory() as session:
        repo = IncidentRepository(session)
        await repo.save_incident_event(
            build_event_envelope(
                event_type="incident.recommendation.generated",
                identity={
                    "incident_id": str(incident.id),
                    "alert_id": str(context.alert.id),
                    "trace_id": str(incident.trace_id or context.alert.trace_id or ""),
                    "correlation_id": str(context.alert.correlation_id or "") or None,
                    "causation_id": None,
                    "parent_event_id": None,
                },
                scope={
                    "tenant_id": context.tenant_id,
                    "service": str(context.alert.service or "unknown"),
                    "environment": str(context.alert.environment or "prod"),
                    "region": None,
                    "team": str(context.alert.metadata.get("owner_team") or "") or None,
                },
                state={
                    "severity": str(
                        getattr(context.alert.severity, "value", context.alert.severity) or "warning"
                    ).lower(),
                    "status": status,
                    "owner": None,
                },
                policy={
                    "risk_tier": str(decision_payload.get("risk_tier") or orchestration.get("risk_tier") or "unknown"),
                    "execution_mode": str(
                        decision_payload.get("execution_mode") or orchestration.get("execution_mode") or "unknown"
                    ),
                    "requires_approval": requires_approval,
                    "policy_version": decision_payload.get("policy_version")
                    or orchestration.get("policy_version")
                    or metadata.get("policy_version"),
                    "policy_reason": decision_payload.get("policy_reason")
                    or orchestration.get("policy_reason")
                    or metadata.get("policy_reason"),
                },
                transport={
                    "provider": str(provider),
                    "channel": RESOLUTION_EVENTS,
                    "partition": None,
                    "offset": None,
                    "delivery_tag": None,
                },
                ai={
                    "confidence": float(recommendation.confidence),
                    "model_provider": str(
                        (metadata.get("model_usage") or [{}])[0].get("provider")
                        if isinstance(metadata.get("model_usage"), list) and metadata.get("model_usage")
                        else ""
                    )
                    or None,
                    "model_name": str(
                        (metadata.get("model_usage") or [{}])[0].get("model")
                        if isinstance(metadata.get("model_usage"), list) and metadata.get("model_usage")
                        else ""
                    )
                    or None,
                    "fallback_reason": None,
                },
                payload={
                    "recommendation_id": str(recommendation.id),
                    "recommended_action": recommendation.recommended_action,
                    "root_cause": recommendation.root_cause,
                    "impact": recommendation.impact,
                    "risk": recommendation.risk,
                    "resolution_lifecycle": metadata.get("resolution_lifecycle") or None,
                    "analysis_request_id": metadata.get("analysis_request_id"),
                    "context_snapshot_id": metadata.get("context_snapshot_id"),
                    "context_fingerprint": metadata.get("context_fingerprint"),
                    "rca_version": metadata.get("rca_version"),
                    "recommendation_version": metadata.get("recommendation_version"),
                },
            )
        )
        iterative = metadata.get("iterative_investigation") if isinstance(metadata.get("iterative_investigation"), dict) else {}
        plan = metadata.get("execution_plan") if isinstance(metadata.get("execution_plan"), dict) else {}
        policy_decision = plan.get("policy_decision") if isinstance(plan.get("policy_decision"), dict) else {}
        evidence_ids = list((iterative.get("conclusion") or {}).get("evidence_ids") or [])
        transition_path: list[tuple[ResolutionWorkflowState, ResolutionWorkflowState, str]]
        if iterative.get("conclusive") is not True:
            transition_path = [(
                ResolutionWorkflowState.EVIDENCE_PENDING,
                ResolutionWorkflowState.ESCALATED,
                "evidence_inconclusive",
            )]
        else:
            policy_target = (
                ResolutionWorkflowState.AWAITING_APPROVAL
                if policy_decision.get("decision") == "hitl"
                else ResolutionWorkflowState.READY_TO_EXECUTE
                if policy_decision.get("decision") == "hotl"
                else ResolutionWorkflowState.ESCALATED
            )
            transition_path = [
                (ResolutionWorkflowState.EVIDENCE_PENDING, ResolutionWorkflowState.EVIDENCE_READY, "evidence_compiled"),
                (ResolutionWorkflowState.EVIDENCE_READY, ResolutionWorkflowState.HYPOTHESES_READY, "hypotheses_ranked"),
                (ResolutionWorkflowState.HYPOTHESES_READY, ResolutionWorkflowState.PLAN_SELECTED, "approved_runbook_selected"),
                (ResolutionWorkflowState.PLAN_SELECTED, ResolutionWorkflowState.POLICY_CHECKED, "policy_evaluated"),
                (ResolutionWorkflowState.POLICY_CHECKED, policy_target, str((policy_decision.get("reason_codes") or ["policy_decision"])[0])),
            ]
        for sequence, (previous_state, new_state, reason_code) in enumerate(transition_path, 1):
            event_id = uuid5(NAMESPACE_URL, f"kaims:resolution-transition:{recommendation.id}:{sequence}:{new_state.value}")
            transition_payload = {
                "tenant_id": context.tenant_id,
                "incident_id": str(incident.id),
                "recommendation_id": str(recommendation.id),
                "execution_plan_id": None,
                "previous_state": previous_state.value,
                "new_state": new_state.value,
                "event_id": str(event_id),
                "correlation_id": str(context.alert.correlation_id or "") or None,
                "causation_id": str(context.alert.id),
                "idempotency_key": transition_idempotency_key(str(incident.id), event_id, new_state),
                "actor": "resolution-agent",
                "reason_code": reason_code,
                "evidence_ids": evidence_ids,
                "policy_decision": policy_decision,
            }
            await repo.record_resolution_transition(transition_payload)
        await session.commit()
    knowledge_id = str(context.metadata.get("context_knowledge_id") or "").strip()
    if not knowledge_id:
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("attach_resolution", "not_linked").inc()
        return
    quality_score = _resolution_quality_score(recommendation.model_dump(mode="json"))
    if (
        not bool(getattr(settings, "context_resolution_reuse_enabled", True))
        or quality_score <= _resolution_reuse_threshold()
    ):
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("attach_resolution", "below_threshold").inc()
        return
    try:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            attached = await repo.attach_context_knowledge_resolution(
                knowledge_id,
                recommendation.model_dump(mode="json"),
            )
            await session.commit()
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("attach_resolution", "success" if attached else "not_found").inc()
    except Exception:
        CONTEXT_KNOWLEDGE_OPERATIONS.labels("attach_resolution", "error").inc()


async def startup(app: FastAPI) -> None:
    workers = max(1, int(getattr(settings, "message_bus_worker_count", 1) or 1))
    consumers: list[tuple[str, Any, ConsumeRunner]] = []
    for worker in range(workers):
        consumers.append(
            (f"rabbitmq-w{worker + 1}", RabbitMQConsumer(settings, CONTEXT_EVENTS), consume_rabbitmq_forever)
        )
    if settings.kafka_enabled and MESSAGE_BUS_DUAL_CONSUME_ENABLED:
        for worker in range(workers):
            consumers.insert(
                worker,
                (f"kafka-w{worker + 1}", KafkaConsumer(settings, CONTEXT_EVENTS), consume_kafka_forever),
            )

    async def handle(payload: dict) -> None:
        context = Context.model_validate(payload["context"])
        incident = Incident.model_validate(payload["incident"])
        await _require_context_snapshot_binding(context)
        decision_payload = payload.get("decision", {}) if isinstance(payload.get("decision"), dict) else {}
        recommendation = await _resolve_context(context)
        _attach_rca_governance_binding(recommendation, context)
        recommendation.trace_id = str(incident.trace_id or context.alert.trace_id or "") or None
        recommendation.metadata["rag_documents"] = context.metadata.get("rag_documents", 0)
        recommendation.metadata["rag_matches"] = context.metadata.get("rag_matches", [])
        recommendation.metadata["rag_top_similarity"] = context.metadata.get("rag_top_similarity", 0.0)
        recommendation.metadata["rag_service_tagged_match"] = context.metadata.get("rag_service_tagged_match", False)
        recommendation.metadata["discovery_report"] = context.metadata.get("discovery_report", {})
        recommendation.metadata["discovery_evidence"] = context.metadata.get("discovery_evidence", {})
        recommendation.metadata["runbook_found"] = bool(context.runbook)
        # Apply the reviewed catalog even on direct RCA reruns and legacy
        # messages whose orchestration decision predates execution-plan v2.
        catalog_plan = _apply_catalog_plan(recommendation, context, decision_payload)
        policy_version = str(decision_payload.get("policy_version") or "").strip()
        policy_reason = str(decision_payload.get("policy_reason") or "").strip()
        if policy_version:
            recommendation.metadata["policy_version"] = policy_version
        if policy_reason:
            recommendation.metadata["policy_reason"] = policy_reason
        if decision_payload:
            recommendation.metadata["orchestration_decision"] = {
                "workflow": decision_payload.get("workflow"),
                "requires_approval": decision_payload.get("requires_approval"),
                "message_bus_provider": decision_payload.get("message_bus_provider"),
                "stream_count": decision_payload.get("stream_count"),
                "stream_threshold": decision_payload.get("stream_threshold"),
                "execution_plan_fingerprint": catalog_plan.get("plan_fingerprint")
                if isinstance(catalog_plan, dict)
                else None,
            }
        if settings.database_enabled:
            async with app.state.session_factory() as session:
                repo = IncidentRepository(session)
                await repo.save_recommendation_as_audit(recommendation, tenant_id=context.tenant_id)
                await session.commit()
        await _persist_resolution_event(
            app=app,
            context=context,
            incident=incident,
            recommendation=recommendation,
            decision_payload=decision_payload,
        )
        payload_out = _build_resolution_event_payload(
            context=context,
            incident=incident,
            recommendation=recommendation,
            decision_payload=decision_payload,
        )
        await app.state.producer.publish(RESOLUTION_EVENTS, payload_out, key=str(context.incident_id))
        EVENTS_PROCESSED.labels(settings.service_name, CONTEXT_EVENTS, "ok").inc()

    for source, consumer, consume_forever in consumers:
        task = asyncio.create_task(consume_forever(consumer, handle), name=f"resolution-agent-{source}-consumer")
        tasks.append(task)


async def shutdown(_: FastAPI) -> None:
    for task in tasks:
        task.cancel()


app = create_app(title="KaiMS Resolution Intelligence Agent", settings=settings, startup=startup, shutdown=shutdown)


class ResolutionCatalogRequest(BaseModel):
    tenant_id: str
    incident_id: UUID
    alert_id: UUID
    analysis_request_id: UUID
    recommendation_id: UUID
    rca_version: int = Field(ge=1)
    context_snapshot_id: UUID
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    issue: str
    service: str = "unknown"
    environment: str = "unknown"
    recommended_action: str = ""


class ResolutionSelectionRequest(BaseModel):
    tenant_id: str
    incident_id: UUID
    alert_id: UUID
    analysis_request_id: UUID
    recommendation_id: UUID
    rca_version: int = Field(ge=1)
    context_snapshot_id: UUID
    context_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolution_plan_id: UUID | None = None
    plan_fingerprint: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    option_id: str
    issue: str
    service: str = "unknown"
    environment: str = "unknown"
    actor: str


async def _require_catalog_readiness(request: ResolutionCatalogRequest | ResolutionSelectionRequest) -> dict[str, Any]:
    tenant_id = require_tenant_id(request.tenant_id, source="resolution catalog readiness")
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "readiness_store_unavailable",
                "blocking_reasons": ["investigation persistence is unavailable"],
            },
        )
    async with app.state.session_factory() as session:
        repository = IncidentRepository(session)
        current = await repository.current_incident_investigation_binding(
            tenant_id=tenant_id, incident_id=request.incident_id, alert_id=request.alert_id,
        )
        if current is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "investigation_binding_missing",
                    "blocking_reasons": ["no current incident investigation binding exists"],
                },
            )
        if current["recommendation_id"] != str(request.recommendation_id):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "stale_recommendation",
                    "blocking_reasons": ["recommendation is not the incident projection's current version"],
                },
            )
        bound = await repository.get_bound_incident_investigation(
            tenant_id=tenant_id,
            incident_id=request.incident_id,
            alert_id=request.alert_id,
            recommendation_id=request.recommendation_id,
        )
    integrity = bound.get("investigation_integrity") if isinstance(bound.get("investigation_integrity"), dict) else {}
    if integrity.get("verified") is not True:
        raise HTTPException(status_code=409, detail={
            "code": f"investigation_{integrity.get('status') or 'invalid'}",
            "blocking_reasons": integrity.get("blocking_reasons") or ["investigation integrity is not verified"],
        })
    recommendation = bound.get("recommendation") if isinstance(bound.get("recommendation"), dict) else {}
    metadata = recommendation.get("metadata") if isinstance(recommendation.get("metadata"), dict) else {}
    identity_mismatches = []
    if str(metadata.get("analysis_request_id") or "") != str(request.analysis_request_id):
        identity_mismatches.append("analysis request does not match")
    if str(metadata.get("context_snapshot_id") or "") != str(request.context_snapshot_id):
        identity_mismatches.append("context snapshot does not match")
    if str(metadata.get("context_fingerprint") or "") != request.context_fingerprint:
        identity_mismatches.append("context fingerprint does not match")
    try:
        persisted_rca_version = int(metadata.get("rca_version") or 0)
    except (TypeError, ValueError):
        persisted_rca_version = 0
    if persisted_rca_version != request.rca_version:
        identity_mismatches.append("RCA version does not match")
    if identity_mismatches:
        raise HTTPException(
            status_code=409,
            detail={"code": "stale_investigation_binding", "blocking_reasons": identity_mismatches},
        )
    analysis = metadata.get("rca_analysis") if isinstance(metadata.get("rca_analysis"), dict) else {}
    investigation = (
        metadata.get("investigation_report")
        if isinstance(metadata.get("investigation_report"), dict)
        else {}
    )
    accepted = metadata.get("evidence_ids") if isinstance(metadata.get("evidence_ids"), list) else []
    blocks = []
    if investigation.get("conclusive") is not True or str(investigation.get("status") or "").lower() != "conclusive":
        blocks.append("investigation is not conclusive")
    if str(metadata.get("rca_status") or "").lower() != "grounded" or not accepted:
        blocks.append("RCA is not grounded in accepted evidence")
    if isinstance(analysis.get("missing_evidence"), list) and analysis["missing_evidence"]:
        blocks.append("declared evidence gaps remain")
    if isinstance(analysis.get("conflicting_evidence"), list) and analysis["conflicting_evidence"]:
        blocks.append("conflicting evidence remains unresolved")
    if blocks:
        raise HTTPException(status_code=409, detail={"code": "resolution_not_ready", "blocking_reasons": blocks})
    return bound


@app.get("/investigations/{incident_id}")
async def latest_investigation(incident_id: str, tenant_id: str) -> dict[str, Any]:
    tenant_id = require_tenant_id(tenant_id, source="investigation query")
    if not settings.database_enabled or getattr(app.state, "session_factory", None) is None:
        raise HTTPException(status_code=503, detail="investigation persistence is unavailable")
    async with app.state.session_factory() as session:
        report = await IncidentRepository(session).latest_resolution_investigation(
            incident_id, tenant_id=tenant_id,
        )
    if report is None:
        raise HTTPException(status_code=404, detail="resolution investigation not found")
    return report


class ExecutionFailureRequest(BaseModel):
    incident_id: UUID
    action_id: UUID
    action_type: str
    target: str
    service: str = "unknown"
    environment: str = "prod"
    error: str
    execution_result: dict[str, Any] = Field(default_factory=dict)
    previous_recommendation: dict[str, Any] = Field(default_factory=dict)
    attempt: int = Field(default=1, ge=1)


@app.post("/reconsider-execution")
async def reconsider_execution(request: ExecutionFailureRequest) -> dict[str, Any]:
    """Produce a new recommendation after a failed executor attempt.

    The response always requires a fresh human approval; it never retries a
    mutating operation directly from failure feedback.
    """
    previous = request.previous_recommendation
    previous_metadata = previous.get("metadata", {}) if isinstance(previous.get("metadata"), dict) else {}
    failure = request.error.strip()
    platform = os.getenv("REMEDIATION_EXECUTION_PLATFORM", "kubernetes").strip().lower()
    safe_service = "".join(ch for ch in request.service if ch.isalnum() or ch in "_.-") or "unknown"
    if platform in {"docker", "docker-compose", "compose"}:
        project = os.getenv("REMEDIATION_COMPOSE_PROJECT", "kaiops_azure").strip()
        safe_project = "".join(ch for ch in project if ch.isalnum() or ch in "_.-") or "kaiops_azure"
        container = f"{safe_project}-{safe_service}-1"
        commands = [
            f"curl --fail --silent --show-error -X POST http://docker-socket-proxy:2375/containers/{container}/restart?t=30",
            f"curl --fail --silent --show-error --retry 15 --retry-connrefused --retry-delay 2 http://{safe_service}:8000/healthz",
        ]
        rationale = (
            f"The previous executor attempt failed ({failure}). Re-plan against the configured Docker Compose runtime."
        )
    else:
        namespace = str(previous_metadata.get("namespace") or "default")
        commands = [
            f"kubectl rollout undo deployment/{request.target} -n {namespace}",
            f"kubectl rollout status deployment/{request.target} -n {namespace} --timeout=180s",
        ]
        rationale = (
            f"The previous executor attempt failed ({failure}). Verify Jenkins tooling "
            "and cluster credentials before approving this revised Kubernetes plan."
        )
    # A failed execution is evidence, not authority to synthesize another live
    # command. Re-enter planning with a non-executable contract; the normal
    # catalog resolver must produce and bind the replacement plan.
    proposed_commands = commands
    commands = []
    recommendation_id = uuid4()
    recommendation = {
        "id": str(recommendation_id),
        "incident_id": str(request.incident_id),
        "root_cause": f"Execution of {request.action_type} failed: {failure}",
        "confidence": 0.8,
        "impact": "Incident remains unresolved until a corrected execution plan succeeds and recovery is validated.",
        "recommended_action": f"Reconsider and retry {request.action_type} with the corrected executor plan",
        "severity": str(previous.get("severity") or "warning"),
        "rationale": rationale,
        "commands": commands,
        "risk": "high",
        "metadata": {
            **previous_metadata,
            "execution_plan": {
                "schema_version": "kaims.execution-plan.v2",
                "commands": [],
                "scripts": [],
                "queries": [f"http://{safe_service}:8000/healthz"],
                "preflight_commands": [],
                "validation_commands": [],
                "rollback_commands": [],
                "mutating": False,
                "plan_kind": "diagnostic",
                "execution_ready": False,
                "readiness_blocks": ["failed execution requires catalog re-planning against fresh evidence"],
            },
            "model_proposed_execution_plan": {"commands": proposed_commands},
            "execution_reconsideration_attempt": request.attempt,
            "failed_action_id": str(request.action_id),
            "failure_feedback": failure,
            "auto_approved": False,
        },
    }
    return {
        "recommendation": recommendation,
        "incident": {
            "id": str(request.incident_id),
            "service": request.service,
            "environment": request.environment,
            "severity": recommendation["severity"],
        },
        "decision": {
            "flow_id": str(request.incident_id),
            "requires_approval": True,
            "execution_mode": "human_approval",
            "risk_tier": "high",
            "policy_reason": "A failed execution must be re-planned and approved before retry.",
        },
    }


@app.post("/resolution-catalog/relevant")
async def resolution_catalog(request: ResolutionCatalogRequest) -> dict[str, Any]:
    tenant_id = require_tenant_id(request.tenant_id, source="resolution catalog request")
    await _require_catalog_readiness(request)
    rows = relevant_resolutions(
        issue=request.issue, service=request.service, recommended_action=request.recommended_action
    )
    best_relevance = float(rows[0].get("relevance") or 0.0) if rows else 0.0
    fallback = {"used": False, "cache_hit": False, "reason": None, "repository": "context-agent-rag", "error": None}
    if best_relevance < 0.35:
        fallback["reason"] = "No governed local option cleared the 0.35 relevance threshold."
        query = " ".join(
            part for part in (request.issue, request.service, request.recommended_action, "remediation runbook") if part
        ).strip()
        try:
            cache_key = f"{tenant_id}:" + " ".join(query.lower().split())
            cached = _GLOBAL_KNOWLEDGE_CACHE.get(cache_key)
            if cached and monotonic() - cached[0] < _GLOBAL_KNOWLEDGE_CACHE_TTL_SECONDS:
                matches = cached[1]
                fallback["cache_hit"] = True
            else:
                async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
                    response = await client.get(
                        f"{settings.context_agent_url.rstrip('/')}/rag/search",
                        params={"query": query, "limit": 6, "kind": "runbook", "tenant_id": tenant_id},
                    )
                    response.raise_for_status()
                    payload_matches = response.json().get("matches", [])
                matches = payload_matches if isinstance(payload_matches, list) else []
                if len(_GLOBAL_KNOWLEDGE_CACHE) >= _GLOBAL_KNOWLEDGE_CACHE_MAX_ENTRIES:
                    oldest_key = min(_GLOBAL_KNOWLEDGE_CACHE, key=lambda key: _GLOBAL_KNOWLEDGE_CACHE[key][0])
                    _GLOBAL_KNOWLEDGE_CACHE.pop(oldest_key, None)
                _GLOBAL_KNOWLEDGE_CACHE[cache_key] = (monotonic(), matches)
            knowledge_rows = register_global_knowledge(
                tenant_id=tenant_id,
                matches=matches if isinstance(matches, list) else [],
            )
            if knowledge_rows:
                rows = [*rows, *knowledge_rows]
                fallback["used"] = True
        except Exception as exc:
            fallback["error"] = str(exc)[:240]
    return {
        "rows": rows[:12],
        "catalog_size": len(RESOLUTION_CATALOG),
        "local_best_relevance": best_relevance,
        "global_knowledge_fallback": fallback,
    }


@app.post("/resolution-catalog/select")
async def select_resolution(request: ResolutionSelectionRequest) -> dict[str, Any]:
    tenant_id = require_tenant_id(request.tenant_id, source="resolution selection request")
    await _require_catalog_readiness(request)
    try:
        plan = prepare_resolution_plan(
            tenant_id=tenant_id,
            option_id=request.option_id,
            issue=request.issue,
            service=request.service,
        )
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=str(exc)) from exc
    plan["target_resource"] = request.service
    plan["connector_id"] = "diagnostic-only"
    plan["commands"] = []
    async with app.state.session_factory() as session:
        repository = IncidentRepository(session)
        try:
            persisted = await repository.persist_governed_resolution_selection(
                tenant_id=tenant_id,
                incident_id=request.incident_id,
                alert_id=request.alert_id,
                analysis_request_id=request.analysis_request_id,
                context_snapshot_id=request.context_snapshot_id,
                context_fingerprint=request.context_fingerprint,
                recommendation_id=request.recommendation_id,
                rca_version=request.rca_version,
                option=plan,
                selected_by=request.actor,
            )
            await session.commit()
        except ValueError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409,
                detail={"code": "stale_or_invalid_resolution_selection", "blocking_reasons": [str(exc)]},
            ) from exc
    return {"incident_id": str(request.incident_id), "selected": persisted}


@app.post("/resolve", response_model=Recommendation)
async def resolve(context: Context, publish_events: bool = True) -> Recommendation:
    await _require_context_snapshot_binding(context)
    recommendation = await _resolve_context(context)
    _attach_rca_governance_binding(recommendation, context)
    _apply_catalog_plan(recommendation, context)
    recommendation.trace_id = str(context.alert.trace_id or "") or None
    recommendation.metadata["rag_documents"] = context.metadata.get("rag_documents", 0)
    recommendation.metadata["rag_matches"] = context.metadata.get("rag_matches", [])
    recommendation.metadata["rag_top_similarity"] = context.metadata.get("rag_top_similarity", 0.0)
    recommendation.metadata["rag_service_tagged_match"] = context.metadata.get("rag_service_tagged_match", False)
    recommendation.metadata["discovery_report"] = context.metadata.get("discovery_report", {})
    recommendation.metadata["discovery_evidence"] = context.metadata.get("discovery_evidence", {})
    recommendation.metadata["runbook_found"] = bool(context.runbook)
    synthetic_incident = Incident(
        id=context.incident_id,
        service=context.alert.service,
        severity=context.alert.severity,
        title=f"{context.alert.service}: {context.alert.name}",
    )
    payload_out = _build_resolution_event_payload(
        context=context,
        incident=synthetic_incident,
        recommendation=recommendation,
        decision_payload={},
    )
    # Temporal invokes this endpoint with publish_events=false because it owns
    # durable orchestration and must not create a second bus delivery. The
    # recommendation is still a business result and must always be persisted;
    # previously it was returned to Temporal and then lost from the incident
    # projection, leaving the cockpit permanently stuck at "RCA pending".
    if settings.database_enabled:
        async with app.state.session_factory() as session:
            repo = IncidentRepository(session)
            await repo.save_recommendation_as_audit(recommendation)
            await session.commit()
    await _persist_resolution_event(
        app=app,
        context=context,
        incident=synthetic_incident,
        recommendation=recommendation,
        decision_payload={},
    )
    if publish_events:
        await app.state.producer.publish(RESOLUTION_EVENTS, payload_out)
    return recommendation
