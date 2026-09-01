import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from context_agent import ContextIntelligenceAgent
from context_agent.connectors import VectorDBConnector


def load_context_app_module():
    module_path = Path("ai-workbench/src/context-agent/app.py")
    spec = importlib.util.spec_from_file_location("context_agent_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_knowledge_pack_extracts_required_operational_facts() -> None:
    module = load_context_app_module()
    request = module.KnowledgePackRequest(
        service="checkout-api",
        environment="prod",
        owner_team="platform-ops",
        documents=[
            module.KnowledgePackSourceDocument(
                name="checkout-runbook.md",
                category="knowledge_pack",
                text="""
                Alert: availability ratio below 99 for 5m.
                Dependency: mysql
                Dependency: rabbitmq
                Command: kubectl rollout restart deployment/checkout-api -n prod
                Rollback by running kubectl rollout undo deployment/checkout-api -n prod.
                Validate service health with curl http://checkout-api:8080/health.
                """,
            )
        ],
    )

    pack = module.build_knowledge_pack(request)

    assert pack["status"] == "ready"
    assert pack["facts"]["service"]["value"] == "checkout-api"
    assert pack["facts"]["environment"]["value"] == "prod"
    assert set(item.lower() for item in pack["facts"]["dependencies"]["value"]) >= {"mysql", "rabbitmq"}
    assert pack["facts"]["commands"]["value"]
    assert pack["facts"]["validation_checks"]["value"]
    assert pack["validation"]["overall_confidence"] >= 0.7


@pytest.mark.asyncio
async def test_knowledge_pack_approval_writes_rag_document(tmp_path) -> None:
    module = load_context_app_module()
    connector = VectorDBConnector(rag_root=tmp_path)
    module.agent = ContextIntelligenceAgent(connectors=[connector])
    request = module.KnowledgePackApproveRequest(
        service="checkout-api",
        environment="prod",
        owner_team="platform-ops",
        tenant_id="tenant-a",
        approved_by="administrator",
        approval_expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        documents=[
            module.KnowledgePackSourceDocument(
                name="checkout-triage.md",
                text="""
                Alert: checkout 5xx error rate above 5 percent for 10m.
                Dependency: mysql
                Command: kubectl rollout restart deployment/checkout-api -n prod
                Validate checkout recovery with curl http://checkout-api:8080/health.
                Rollback with kubectl rollout undo deployment/checkout-api -n prod.
                """,
            )
        ],
    )

    response = await module.approve_knowledge_pack(request)

    assert response["status"] == "approved"
    assert response["rag_document"]["document_count"] == 1
    assert Path(response["rag_document"]["path"]).exists()
    matches = connector.search("checkout 5xx mysql recovery", limit=3, tenant_id="tenant-a")
    assert matches[0]["title"] == "checkout-api Knowledge Pack"
    assert matches[0]["source_system"] == "knowledge-pack"
