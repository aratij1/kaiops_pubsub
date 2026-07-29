import importlib.util
from pathlib import Path
from types import SimpleNamespace

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
    )

    result = module.write_rag_document(request)

    assert result["document_count"] == 1
    assert result["index"]["vector_store"]["provider"] == "file-backed-memory"
    assert result["index"]["embedding_model"]["model"] == "hashing-token-counter-v1"
    assert result["index"]["metadata_embedding_count"] == 1
    assert Path(result["path"]).exists()
    matches = connector.search("payments cache warmup", limit=3)
    assert matches[0]["title"] == "Payments cache warmup"
    assert matches[0]["kind"] == "runbook"

    public_doc = module._public_rag_document(connector.documents[0], connector)
    assert public_doc["embedding_status"] in {"embedded", "metadata-only"}
    assert public_doc["vector_store"]["provider"] == "file-backed-memory"


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
    assert not list(tmp_path.rglob("*.md"))
    assert connector.search("checkout returned HTTP 500", limit=3) == []

    reviewed = await module.review_evidence_rag_draft(
        draft["draft_id"],
        module.EvidenceRagDraftReviewRequest(
            reviewed_by="Operations Reviewer",
            content=draft["content"] + "\n\nReviewed against the incident timeline.",
        ),
    )
    assert reviewed["draft"]["status"] == "reviewed"
    assert not list(tmp_path.rglob("*.md"))

    approved = await module.approve_evidence_rag_draft(
        draft["draft_id"],
        module.EvidenceRagDraftApproveRequest(approved_by="Operations Approver"),
    )
    assert approved["draft"]["status"] == "approved"
    assert list(tmp_path.rglob("*.md"))
    assert connector.search("checkout returned HTTP 500", limit=3)[0]["kind"] == "incident"


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
    )

    assert matches[0]["title"] == "Payments triage"
    assert matches[0]["_vector_store"] == "azure-ai-search"
    assert "/indexes/kaiops-rag/docs/search" in captured["url"]
    assert captured["json"]["vectorQueries"][0]["fields"] == "content_vector"
    assert "kind eq 'runbook'" in captured["json"]["filter"]
    assert "services/any" in captured["json"]["filter"]


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
