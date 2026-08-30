import importlib.util
from pathlib import Path
from types import SimpleNamespace
from datetime import UTC, datetime

import pytest

from common.config import Settings
from ai_workbench_common.embeddings import HashingEmbeddingModel
from context_agent import ContextIntelligenceAgent
from context_agent.connectors import AzureAISearchVectorStore, VectorDBConnector


def load_context_app_module():
    module_path = Path("ai-workbench/src/context-agent/app.py")
    spec = importlib.util.spec_from_file_location("context_agent_app", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rag_ingestion_writes_reloads_and_searches(tmp_path) -> None:
    module = load_context_app_module()
    connector = VectorDBConnector(rag_root=tmp_path)
    module.agent = ContextIntelligenceAgent(connectors=[connector])
    request = module.RagDocumentRequest(
        kind="runbook",
        title="Payments cache warmup",
        services=["payments", "cache"],
        dependencies=["redis"],
        content="Use this runbook when payments cache warmup fails after deployment.",
        tenant_scope="tenant-a",
        owner_team="payments-ops",
        source_system="governed-test-fixture",
        source_ref="test://payments-cache-warmup",
        review_status="approved",
        corpus_classification="TENANT_CURATED",
        reviewed_by="test-reviewer",
        approved_by="test-approver",
        approved_at=datetime.now(UTC).isoformat(),
        last_reviewed=datetime.now(UTC).isoformat(),
    )

    result = module.write_rag_document(request)

    assert result["document_count"] == 1
    assert result["index"]["vector_store"]["provider"] == "local-hybrid-vector-index"
    assert result["index"]["embedding_model"]["model"] == "hashing-token-counter-v1"
    assert result["index"]["metadata_embedding_count"] == 1
    assert Path(result["path"]).exists()
    matches = connector.search("payments cache warmup", limit=3, tenant_id="tenant-a")
    assert matches[0]["title"] == "Payments cache warmup"
    assert matches[0]["kind"] == "runbook"

    public_doc = module._public_rag_document(connector.documents[0], connector)
    assert public_doc["embedding_status"] in {"embedded", "metadata-only"}
    assert public_doc["vector_store"]["provider"] == "local-hybrid-vector-index"


@pytest.mark.asyncio
async def test_general_ingestion_requires_separate_approval_before_retrieval(tmp_path) -> None:
    module = load_context_app_module()
    connector = VectorDBConnector(rag_root=tmp_path)
    module.agent = ContextIntelligenceAgent(connectors=[connector])
    request = module.RagDocumentRequest(
        kind="runbook",
        title="Checkout diagnostics",
        services=["checkout"],
        content="Collect checkout logs and latency telemetry before selecting remediation.",
        tenant_scope="tenant-a",
        owner_team="client-supplied-value",
        source_system="runbook-registry",
        source_ref="runbook://checkout/draft",
        review_status="approved",
        corpus_classification="TENANT_CURATED",
        approved_by="forged-client-identity",
    )

    pending = await module.ingest_rag_document(request)

    assert pending["status"] == "pending_review"
    assert not list(tmp_path.rglob("*.md"))
    assert connector.search("checkout diagnostics", tenant_id="tenant-a") == []

    approved = await module.approve_rag_document(
        pending["draft"]["draft_id"],
        module.RagDocumentApproveRequest(
            tenant_scope="tenant-a",
            approved_by="server-derived-admin",
            owner_team="checkout-ops",
        ),
    )

    assert approved["status"] == "approved"
    matches = connector.search("checkout diagnostics", tenant_id="tenant-a")
    assert matches[0]["approved_by"] == "server-derived-admin"
    assert matches[0]["owner_team"] == "checkout-ops"


@pytest.mark.asyncio
async def test_evidence_draft_requires_review_approval_before_grounding(tmp_path) -> None:
    module = load_context_app_module()
    connector = VectorDBConnector(rag_root=tmp_path)
    module.agent = ContextIntelligenceAgent(connectors=[connector])
    alert = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        name="Checkout error rate",
        service="checkout-api",
        environment="production",
        severity=SimpleNamespace(value="high"),
        tenant_id="tenant-a",
        labels={},
    )
    incident = SimpleNamespace(id="22222222-2222-2222-2222-222222222222")
    context = SimpleNamespace(
        metadata={
            "discovery_report": {
                "report": {
                    "summary": "Error rate increased after the latest deployment.",
                    "hypotheses": [{"cause": "Bad checkout deployment", "confidence": 0.82}],
                },
                "evidence": [
                    {
                        "evidence_id": "LOG-123",
                        "source": "logs",
                        "snippet": "checkout returned HTTP 500",
                        "uri": "logs://checkout/123",
                    }
                ],
            }
        }
    )

    draft = module.create_evidence_rag_draft(alert=alert, incident=incident, context=context)

    assert draft["status"] == "draft"
    stored_drafts = module._list_evidence_rag_drafts_sync(None, None, "tenant-a")
    assert {item["document_kind"] for item in stored_drafts} == {
        "incident", "jira", "runbook", "deployment", "change", "dependency", "remediation"
    }
    assert len({item["draft_id"] for item in stored_drafts}) == 7
    assert not list(tmp_path.rglob("*.md"))
    assert connector.search("checkout returned HTTP 500", limit=3, tenant_id="tenant-a") == []

    reviewed = await module.review_evidence_rag_draft(
        draft["draft_id"],
        module.EvidenceRagDraftReviewRequest(
            tenant_scope="tenant-a",
            reviewed_by="Operations Reviewer",
            content=draft["content"] + "\n\nReviewed against the incident timeline.",
        ),
    )
    assert reviewed["draft"]["status"] == "reviewed"
    assert not list(tmp_path.rglob("*.md"))

    approved = await module.approve_evidence_rag_draft(
        draft["draft_id"],
        module.EvidenceRagDraftApproveRequest(
            tenant_scope="tenant-a",
            approved_by="Operations Approver",
            owner_team="checkout-ops",
        ),
    )
    assert approved["draft"]["status"] == "approved"
    assert list(tmp_path.rglob("*.md"))
    assert connector.search("checkout returned HTTP 500", limit=3, tenant_id="tenant-a")[0]["kind"] == "incident"


