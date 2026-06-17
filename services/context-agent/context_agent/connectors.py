from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from common.embeddings import HashingEmbeddingModel, cosine_similarity
from common.models import Alert, Context, Incident
from common.resilience import retry_async


class BaseConnector:
    name = "base"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        raise NotImplementedError


class ServiceNowConnector(BaseConnector):
    name = "servicenow"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"ticket": incident.ticket_id, "change_records": [{"id": "CHG-1024", "service": alert.service}]}


class PrometheusConnector(BaseConnector):
    name = "prometheus"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"latency_p95_ms": 1250, "cpu_percent": 71, "error_rate": 0.08, "alerts_cleared": False}


class KubernetesConnector(BaseConnector):
    name = "kubernetes"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"namespace": alert.environment, "deployment": alert.labels.get("deployment", alert.service)}


class JenkinsConnector(BaseConnector):
    name = "jenkins"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"recent_deployments": [{"version": "Deployment 2.5", "status": "success"}]}


class GitHubConnector(BaseConnector):
    name = "github"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {"recent_commits": [{"sha": "abc1234", "message": "Tune payment timeout"}]}


class CMDBConnector(BaseConnector):
    name = "cmdb"

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        return {
            "owner_team": alert.metadata.get("owner_team", "platform-ops"),
            "tier": "tier-1" if alert.service in {"payments", "checkout"} else "tier-2",
            "dependencies": ["checkout", "ledger", "fraud"] if alert.service == "payments" else [],
        }


@dataclass
class VectorDBConnector(BaseConnector):
    name: str = "vector-db"
    embedding_model: HashingEmbeddingModel = field(default_factory=HashingEmbeddingModel)
    documents: list[dict[str, str]] = field(
        default_factory=lambda: [
            {
                "kind": "runbook",
                "title": "payments latency rollback",
                "content": "If payment latency follows Deployment 2.5, rollback payments-api.",
            },
            {
                "kind": "incident",
                "title": "INC-8842 payment latency",
                "content": "Deployment 2.5 increased checkout p95 latency; rollback restored service.",
            },
            {
                "kind": "dependency",
                "title": "payments graph",
                "content": "payments depends on checkout, ledger, fraud, and postgres-primary.",
            },
        ]
    )

    async def fetch(self, alert: Alert, incident: Incident) -> dict[str, Any]:
        await asyncio.sleep(0)
        query_vector = self.embedding_model.embed(f"{alert.service} {alert.name} {alert.description}")
        ranked = sorted(
            self.documents,
            key=lambda doc: cosine_similarity(query_vector, self.embedding_model.embed(doc["content"])),
            reverse=True,
        )
        return {"matches": ranked[:3]}


@dataclass
class ContextIntelligenceAgent:
    connectors: list[BaseConnector] = field(
        default_factory=lambda: [
            ServiceNowConnector(),
            PrometheusConnector(),
            KubernetesConnector(),
            JenkinsConnector(),
            GitHubConnector(),
            CMDBConnector(),
            VectorDBConnector(),
        ]
    )

    async def collect(self, alert: Alert, incident: Incident) -> Context:
        results = await asyncio.gather(
            *[
                retry_async(lambda connector=connector: connector.fetch(alert, incident))
                for connector in self.connectors
            ]
        )
        by_name = {connector.name: result for connector, result in zip(self.connectors, results, strict=True)}
        vector_matches = by_name["vector-db"]["matches"]
        runbook = next((doc["content"] for doc in vector_matches if doc["kind"] == "runbook"), "")
        related = [doc for doc in vector_matches if doc["kind"] == "incident"]
        deployment = by_name["jenkins"].get("recent_deployments", [{}])[0].get("version") or alert.labels.get(
            "deployment"
        )
        dependencies = by_name["cmdb"].get("dependencies", [])
        recent_changes = by_name["servicenow"].get("change_records", []) + by_name["github"].get("recent_commits", [])
        return Context(
            incident_id=incident.id,
            alert=alert,
            deployment=deployment,
            related_incidents=related,
            runbook=runbook,
            dependency_services=dependencies,
            recent_changes=recent_changes,
            cmdb=by_name["cmdb"],
            kubernetes=by_name["kubernetes"],
            observability=by_name["prometheus"],
        )
