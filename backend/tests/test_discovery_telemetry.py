import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src" / "discovery-mcp" / "app.py"
SPEC = importlib.util.spec_from_file_location("discovery_mcp_telemetry_app", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_telemetry_project_routes_code_search_to_astronomy_shop(monkeypatch):
    project_root = Path("/workspace/external/telemetry/opentelemetry-demo")
    monkeypatch.setattr(
        MODULE,
        "_project_catalog",
        lambda: {
            "telemetry": {
                "name": "telemetry",
                "aliases": ["astronomy-shop"],
                "code_roots": [str(project_root)],
            }
        },
    )

    roots = MODULE._code_roots({"project": "telemetry", "terms": ["payment"]})

    assert roots == [project_root]


def test_telemetry_tool_is_published():
    names = {tool["name"] for tool in MODULE.TOOLS}
    assert "telemetry.search" in names
