import importlib.util
from pathlib import Path

from context_agent import ContextIntelligenceAgent
from context_agent.connectors import VectorDBConnector


def load_context_app_module():
    module_path = Path("services/context-agent/app.py")
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
    assert Path(result["path"]).exists()
    matches = connector.search("payments cache warmup", limit=3)
    assert matches[0]["title"] == "Payments cache warmup"
    assert matches[0]["kind"] == "runbook"
