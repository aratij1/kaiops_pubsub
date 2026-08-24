from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic
from typing import Any, Awaitable, Callable
from uuid import uuid4

import httpx

from ai_workbench_common.models import Context
from common.change_intelligence import ChangeCorrelationContext, ChangeEvent, rank_correlated_changes
from common.evidence_graph import build_incident_evidence_graph
from resolution_agent.contracts import (
    Hypothesis as HypothesisContract,
    HypothesisStatus,
    InvestigationPlan,
    InvestigationToolCall,
    RCAResult,
    ResolutionOutcome,
)
from resolution_agent.evidence import EvidenceCompiler
from resolution_agent.confidence import ConfidenceInputs, score_confidence
from resolution_agent.metrics import (
    EVIDENCE_COUNT,
    HYPOTHESIS_COUNT,
    INCONCLUSIVE_TOTAL,
    INVESTIGATION_DURATION,
    RESOLUTION_CONFIDENCE,
)


class InvestigationStatus(StrEnum):
    RUNNING = "running"
    CONCLUSIVE = "conclusive"
    INCONCLUSIVE = "inconclusive"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TOOL_FAILURE = "tool_failure"


PersistEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


class ReadOnlyDiscoveryClient:
    ALLOWED_TOOLS = frozenset({
        "logs.search", "code.search", "telemetry.search", "traces.search", "topology.search",
        "dependency-health.search", "changes.search", "runbooks.search", "tickets.search", "mysql.search",
    })

    def __init__(self) -> None:
        self.url = os.getenv("DISCOVERY_MCP_URL", "http://discovery-mcp:8000/mcp")
        self.timeout_seconds = max(2.0, min(float(os.getenv("RESOLUTION_INVESTIGATION_TOOL_TIMEOUT_SECONDS", "15")), 45.0))

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in self.ALLOWED_TOOLS:
            raise ValueError(f"investigation tool is not read-only or allow-listed: {tool_name}")
        request = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False) as client:
            response = await client.post(self.url, json=request)
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload.get("error"), dict):
            raise RuntimeError(str(payload["error"].get("message") or "discovery tool failed"))
        result = payload.get("result")
        if not isinstance(result, dict):
            return {}
        # KaiMS Discovery MCP returns the tool payload directly. Also accept the
        # standard MCP content envelope so a compliant remote server does not
        # silently produce zero evidence.
        if isinstance(result.get("evidence"), list):
            return result
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                try:
                    decoded = json.loads(str(item.get("text") or ""))
                except (TypeError, ValueError):
                    continue
                if isinstance(decoded, dict):
                    return decoded
        return result


