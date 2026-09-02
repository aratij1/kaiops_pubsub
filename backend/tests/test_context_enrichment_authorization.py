from common.context_enrichment_contract import (
    authorized_enrichment_connectors,
    next_authorized_enrichment_connector,
)


def test_completed_canonical_context_connector_is_authorized_for_enrichment() -> None:
    authorized = authorized_enrichment_connectors(
        alert_metadata={"resolved_context_connectors": []},
        context_payload={
            "metadata": {
                "context_graph": {
                    "connectors": {
                        "discovery-mcp": {"status": "completed"},
                        "jaeger": {"status": "unavailable"},
                    }
                }
            }
        },
    )

    assert "discovery-mcp" in authorized
    assert "jaeger" not in authorized


def test_alert_resolved_connector_remains_authorized() -> None:
    authorized = authorized_enrichment_connectors(
        alert_metadata={"resolved_context_connectors": [{"provider": "jaeger"}]},
        context_payload={},
    )

    assert {"jaeger", "discovery-mcp", "local-evidence", "vector-db"} <= authorized


def test_internal_discovery_is_available_for_targeted_trace_enrichment() -> None:
    authorized = authorized_enrichment_connectors(
        alert_metadata={},
        context_payload={},
    )

    assert "discovery-mcp" in authorized


def test_enrichment_falls_through_to_next_authorized_unattempted_connector() -> None:
    connector = next_authorized_enrichment_connector(
        candidate_connectors=["jaeger", "discovery-mcp", "local-evidence"],
        authorized_connectors={"jaeger", "discovery-mcp", "local-evidence"},
        attempted_connectors={"jaeger", "discovery-mcp"},
    )

    assert connector == "local-evidence"


def test_enrichment_stops_after_all_authorized_connectors_are_attempted() -> None:
    connector = next_authorized_enrichment_connector(
        candidate_connectors=["jaeger", "discovery-mcp"],
        authorized_connectors={"discovery-mcp"},
        attempted_connectors={"discovery-mcp"},
    )

    assert connector is None
