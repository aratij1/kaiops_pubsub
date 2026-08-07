from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "ai-workbench"
    / "src"
    / "context-agent"
    / "context_agent"
    / "knowledge_graph.py"
)
SPEC = importlib.util.spec_from_file_location("kaiops_knowledge_graph", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
KnowledgeGraph = MODULE.KnowledgeGraph


def test_graph_builds_service_dependency_and_document_context() -> None:
    graph = KnowledgeGraph.from_documents(
        [
            {
                "path": "runbooks/checkout.md",
                "kind": "runbook",
                "title": "Checkout recovery",
                "services": ["checkout"],
                "dependencies": ["payments", "redis"],
                "deployment": "checkout-v42",
            },
            {
                "path": "incidents/inc-42.md",
                "kind": "incident",
                "title": "Checkout latency",
                "services": ["checkout"],
                "incident_id": "INC-42",
            },
        ]
    )

    context = graph.context("checkout", depth=2)

    assert set(context["dependencies"]) == {"payments", "redis"}
    assert {row["label"] for row in context["documents"]} == {"Checkout recovery", "Checkout latency"}
    assert {row["relation"] for row in context["edges"]} >= {"DEPENDS_ON", "HAS_KNOWLEDGE", "DEPLOYED_AS", "AFFECTED_BY"}
    assert graph.summary()["node_count"] == 7


def test_unknown_service_returns_empty_context() -> None:
    context = KnowledgeGraph.from_documents([]).context("missing")
    assert context["nodes"] == []
    assert context["edges"] == []