class IterativeInvestigator:
    SOURCE_TOOL = {
        "logs": "logs.search",
        "code": "code.search",
        "telemetry": "telemetry.search",
        "traces": "traces.search",
        "topology": "topology.search",
        "dependency": "dependency-health.search",
        "changes": "changes.search",
        "runbooks": "runbooks.search",
        "history": "tickets.search",
        "data": "mysql.search",
    }
    SOURCE_ALIASES = {
        "log": "logs", "logs": "logs", "opensearch": "logs", "elasticsearch": "logs",
        "code": "code", "source": "code", "github": "code", "gitlab": "code",
        "prometheus": "telemetry", "metric": "telemetry", "metrics": "telemetry", "telemetry": "telemetry",
        "trace": "traces", "traces": "traces", "jaeger": "traces",
        "topology": "topology", "dependency": "dependency", "dependencies": "dependency",
        "change": "changes", "changes": "changes", "deployment": "changes",
        "runbook": "runbooks", "runbooks": "runbooks",
        "ticket": "history", "tickets": "history", "incident": "history", "rag": "history",
        "mysql": "data", "database": "data",
    }

    def __init__(self, client: ReadOnlyDiscoveryClient | None = None) -> None:
        self.client = client or ReadOnlyDiscoveryClient()
        self.evidence_compiler = EvidenceCompiler()
        self.max_steps = max(8, min(int(os.getenv("RESOLUTION_INVESTIGATION_MAX_STEPS", "8")), 12))
        self.max_evidence = max(8, min(int(os.getenv("RESOLUTION_INVESTIGATION_MAX_EVIDENCE", "40")), 100))
        self.max_tool_calls = max(1, min(int(os.getenv("RESOLUTION_INVESTIGATION_MAX_TOOL_CALLS", "12")), 100))
        self.max_duration_seconds = max(5, min(int(os.getenv("RESOLUTION_INVESTIGATION_MAX_DURATION_SECONDS", "120")), 3600))
        self.max_cost_usd = max(0.0, min(float(os.getenv("RESOLUTION_INVESTIGATION_MAX_COST_USD", "0.25")), 1000.0))
        self.conclusive_threshold = max(0.6, min(float(os.getenv("RESOLUTION_INVESTIGATION_CONCLUSIVE_THRESHOLD", "0.85")), 0.98))

    def plan(self, context: Context, *, investigation_id: str) -> InvestigationPlan:
        required = sorted(self._required_sources(context))
        service = context.alert.service
        questions = [
            f"What changed immediately before {service} became unhealthy?",
            f"Which direct evidence proves or disproves failure inside {service}?",
            f"Is a dependency, data store, or infrastructure resource causing the symptom in {service}?",
            "Which resources and dependent services are inside the blast radius?",
            "Is there an independently corroborated causal chain rather than a temporal coincidence?",
        ]
        text = " ".join((context.alert.name, context.alert.description)).lower()
        if any(token in text for token in ("deploy", "release", "exception", "traceback")):
            questions.insert(0, "Did the failure begin after a deployment, and is only the new version affected?")
        if any(token in text for token in ("database", "mysql", "query", "pool", "replica")):
            questions.insert(0, "Do database saturation or data-path diagnostics align with the application failure window?")
        calls = [
            InvestigationToolCall(
                tool_name=self.SOURCE_TOOL[source],
                objective=f"Collect {source} evidence that can support or falsify a hypothesis.",
                source_type=source,
                arguments={"service": service},
            )
            for source in required
        ]
        return InvestigationPlan(
            investigation_id=investigation_id,
            incident_id=context.incident_id,
            correlation_id=str(context.trace_id or context.incident_id),
            objectives=[
                "Identify a falsifiable causal explanation grounded in incident-window evidence.",
                "Disprove plausible competing hypotheses before recommending remediation.",
                "Return an explicit non-conclusive outcome when proof is insufficient.",
            ],
            questions_to_answer=questions,
            required_evidence=required,
            recommended_tool_calls=calls,
            investigation_priority=required,
            stop_conditions=[
                f"confidence >= {self.conclusive_threshold:.2f} with two independent evidence sources",
                "required evidence remains unavailable",
                "contradictory evidence cannot be resolved",
                "tool-call, duration, cost, or step budget is exhausted",
                "policy prevents further read access",
            ],
            max_steps=self.max_steps,
            max_tool_calls=self.max_tool_calls,
            max_duration_seconds=self.max_duration_seconds,
            max_cost_usd=self.max_cost_usd,
            minimum_confidence=self.conclusive_threshold,
        )

    def _compile_evidence(self, context: Context, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            record.model_dump(mode="json")
            for record in self.evidence_compiler.compile(
                rows,
                tenant_id=context.tenant_id,
                incident_id=context.incident_id,
                service=context.alert.service,
                environment=context.alert.environment,
            )
        ]

    @staticmethod
    def _tokens(value: Any) -> set[str]:
        ignored = {"after", "before", "service", "error", "failed", "failure", "issue", "alert", "prod", "production"}
        return {
            token for token in re.findall(r"[a-z0-9_.-]{3,}", str(value or "").lower())
            if token not in ignored
        }

    @classmethod
    def _source(cls, row: dict[str, Any]) -> str:
        return cls.SOURCE_ALIASES.get(
            str(row.get("source") or row.get("source_type") or "").strip().lower(), "alert"
        )

    @staticmethod
    def _initial_evidence(context: Context) -> list[dict[str, Any]]:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        buckets = metadata.get("context_evidence") if isinstance(metadata.get("context_evidence"), dict) else {}
        discovery = metadata.get("discovery_report") if isinstance(metadata.get("discovery_report"), dict) else {}
        rows: list[dict[str, Any]] = []
        for values in buckets.values():
            if isinstance(values, list):
                rows.extend(item for item in values if isinstance(item, dict))
        if isinstance(discovery.get("evidence"), list):
            rows.extend(item for item in discovery["evidence"] if isinstance(item, dict))
        unique: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(rows):
            key = str(row.get("evidence_id") or row.get("uri") or f"existing:{index}")
            unique[key] = row
        return list(unique.values())

    @staticmethod
    def _initial_hypotheses(context: Context) -> list[dict[str, Any]]:
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        discovery = metadata.get("discovery_report") if isinstance(metadata.get("discovery_report"), dict) else {}
        report = discovery.get("report") if isinstance(discovery.get("report"), dict) else {}
        candidates = report.get("hypotheses") if isinstance(report.get("hypotheses"), list) else []
        hypotheses: list[dict[str, Any]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            claim = str(item.get("claim") or item.get("cause") or item.get("summary") or "").strip()
            if not claim:
                continue
            hypotheses.append({
                "hypothesis_id": str(uuid4()),
                "claim": claim[:1000],
                "status": "viable",
                "confidence": max(0.05, min(float(item.get("confidence") or 0.35), 0.75)),
                "supporting_evidence_ids": list(item.get("evidence_ids") or item.get("evidence_used") or []),
                "contradicting_evidence_ids": [],
                "affected_resource_ids": list(item.get("affected_resource_ids") or []),
                "causal_sequence": list(item.get("causal_sequence") or []),
                "confidence_components": dict(item.get("confidence_components") or {}),
                "falsification_check": item.get("falsification_check") or item.get("falsification_query") or item.get("next_check") or {},
                "next_evidence_requests": list(item.get("next_evidence_requests") or []),
                "source": "context",
            })
        return hypotheses[:8]

    def _coverage(self, evidence: list[dict[str, Any]]) -> dict[str, int]:
        coverage = {source: 0 for source in self.SOURCE_TOOL}
        for row in evidence:
            source = self._source(row)
            if source in coverage:
                coverage[source] += 1
        return coverage

    @staticmethod
    def _change_events(context: Context, evidence: list[dict[str, Any]]) -> list[ChangeEvent]:
        source_map = {
            "github": "git_commit", "gitlab": "git_commit", "git": "git_commit",
            "deployment": "deployment", "jenkins": "jenkins", "argocd": "argocd",
            "terraform": "terraform", "servicenow": "servicenow_change",
            "feature_flag": "feature_flag", "database": "database", "config": "configuration",
        }
        events: list[ChangeEvent] = []
        for row in evidence:
            if row.get("source_type") != "change":
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            raw_source = str(metadata.get("change_source") or row.get("source_system") or "deployment").lower()
            source = next((value for key, value in source_map.items() if key in raw_source), "deployment")
            occurred_at = row.get("observed_at")
            if isinstance(occurred_at, str):
                try:
                    occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
                except ValueError:
                    continue
            if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
                continue
            target = str(row.get("target_resource_id") or "").strip()
            topology_ids = metadata.get("topology_resource_ids")
            topology_ids = topology_ids if isinstance(topology_ids, list) else []
            try:
                events.append(ChangeEvent(
                    change_id=str(metadata.get("change_id") or row.get("evidence_id") or ""),
                    tenant_id=context.tenant_id,
                    source=source,
                    source_event_id=str(metadata.get("source_event_id") or row.get("evidence_id") or ""),
                    occurred_at=occurred_at,
                    service=str(row.get("service") or context.alert.service),
                    environment=str(row.get("environment") or context.alert.environment),
                    resource_ids=[target] if target else [],
                    topology_resource_ids=[str(item) for item in topology_ids],
                    change_reference=str(row.get("source_uri") or metadata.get("uri") or row.get("evidence_id") or ""),
                    actor_reference=str(metadata.get("actor_reference") or "") or None,
                    version=str(metadata.get("version") or metadata.get("deployment") or "") or None,
                    evidence_ids=[str(row.get("evidence_id"))] if row.get("evidence_id") else [],
                    metadata={"source_system": row.get("source_system")},
                ))
            except ValueError:
                continue
        return events

    @staticmethod
    def _required_sources(context: Context) -> set[str]:
        text = " ".join((context.alert.name, context.alert.description, context.alert.service)).lower()
        required = {"logs", "telemetry", "topology", "dependency", "changes", "runbooks"}
        if any(token in text for token in ("latency", "timeout", "availability", "down", "error", "5xx")):
            required.add("traces")
        if any(token in text for token in ("deploy", "release", "config", "traceback", "exception")):
            required.add("code")
        if any(token in text for token in ("database", "mysql", "query", "replica", "table", "data")):
            required.add("data")
        if any(token in text for token in ("recurring", "repeat", "known issue", "regression")):
            required.add("history")
        return required

    def _select_tool(
        self,
        *,
        context: Context,
        evidence: list[dict[str, Any]],
        hypotheses: list[dict[str, Any]],
        tool_counts: dict[str, int],
    ) -> tuple[str, dict[str, Any]] | None:
        coverage = self._coverage(evidence)
        haystack = " ".join([
            context.alert.name, context.alert.description, context.alert.service,
            *(str(item.get("claim") or "") for item in hypotheses[:3]),
        ]).lower()
        priority = [
            "logs", "telemetry", "traces", "topology", "dependency", "changes", "runbooks",
            "code", "history", "data",
        ]
        if any(token in haystack for token in ("deploy", "release", "config", "stack", "traceback")):
            priority = ["changes", "code", "logs", "telemetry", "traces", "topology", "dependency", "runbooks", "history", "data"]
        elif any(token in haystack for token in ("database", "mysql", "query", "replica", "table")):
            priority = ["data", "logs", "telemetry", "topology", "dependency", "changes", "runbooks", "code", "history", "traces"]
        elif any(token in haystack for token in ("recurring", "repeat", "known issue")):
            priority = ["history", "logs", "telemetry", "topology", "dependency", "changes", "runbooks", "code", "data", "traces"]
        required = self._required_sources(context)
        priority = [source for source in priority if source in required]
        # An unavailable/empty source must not consume the entire investigation
        # budget. Query every required evidence plane once before issuing a
        # bounded refinement query to any one tool.
        source = next(
            (
                name
                for name in priority
                if coverage.get(name, 0) == 0
                and tool_counts.get(self.SOURCE_TOOL[name], 0) == 0
            ),
            None,
        )
        if source is None:
            # A second query to the same plane is allowed when it refines or
            # falsifies the leading hypothesis. Bound it to two calls per tool.
            source = min(
                (name for name in priority if tool_counts.get(self.SOURCE_TOOL[name], 0) < 2),
                key=lambda name: tool_counts.get(self.SOURCE_TOOL[name], 0),
                default=None,
            )
        if source is None:
            return None
        tool = self.SOURCE_TOOL[source]
        terms: list[str] = []
        for value in (
            context.alert.service, context.alert.name, context.alert.description,
            *(item.get("claim") for item in hypotheses[:2]),
        ):
            terms.extend(sorted(self._tokens(value)))
        terms = list(dict.fromkeys(terms))[:18]
        arguments: dict[str, Any] = {
            "terms": terms,
            "limit": min(10, self.max_evidence - len(evidence)),
            "service": context.alert.service,
            "application": context.alert.labels.get("application") or context.alert.service,
            "project": context.alert.labels.get("project") or context.alert.metadata.get("project"),
            "trace_id": context.alert.trace_id,
        }
        return tool, {key: value for key, value in arguments.items() if value not in (None, "", [])}

    def _revise_hypotheses(
        self,
        hypotheses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        *,
        context: Context,
    ) -> list[dict[str, Any]]:
        if not hypotheses:
            diagnostic = next(
                (
                    row for row in evidence
                    if self._source(row) in {"logs", "code", "telemetry", "data"}
                    and str(row.get("snippet") or row.get("summary") or "").strip()
                ),
                None,
            )
            if diagnostic:
                snippet = str(diagnostic.get("snippet") or diagnostic.get("summary"))[:500]
                hypotheses = [{
                    "hypothesis_id": str(uuid4()),
                    "claim": f"Observed signal requiring causal confirmation: {snippet}",
                    "status": "viable",
                    "confidence": 0.3,
                    "supporting_evidence_ids": [str(diagnostic.get("evidence_id"))] if diagnostic.get("evidence_id") else [],
                    "contradicting_evidence_ids": [],
                    "affected_resource_ids": [], "causal_sequence": [], "confidence_components": {},
                    "falsification_check": {"objective": "Find an independent source that confirms the causal mechanism."},
                    "next_evidence_requests": [],
                    "source": "derived_observation",
                }]
        # Keep a falsifiable 3-5 candidate set.  These are investigation
        # branches, not asserted causes: their deliberately low initial score
        # cannot authorize a plan without independent supporting evidence.
        mechanisms = [
            ("recent_change", f"A recent code or configuration change affected {context.alert.service}.", "Query deployment and code history around the alert onset."),
            ("dependency", f"An unhealthy upstream or downstream dependency is degrading {context.alert.service}.", "Query topology and dependency health for temporal correlation."),
            ("resource_or_data", f"Resource saturation or a data-path constraint is affecting {context.alert.service}.", "Query resource telemetry and data-store health over the incident window."),
            ("traffic", f"A traffic or workload shift exceeded the operating envelope of {context.alert.service}.", "Compare request volume, latency, errors, and capacity before and after onset."),
        ]
        existing_claims = {str(item.get("claim") or "").strip().lower() for item in hypotheses}
        for mechanism, claim, objective in mechanisms:
            if len(hypotheses) >= 3:
                break
            if claim.lower() in existing_claims:
                continue
            hypotheses.append({
                "hypothesis_id": hypothesis_digest(f"{context.incident_id}:{mechanism}")[:24],
                "claim": claim,
                "status": "candidate",
                "confidence": 0.0,
                "supporting_evidence_ids": [],
                "contradicting_evidence_ids": [],
                "affected_resource_ids": [], "causal_sequence": [], "confidence_components": {},
                "falsification_check": {"objective": objective}, "next_evidence_requests": [],
                "source": "mechanism_candidate",
            })
            existing_claims.add(claim.lower())
        hypotheses = hypotheses[:5]
        coverage = self._coverage(evidence)
        required_sources = self._required_sources(context)
        change_events = self._change_events(context, evidence)
        for hypothesis in hypotheses:
            claim_tokens = self._tokens(hypothesis.get("claim"))
            support: list[str] = []
            sources: set[str] = set()
            contradiction: list[str] = []
            for row in evidence:
                evidence_id = str(row.get("evidence_id") or "")
                text = " ".join(str(row.get(key) or "") for key in ("snippet", "summary", "content", "title"))
                overlap = claim_tokens.intersection(self._tokens(text))
                if len(overlap) >= 2 or (claim_tokens and len(overlap) / len(claim_tokens) >= 0.35):
                    if evidence_id:
                        support.append(evidence_id)
                    if row.get("metadata", {}).get("current_operational_evidence", True):
                        sources.add(self._source(row))
                if evidence_id and any(token in text.lower() for token in ("healthy", "normal", "no errors", "recovered")) and overlap:
                    contradiction.append(evidence_id)
            supporting_rows = [row for row in evidence if str(row.get("evidence_id") or "") in set(support)]
            fresh_support = [
                row for row in supporting_rows
                if int(row.get("freshness_seconds") or 0) <= 900
                and row.get("metadata", {}).get("current_operational_evidence", True)
            ]
            temporal_alignment = len(fresh_support) / max(1, len(supporting_rows))
            topology_support = 1.0 if any(row.get("source_type") in {"topology", "dependency"} for row in supporting_rows) else (
                0.5 if len({str(row.get("service") or "") for row in supporting_rows if row.get("service")}) > 1 else 0.0
            )
            affected_resources = [str(item) for item in hypothesis.get("affected_resource_ids") or []]
            alert_resource = str(context.alert.labels.get("resource_id") or "").strip()
            if alert_resource and alert_resource not in affected_resources:
                affected_resources.append(alert_resource)
            correlated_changes = rank_correlated_changes(
                change_events,
                ChangeCorrelationContext(
                    tenant_id=context.tenant_id,
                    incident_started_at=context.alert.starts_at,
                    service=context.alert.service,
                    environment=context.alert.environment,
                    affected_resource_ids=affected_resources,
                    topology_resource_ids=[str(item) for item in context.metadata.get("topology_resource_ids", [])],
                ),
            ) if change_events else []
            change_correlation = max(
                (item.change_correlation_score for item in correlated_changes), default=0.0
            )
            for item in correlated_changes:
                if item.change_correlation_score >= 0.55:
                    support.extend(evidence_id for evidence_id in item.evidence_ids if evidence_id)
                    sources.add("changes")
            supporting_rows = [row for row in evidence if str(row.get("evidence_id") or "") in set(support)]
            fresh_support = [
                row for row in supporting_rows
                if int(row.get("freshness_seconds") or 0) <= 900
                and row.get("metadata", {}).get("current_operational_evidence", True)
            ]
            temporal_alignment = len(fresh_support) / max(1, len(supporting_rows))
            topology_support = 1.0 if any(
                row.get("source_type") in {"topology", "dependency"} for row in supporting_rows
            ) else topology_support
            historical_similarities = [
                float(row.get("metadata", {}).get("similarity"))
                for row in evidence
                if row.get("source_type") == "ticket"
                and row.get("metadata", {}).get("reviewed") is True
                and row.get("metadata", {}).get("similarity") is not None
            ]
            tested_rows = [
                row for row in supporting_rows
                if row.get("metadata", {}).get("test_passed") is not None
            ]
            successful_test_ratio = (
                sum(1 for row in tested_rows if row.get("metadata", {}).get("test_passed") is True)
                / len(tested_rows)
                if tested_rows else 0.0
            )
            evidence_quality = (
                sum(float(row.get("reliability_score") or 0.0) for row in supporting_rows)
                / len(supporting_rows)
                if supporting_rows else 0.0
            )
            consistency = len(support) / max(1, len(support) + len(contradiction))
            causal_strength = min(
                1.0,
                (0.35 * temporal_alignment)
                + (0.25 * topology_support)
                + (0.20 * successful_test_ratio)
                + (0.20 * change_correlation),
            )
            completeness = sum(1 for source in required_sources if coverage.get(source, 0)) / max(1, len(required_sources))
            scored = score_confidence(ConfidenceInputs(
                evidence_quality=evidence_quality,
                evidence_consistency=consistency,
                causal_strength=causal_strength,
                independent_source_corroboration=min(len(sources) / 3, 1.0),
                temporal_alignment=temporal_alignment,
                topology_alignment=topology_support,
                historical_similarity=(
                    sum(historical_similarities) / len(historical_similarities)
                    if historical_similarities else 0.0
                ),
                successful_test_ratio=successful_test_ratio,
                contradiction_penalty=min(len(set(contradiction)) * 0.1, 0.35),
                freshness_penalty=0.15 if supporting_rows and not fresh_support else 0.0,
                missing_data_penalty=(1.0 - completeness) * 0.2,
                sources_unavailable=any(coverage.get(source, 0) == 0 for source in required_sources),
                stale_evidence=bool(supporting_rows and not fresh_support),
                model_fallback=bool(context.metadata.get("model_fallback")),
                degraded_context=bool(context.metadata.get("degraded_context")),
                unresolved_contradictions=bool(contradiction),
                ambiguous_target=not bool(str(context.alert.service or "").strip()),
            ))
            contradiction_ids = list(dict.fromkeys(contradiction))[:20]
            hypothesis["supporting_evidence_ids"] = [
                evidence_id for evidence_id in dict.fromkeys(support)
                if evidence_id not in set(contradiction_ids)
            ][:20]
            hypothesis["contradicting_evidence_ids"] = contradiction_ids
            hypothesis["independent_sources"] = sorted(sources)
            hypothesis["temporal_alignment"] = round(temporal_alignment, 4)
            hypothesis["topology_support"] = round(topology_support, 4)
            hypothesis["change_correlation"] = round(change_correlation, 4)
            hypothesis["correlated_changes"] = [item.model_dump(mode="json") for item in correlated_changes[:5]]
            hypothesis["independent_source_count"] = len(sources)
            hypothesis["confidence"] = scored.score
            hypothesis["confidence_breakdown"] = {
                "raw_score": scored.raw_score,
                "ceiling": scored.ceiling,
                "components": scored.components,
                "penalties": scored.penalties,
                "ceiling_reasons": list(scored.ceiling_reasons),
            }
            hypothesis["confidence_components"] = scored.components
            hypothesis["status"] = (
                "confirmed" if hypothesis["confidence"] >= self.conclusive_threshold and len(sources) >= 2
                else "falsified" if hypothesis["confidence"] <= 0.15 and bool(contradiction)
                else "leading" if hypothesis["confidence"] >= 0.55
                else "candidate"
            )
        return sorted(hypotheses, key=lambda item: float(item.get("confidence") or 0), reverse=True)

    async def investigate(self, context: Context, *, persist: PersistEvent | None = None) -> dict[str, Any]:
        investigation_started = monotonic()
        investigation_id = str(uuid4())
        investigation_plan = self.plan(context, investigation_id=investigation_id)
        evidence = self._compile_evidence(context, self._initial_evidence(context))[: self.max_evidence]
        hypotheses = self._revise_hypotheses(self._initial_hypotheses(context), evidence, context=context)
        started_at = datetime.now(UTC).isoformat()
        tool_counts: dict[str, int] = {}
        steps: list[dict[str, Any]] = []
        if persist:
            await persist("started", {
                "investigation_id": investigation_id,
                "incident_id": str(context.incident_id),
                "alert_id": str(context.alert.id),
                "tenant_id": str(context.alert.tenant_id or "default"),
                "status": InvestigationStatus.RUNNING.value,
                "step_budget": self.max_steps,
                "evidence_count": len(evidence),
                "correlation_id": investigation_plan.correlation_id,
                "investigation_plan": investigation_plan.model_dump(mode="json"),
            })

        status = InvestigationStatus.RUNNING
        stop_reason = ""
        for sequence in range(1, self.max_steps + 1):
            if monotonic() - investigation_started >= self.max_duration_seconds:
                status, stop_reason = InvestigationStatus.BUDGET_EXHAUSTED, "duration_budget_exhausted"
                break
            if sum(tool_counts.values()) >= self.max_tool_calls:
                status, stop_reason = InvestigationStatus.BUDGET_EXHAUSTED, "tool_call_budget_exhausted"
                break
            leading = hypotheses[0] if hypotheses else None
            if (
                leading
                and leading.get("status") == "confirmed"
                and len(leading.get("supporting_evidence_ids") or []) >= 2
            ):
                status, stop_reason = InvestigationStatus.CONCLUSIVE, "corroborated_leading_hypothesis"
                break
            selection = self._select_tool(
                context=context, evidence=evidence, hypotheses=hypotheses, tool_counts=tool_counts,
            )
            if selection is None:
                status, stop_reason = InvestigationStatus.INCONCLUSIVE, "no_additional_read_only_tool"
                break
            tool_name, arguments = selection
            tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
            step_id = str(uuid4())
            step_started = datetime.now(UTC).isoformat()
            try:
                result = await self.client.call(tool_name, arguments)
                rows = result.get("evidence") if isinstance(result.get("evidence"), list) else []
                combined = self._compile_evidence(
                    context,
                    [*evidence, *(row for row in rows if isinstance(row, dict))],
                )[: self.max_evidence]
                existing = {str(row.get("evidence_id") or "") for row in evidence}
                new_rows = [row for row in combined if str(row.get("evidence_id") or "") not in existing]
                evidence = combined
                hypotheses = self._revise_hypotheses(hypotheses, evidence, context=context)
                step = {
                    "step_id": step_id,
                    "sequence_no": sequence,
                    "tool_name": tool_name,
                    "query": arguments,
                    "status": "completed",
                    "result_count": len(new_rows),
                    "evidence_ids": [str(row.get("evidence_id")) for row in new_rows if row.get("evidence_id")],
                    "hypothesis_updates": hypotheses,
                    "started_at": step_started,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            except Exception as exc:
                step = {
                    "step_id": step_id,
                    "sequence_no": sequence,
                    "tool_name": tool_name,
                    "query": arguments,
                    "status": "failed",
                    "result_count": 0,
                    "evidence_ids": [],
                    "hypothesis_updates": hypotheses,
                    "error": str(exc)[:1000],
                    "started_at": step_started,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            steps.append(step)
            if persist:
                await persist("step", {"investigation_id": investigation_id, **step})
            if len(evidence) >= self.max_evidence:
                status, stop_reason = InvestigationStatus.BUDGET_EXHAUSTED, "evidence_budget_exhausted"
                break

        if status == InvestigationStatus.RUNNING:
            leading = hypotheses[0] if hypotheses else None
            if leading and leading.get("status") == "confirmed":
                status, stop_reason = InvestigationStatus.CONCLUSIVE, "corroborated_leading_hypothesis"
            else:
                status, stop_reason = InvestigationStatus.BUDGET_EXHAUSTED, "step_budget_exhausted"
        coverage = self._coverage(evidence)
        required_sources = self._required_sources(context)
        missing = [source for source in required_sources if coverage.get(source, 0) == 0]
        leading = hypotheses[0] if hypotheses else None
        contradictory = list(leading.get("contradicting_evidence_ids") or []) if leading else []
        failed_steps = [step for step in steps if step.get("status") == "failed"]
        if status == InvestigationStatus.CONCLUSIVE:
            outcome = ResolutionOutcome.EVIDENCE_SUPPORTED
        elif contradictory:
            outcome = ResolutionOutcome.CONFLICTING_EVIDENCE
        elif failed_steps and len(failed_steps) == len(steps):
            outcome = ResolutionOutcome.CONNECTOR_FAILURE
        elif missing or status == InvestigationStatus.BUDGET_EXHAUSTED:
            outcome = ResolutionOutcome.INSUFFICIENT_EVIDENCE
        else:
            outcome = ResolutionOutcome.UNKNOWN
        confidence_breakdown = leading.get("confidence_breakdown") if leading else {}
        confidence_breakdown = confidence_breakdown if isinstance(confidence_breakdown, dict) else {}
        typed_hypotheses = []
        status_map = {
            "confirmed": HypothesisStatus.SUPPORTED,
            "falsified": HypothesisStatus.REJECTED,
            "leading": HypothesisStatus.TESTING,
            "candidate": HypothesisStatus.PROPOSED,
            "viable": HypothesisStatus.PROPOSED,
        }
        for hypothesis in hypotheses:
            claim = str(hypothesis.get("claim") or "").strip()
            typed_hypotheses.append(HypothesisContract(
                hypothesis_id=str(hypothesis.get("hypothesis_id") or uuid4()),
                incident_id=context.incident_id,
                correlation_id=investigation_plan.correlation_id,
                title=claim[:160] or "Unresolved causal hypothesis",
                description=claim or "No causal claim was available.",
                suspected_component=str(context.alert.service or "unknown"),
                suspected_change=None,
                probability=float(hypothesis.get("confidence") or 0.0),
                status=status_map.get(str(hypothesis.get("status") or ""), HypothesisStatus.INCONCLUSIVE),
                supporting_evidence_ids=list(hypothesis.get("supporting_evidence_ids") or []),
                contradicting_evidence_ids=list(hypothesis.get("contradicting_evidence_ids") or []),
                required_tests=[str((hypothesis.get("falsification_check") or {}).get("objective") or "Collect independent causal evidence.")],
                reasoning_summary=str(hypothesis.get("reasoning_summary") or "Probability is computed from evidence factors, not model self-assessment."),
                confidence_factors=dict(confidence_breakdown.get("components") or {}),
                confidence_penalties=dict(confidence_breakdown.get("penalties") or {}),
                affected_resource_ids=list(hypothesis.get("affected_resource_ids") or []),
                causal_path=[str(item) for item in hypothesis.get("causal_sequence") or []],
                recommended_next_diagnostic=str(
                    (hypothesis.get("falsification_check") or {}).get("objective")
                    or "Collect independent causal evidence."
                ),
            ).model_dump(mode="json"))
        rca_result = RCAResult(
            incident_id=context.incident_id,
            correlation_id=investigation_plan.correlation_id,
            outcome=outcome,
            root_cause=str(leading.get("claim")) if outcome == ResolutionOutcome.EVIDENCE_SUPPORTED and leading else None,
            leading_hypothesis_id=str(leading.get("hypothesis_id")) if outcome == ResolutionOutcome.EVIDENCE_SUPPORTED and leading else None,
            confidence=float(leading.get("confidence") or 0.0) if leading else 0.0,
            supporting_evidence_ids=list(leading.get("supporting_evidence_ids") or []) if leading else [],
            contradicting_evidence_ids=contradictory,
            factors=dict(confidence_breakdown.get("components") or {}),
            penalties=dict(confidence_breakdown.get("penalties") or {}),
            missing_evidence=missing,
        )
        graph_gaps = [*missing]
        if contradictory:
            graph_gaps.append("unresolved_contradicting_evidence")
        if not hypotheses:
            graph_gaps.append("no_falsifiable_hypothesis")
        evidence_graph = build_incident_evidence_graph(
            tenant_id=context.tenant_id,
            incident_id=context.incident_id,
            evidence=evidence,
            hypotheses=hypotheses,
            conclusive_primary_id=(
                str(leading.get("hypothesis_id"))
                if outcome == ResolutionOutcome.EVIDENCE_SUPPORTED and leading
                else None
            ),
            data_gaps=graph_gaps,
        )
        report = {
            "schema_version": "kaims.iterative-investigation.v1",
            "investigation_id": investigation_id,
            "correlation_id": investigation_plan.correlation_id,
            "incident_id": str(context.incident_id),
            "alert_id": str(context.alert.id),
            "status": status.value,
            "stop_reason": stop_reason,
            "conclusive": status == InvestigationStatus.CONCLUSIVE,
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "step_budget": self.max_steps,
            "steps_used": len(steps),
            "evidence_budget": self.max_evidence,
            "evidence_count": len(evidence),
            "source_coverage": coverage,
            "missing_sources": missing,
            "investigation_plan": investigation_plan.model_dump(mode="json"),
            "steps": steps,
            "hypotheses": hypotheses,
            "typed_hypotheses": typed_hypotheses,
            "outcome": outcome.value,
            "rca_result": rca_result.model_dump(mode="json"),
            "evidence_graph": evidence_graph.model_dump(mode="json"),
            "change_intelligence": {
                "correlations": list(leading.get("correlated_changes") or []) if leading else [],
                "change_correlation_score": float(leading.get("change_correlation") or 0.0) if leading else 0.0,
                "causal_proof": False,
            },
            "conclusion": {
                "hypothesis_id": leading.get("hypothesis_id") if leading else None,
                "claim": leading.get("claim") if leading else None,
                "confidence": leading.get("confidence") if leading else 0.0,
                "evidence_ids": leading.get("supporting_evidence_ids", []) if leading else [],
            },
            "next_evidence": [
                {"source": source, "tool": self.SOURCE_TOOL[source], "reason": "required evidence plane is missing"}
                for source in missing[:3]
            ],
            "evidence": evidence,
        }
        if persist:
            await persist("completed", report)
        INVESTIGATION_DURATION.observe(monotonic() - investigation_started)
        EVIDENCE_COUNT.set(len(evidence))
        HYPOTHESIS_COUNT.set(len(hypotheses))
        RESOLUTION_CONFIDENCE.set(float((report.get("conclusion") or {}).get("confidence") or 0.0))
        if not report["conclusive"]:
            INCONCLUSIVE_TOTAL.inc()
        return report


def hypothesis_digest(claim: str) -> str:
    return hashlib.sha256(str(claim or "").strip().lower().encode()).hexdigest()
