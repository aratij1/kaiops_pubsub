from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_application_layer_uses_ai_endpoints_instead_of_direct_ai_imports() -> None:
    application_files = [
        ROOT / "backend/src/monitoring-adapter/app.py",
        ROOT / "backend/src/common/common/orchestration/workflow_engine.py",
    ]
    forbidden_imports = [
        "from context_agent import",
        "import context_agent",
        "from resolution_agent import",
        "import resolution_agent",
        "from model_router import",
        "import model_router",
    ]

    for path in application_files:
        source = path.read_text(encoding="utf-8")
        for forbidden in forbidden_imports:
            assert forbidden not in source, f"{path} must use AiLayerClient endpoints, not {forbidden}"


def test_layered_compose_overlay_defines_application_and_ai_profiles() -> None:
    overlay = (ROOT / "docker-compose.layered.yml").read_text(encoding="utf-8")

    assert 'profiles: ["application-layer"]' in overlay
    assert 'profiles: ["ai-layer"]' in overlay
    assert "context-agent:" in overlay
    assert "resolution-agent:" in overlay
    assert "model-router:" in overlay