@pytest.mark.asyncio
async def test_approved_remediation_is_reused_as_historical_knowledge_for_future_incident(tmp_path) -> None:
    module = load_context_app_module()
    connector = VectorDBConnector(rag_root=tmp_path)
    module.agent = ContextIntelligenceAgent(connectors=[connector])
    alert = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        name="MySQL table rows high",
        service="mysql",
        environment="production",
        severity=SimpleNamespace(value="high"),
        tenant_id="tenant-a",
        labels={},
    )
    incident = SimpleNamespace(id="22222222-2222-2222-2222-222222222222", tenant_id="tenant-a")
    context = SimpleNamespace(metadata={"discovery_report": {"report": {
        "summary": "Rows increased after an unbounded retention job.",
        "hypotheses": [{"cause": "Retention job did not purge old rows", "confidence": 0.7}],
    }, "evidence": [{
        "evidence_id": "DB-123", "source": "database",
        "snippet": "events table row count exceeded the reviewed threshold",
        "uri": "database://mysql/events/rows",
    }]}})
    module.create_evidence_rag_draft(alert=alert, incident=incident, context=context)
    remediation = next(
        item for item in module._list_evidence_rag_drafts_sync(None, None, "tenant-a")
        if item["document_kind"] == "remediation"
    )
    reviewed_content = (
        remediation["content"]
        + "\n\nVerified action: inspect retention policy before any governed change."
    )
    await module.review_evidence_rag_draft(
        remediation["draft_id"],
        module.EvidenceRagDraftReviewRequest(
            tenant_scope="tenant-a", reviewed_by="Operations Reviewer", content=reviewed_content,
        ),
    )
    await module.approve_evidence_rag_draft(
        remediation["draft_id"],
        module.EvidenceRagDraftApproveRequest(
            tenant_scope="tenant-a", approved_by="Operations Approver", owner_team="database-ops",
        ),
    )

    future_alert = SimpleNamespace(
        id="33333333-3333-3333-3333-333333333333",
        name="MySQL table rows high",
        description="events table row count exceeded the reviewed threshold",
        service="mysql",
        tenant_id="tenant-a",
        labels={}, annotations={},
    )
    future_incident = SimpleNamespace(
        id="44444444-4444-4444-4444-444444444444", tenant_id="tenant-a"
    )

    result = await connector.fetch(future_alert, future_incident)

    assert result["matches"]
    assert result["matches"][0]["kind"] == "remediation"
    assert result["matches"][0]["review_status"] == "approved"


def test_evidence_draft_rejects_unrelated_cross_project_evidence(tmp_path) -> None:
    module = load_context_app_module()
    alert = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        name="UptimeRobot monitor down",
        service="uptimerobot",
        environment="production",
        severity=SimpleNamespace(value="critical"),
        labels={"application": "UptimeRobot", "monitor_id": "monitor-42"},
        tenant_id="tenant-a",
    )
    incident = SimpleNamespace(id="22222222-2222-2222-2222-222222222222")
    context = SimpleNamespace(metadata={"discovery_report": {
        "report": {"summary": "Unrelated service failed."},
        "evidence": [{
            "evidence_id": "MYSQL-123",
            "source": "mysql",
            "snippet": "kaiops remediation engine is unavailable",
            "uri": "mysql://kaiops/incidents/123",
        }],
    }})

    assert module.create_evidence_rag_draft(alert=alert, incident=incident, context=context) is None


def test_empty_corpus_is_degraded_and_blocks_execution_readiness(tmp_path) -> None:
    connector = VectorDBConnector(rag_root=tmp_path)
    connector.reload()

    index = connector.index_info()

    assert index["status"] == "degraded_empty_corpus"
    assert index["execution_ready"] is False
    assert index["approved_retrievable_count"] == 0


