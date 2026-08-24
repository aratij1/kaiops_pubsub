from datetime import UTC, datetime, timedelta

import pytest

from common.change_intelligence import ChangeCorrelationContext, ChangeEvent, correlate_change, rank_correlated_changes


NOW = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


def change(**updates):
    values = {
        "change_id": "change-1", "tenant_id": "tenant-a", "source": "deployment",
        "source_event_id": "deploy-41", "occurred_at": NOW - timedelta(minutes=5),
        "service": "checkout", "environment": "production",
        "resource_ids": ["k8s://cluster-a/prod/deployment/checkout"],
        "topology_resource_ids": ["dt://tenant-a/database/orders"],
        "change_reference": "deploy://checkout/v2.41", "evidence_ids": ["change:evidence:1"],
    }
    values.update(updates)
    return ChangeEvent.model_validate(values)


def context(**updates):
    values = {
        "tenant_id": "tenant-a", "incident_started_at": NOW, "service": "checkout",
        "environment": "production",
        "affected_resource_ids": ["k8s://cluster-a/prod/deployment/checkout"],
        "topology_resource_ids": ["dt://tenant-a/database/orders"],
    }
    values.update(updates)
    return ChangeCorrelationContext.model_validate(values)


def test_change_correlation_uses_time_and_operational_identity():
    result = correlate_change(change(), context())
    assert result.change_correlation_score > .8
    assert result.causal_proof is False
    assert "resource_identity_match" in result.reason_codes


def test_temporal_proximity_alone_is_not_causal_proof():
    result = correlate_change(
        change(service="unrelated", environment="staging", resource_ids=[], topology_resource_ids=[]),
        context(),
    )
    assert 0 < result.change_correlation_score <= .35
    assert result.reason_codes == ["change_within_incident_window"]
    assert result.causal_proof is False


def test_cross_tenant_change_is_rejected():
    with pytest.raises(ValueError, match="tenant"):
        correlate_change(change(tenant_id="tenant-b"), context())


def test_ranking_is_deterministic():
    ranked = rank_correlated_changes([
        change(change_id="old", source_event_id="old", occurred_at=NOW - timedelta(hours=3)),
        change(change_id="recent", source_event_id="recent"),
    ], context())
    assert [item.change_id for item in ranked] == ["recent", "old"]
