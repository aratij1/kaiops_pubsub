from __future__ import annotations

import json

from ai_workbench_common.model_gateway import HttpModelGateway


def test_resolution_model_payload_is_compacted_without_losing_identity() -> None:
    gateway = HttpModelGateway("http://model-router", max_payload_bytes=8_000)
    payload = {
        "service": "payments-api",
        "environment": "prod",
        "root_cause": "connection pool exhaustion",
        "raw_payload": "secret/noisy" * 2_000,
        "discovery_evidence": [
            {"evidence_id": f"ev-{index}", "snippet": "x" * 5_000}
            for index in range(50)
        ],
    }

    compacted, budget = gateway._compact_payload(payload)

    assert compacted["service"] == "payments-api"
    assert compacted["environment"] == "prod"
    assert compacted["root_cause"] == "connection pool exhaustion"
    assert "raw_payload" not in compacted
    assert budget["trimmed"] is True
    assert budget["sent_bytes"] <= budget["budget_bytes"]
    assert len(json.dumps(compacted).encode("utf-8")) <= 8_000


def test_small_resolution_payload_is_not_marked_trimmed() -> None:
    gateway = HttpModelGateway("http://model-router", max_payload_bytes=8_000)
    payload = {"service": "inventory", "evidence": [{"evidence_id": "ev-1", "snippet": "healthy"}]}

    compacted, budget = gateway._compact_payload(payload)

    assert compacted == payload
    assert budget["trimmed"] is False
