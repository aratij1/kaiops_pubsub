from __future__ import annotations

import hashlib
import os
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Awaitable, Callable
from uuid import uuid4

import httpx

from ai_workbench_common.models import Context


class InvestigationStatus(StrEnum):
    RUNNING = "running"
    CONCLUSIVE = "conclusive"
    INCONCLUSIVE = "inconclusive"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TOOL_FAILURE = "tool_failure"


PersistEvent = Callable[[str, dict[str, Any]], Awaitable[None]]


class ReadOnlyDiscoveryClient:
    ALLOWED_TOOLS = frozenset({
        "logs.search", "code.search", "telemetry.search", "tickets.search", "mysql.search",
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
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(self.url, json=request)
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload.get("error"), dict):
            raise RuntimeError(str(payload["error"].get("message") or "discovery tool failed"))
        result = payload.get("result")
        return result if isinstance(result, dict) else {}


class IterativeInvestigator:
    SOURCE_TOOL = {
        "logs": "logs.search",
        "code": "code.search",
        "telemetry": "telemetry.search",
        "history": "tickets.search",
        "data": "mysql.search",
    }
    SOURCE_ALIASES = {
        "log": "logs", "logs": "logs", "opensearch": "logs", "elasticsearch": "logs",
        "code": "code", "source": "code", "github": "code", "gitlab": "code",
        "prometheus": "telemetry", "metric": "telemetry", "metrics": "telemetry", "telemetry": "telemetry",
        "ticket": "history", "tickets": "history", "incident": "history", "rag": "history",
        "mysql": "data", "database": "data",
    }

    def __init__(self, client: ReadOnlyDiscoveryClient | None = None) -> None:
        self.client = client or ReadOnlyDiscoveryClient()
        self.max_steps = max(1, min(int(os.getenv("RESOLUTION_INVESTIGATION_MAX_STEPS", "4")), 10))
        self.max_evidence = max(8, min(int(os.getenv("RESOLUTION_INVESTIGATION_MAX_EVIDENCE", "40")), 100))
        self.conclusive_threshold = max(0.5, min(float(os.getenv("RESOLUTION_INVESTIGATION_CONCLUSIVE_THRESHOLD", "0.78")), 0.98))

    @staticmethod
    def _tokens(value: Any) -> set[str]:
        ignored = {"after", "before", "service", "error", "failed", "failure", "issue", "alert", "prod", "production"}
        return {
            token for token in re.findall(r"[a-z0-9_.-]{3,}", str(value or "").lower())
            if token not in ignored
        }

    @classmethod
    def _source(cls, row: dict[str, Any]) -> str:
        return cls.SOURCE_ALIASES.get(str(row.get("source") or "").strip().lower(), "alert")

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
            claim = str(item.get("cause") or item.get("summary") or "").strip()
            if not claim:
                continue
            hypotheses.append({
                "hypothesis_id": str(uuid4()),
                "claim": claim[:1000],
                "status": "viable",
                "confidence": max(0.05, min(float(item.get("confidence") or 0.35), 0.75)),
                "supporting_evidence_ids": list(item.get("evidence_ids") or item.get("evidence_used") or []),
                "contradicting_evidence_ids": [],
                "falsification_query": item.get("falsification_query") or item.get("next_check") or {},
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

    def _select_tool(
        self,
        *,
        context: Context,
        evidence: list[dict[str, Any]],
        hypotheses: list[dict[str, Any]],
        used_tools: set[str],
    ) -> tuple[str, dict[str, Any]] | None:
        coverage = self._coverage(evidence)
        haystack = " ".join([
            context.alert.name, context.alert.description, context.alert.service,
            *(str(item.get("claim") or "") for item in hypotheses[:3]),
        ]).lower()
        priority = ["logs", "telemetry", "code", "history", "data"]
        if any(token in haystack for token in ("deploy", "release", "config", "stack", "traceback")):
            priority = ["code", "logs", "telemetry", "history", "data"]
        elif any(token in haystack for token in ("database", "mysql", "query", "replica", "table")):
            priority = ["data", "logs", "telemetry", "code", "history"]
        elif any(token in haystack for token in ("recurring", "repeat", "known issue")):
            priority = ["history", "logs", "telemetry", "code", "data"]
        source = next(
            (name for name in priority if self.SOURCE_TOOL[name] not in used_tools and coverage.get(name, 0) == 0),
            None,
        )
        if source is None:
            source = next((name for name in priority if self.SOURCE_TOOL[name] not in used_tools), None)
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
                    "falsification_query": {"objective": "Find an independent source that confirms the causal mechanism."},
                    "source": "derived_observation",
                }]
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
                    sources.add(self._source(row))
                if evidence_id and any(token in text.lower() for token in ("healthy", "normal", "no errors", "recovered")) and overlap:
                    contradiction.append(evidence_id)
            base = min(float(hypothesis.get("confidence") or 0.2), 0.6)
            score = base + min(0.22, 0.07 * len(set(support))) + min(0.18, 0.08 * max(0, len(sources) - 1))
            score -= min(0.25, 0.1 * len(set(contradiction)))
            hypothesis["supporting_evidence_ids"] = list(dict.fromkeys(support))[:20]
            hypothesis["contradicting_evidence_ids"] = list(dict.fromkeys(contradiction))[:20]
            hypothesis["independent_sources"] = sorted(sources)
            hypothesis["confidence"] = round(max(0.05, min(score, 0.95)), 4)
            hypothesis["status"] = (
                "confirmed" if hypothesis["confidence"] >= self.conclusive_threshold and len(sources) >= 2
                else "falsified" if hypothesis["confidence"] <= 0.15 and bool(contradiction)
                else "leading" if hypothesis["confidence"] >= 0.55
                else "viable"
            )
        return sorted(hypotheses, key=lambda item: float(item.get("confidence") or 0), reverse=True)

    async def investigate(self, context: Context, *, persist: PersistEvent | None = None) -> dict[str, Any]:
        investigation_id = str(uuid4())
        evidence = self._initial_evidence(context)[: self.max_evidence]
        hypotheses = self._revise_hypotheses(self._initial_hypotheses(context), evidence, context=context)
        started_at = datetime.now(UTC).isoformat()
        used_tools: set[str] = set()
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
            })

        status = InvestigationStatus.RUNNING
        stop_reason = ""
        for sequence in range(1, self.max_steps + 1):
            leading = hypotheses[0] if hypotheses else None
            if (
                leading
                and leading.get("status") == "confirmed"
                and len(leading.get("supporting_evidence_ids") or []) >= 2
            ):
                status, stop_reason = InvestigationStatus.CONCLUSIVE, "corroborated_leading_hypothesis"
                break
            selection = self._select_tool(
                context=context, evidence=evidence, hypotheses=hypotheses, used_tools=used_tools,
            )
            if selection is None:
                status, stop_reason = InvestigationStatus.INCONCLUSIVE, "no_additional_read_only_tool"
                break
            tool_name, arguments = selection
            used_tools.add(tool_name)
            step_id = str(uuid4())
            step_started = datetime.now(UTC).isoformat()
            try:
                result = await self.client.call(tool_name, arguments)
                rows = result.get("evidence") if isinstance(result.get("evidence"), list) else []
                existing = {str(row.get("evidence_id") or row.get("uri") or "") for row in evidence}
                new_rows = [
                    row for row in rows if isinstance(row, dict)
                    and str(row.get("evidence_id") or row.get("uri") or "") not in existing
                ][: max(0, self.max_evidence - len(evidence))]
                evidence.extend(new_rows)
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
        missing = [source for source, count in coverage.items() if count == 0]
        leading = hypotheses[0] if hypotheses else None
        report = {
            "schema_version": "kaims.iterative-investigation.v1",
            "investigation_id": investigation_id,
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
            "steps": steps,
            "hypotheses": hypotheses,
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
        return report


def hypothesis_digest(claim: str) -> str:
    return hashlib.sha256(str(claim or "").strip().lower().encode()).hexdigest()