def test_azure_ai_search_vector_store_builds_hybrid_search_request(monkeypatch) -> None:
    captured = {}
    store = AzureAISearchVectorStore(
        settings=Settings(
            AZURE_AI_SEARCH_ENABLED=True,
            AZURE_AI_SEARCH_ENDPOINT="https://search.example.net",
            AZURE_AI_SEARCH_API_KEY="key",
            AZURE_AI_SEARCH_INDEX_NAME="kaiops-rag",
        ),
        embedding_model=HashingEmbeddingModel(),
    )

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "value": [
                    {
                        "@search.score": 0.91,
                        "kind": "runbook",
                        "title": "Payments triage",
                        "content": "Investigate payments latency",
                        "services": ["payments"],
                        "tenant_scope": "tenant-a",
                        "review_status": "approved",
                        "corpus_classification": "TENANT_CURATED",
                        "owner_team": "payments-ops",
                        "source_system": "test",
                        "source_ref": "test://payments",
                        "content_version": 1,
                        "created_at": "2026-08-27T00:00:00Z",
                        "updated_at": "2026-08-27T00:00:00Z",
                        "last_reviewed": "2026-08-27T00:00:00Z",
                        "reviewed_by": "reviewer",
                        "approved_by": "approver",
                        "approved_at": "2026-08-27T00:00:00Z",
                        "content_checksum": "sha256:" + "0" * 64,
                    }
                ]
            }

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse()

    import context_agent.connectors as connectors_module

    monkeypatch.setattr(connectors_module.httpx, "Client", _FakeClient)

    matches = store.search(
        query="payments latency",
        query_vector=[0.1, 0.2, 0.3],
        limit=3,
        preferred_kinds={"runbook"},
        service="payments",
        tenant_id="tenant-a",
    )

    assert matches[0]["title"] == "Payments triage"
    assert matches[0]["_vector_store"] == "azure-ai-search"
    assert "/indexes/kaiops-rag/docs/search" in captured["url"]
    assert captured["json"]["vectorQueries"][0]["fields"] == "content_vector"
    assert "kind eq 'runbook'" in captured["json"]["filter"]
    assert "services/any" in captured["json"]["filter"]
    assert "tenant_scope eq 'tenant-a'" in captured["json"]["filter"]
    assert "corpus_classification eq 'TENANT_CURATED'" in captured["json"]["filter"]
    assert "tenant_scope eq 'global'" in captured["json"]["filter"]
    assert "corpus_classification eq 'PRODUCTION_CURATED'" in captured["json"]["filter"]
    assert "review_status eq 'approved'" in captured["json"]["filter"]


def test_azure_ai_search_vector_store_chunks_and_uploads(monkeypatch) -> None:
    captured = {}
    store = AzureAISearchVectorStore(
        settings=Settings(
            AZURE_AI_SEARCH_ENABLED=True,
            AZURE_AI_SEARCH_ENDPOINT="https://search.example.net",
            AZURE_AI_SEARCH_API_KEY="key",
            AZURE_AI_SEARCH_INDEX_NAME="kaiops-rag",
        ),
        embedding_model=HashingEmbeddingModel(),
    )

    class _FakeResponse:
        def raise_for_status(self):
            return None

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    import context_agent.connectors as connectors_module

    monkeypatch.setattr(connectors_module.httpx, "Client", _FakeClient)

    result = store.upsert_documents(
        [
            {
                "path": "/tmp/rag/runbooks/payments.md",
                "kind": "runbook",
                "title": "Payments runbook",
                "services": ["payments"],
                "content": "A" * 2200,
            }
        ]
    )

    assert result["indexed"] >= 2
    assert "/indexes/kaiops-rag/docs/index" in captured["url"]
    assert captured["json"]["value"][0]["@search.action"] == "mergeOrUpload"
    assert captured["json"]["value"][0]["content_vector"]


def test_azure_ai_search_removes_all_chunks_for_quarantined_document(monkeypatch) -> None:
    requests = []
    store = AzureAISearchVectorStore(
        settings=Settings(
            AZURE_AI_SEARCH_ENABLED=True,
            AZURE_AI_SEARCH_ENDPOINT="https://search.example.net",
            AZURE_AI_SEARCH_API_KEY="key",
            AZURE_AI_SEARCH_INDEX_NAME="kaiops-rag",
        ),
        embedding_model=HashingEmbeddingModel(),
    )

    class _FakeResponse:
        def __init__(self, payload=None):
            self._payload = payload or {}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            requests.append((url, json))
            if "/docs/search" in url:
                return _FakeResponse({"value": [
                    {"id": "runbook-chunk-1", "document_id": "/rag/runbook.md"},
                    {"id": "runbook-chunk-2", "document_id": "/rag/runbook.md"},
                ]})
            return _FakeResponse()

    import context_agent.connectors as connectors_module

    monkeypatch.setattr(connectors_module.httpx, "Client", _FakeClient)

    result = store.delete_document("/rag/runbook.md")

    assert result["deleted"] == 2
    assert requests[1][1]["value"] == [
        {"@search.action": "delete", "id": "runbook-chunk-1"},
        {"@search.action": "delete", "id": "runbook-chunk-2"},
    ]
