from __future__ import annotations

import pytest

from common.tenant_identity import require_tenant_id, sign_event_envelope, verify_event_envelope


def _envelope() -> dict:
    return {
        "event_id": "event-1",
        "event_type": "incident.approval.decided",
        "incident_id": "incident-1",
        "scope": {"tenant_id": "tenant-a"},
        "payload": {"plan_fingerprint": "sha256:" + "a" * 64},
    }


@pytest.mark.parametrize("value", [None, "", "default", "unknown", "null"])
def test_placeholder_tenant_is_rejected(value: str | None) -> None:
    with pytest.raises(ValueError, match="verified tenant_id"):
        require_tenant_id(value, source="test identity")


def test_default_tenant_is_allowed_only_in_explicit_local_environment(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "local")
    assert require_tenant_id("default", source="local stack") == "default"
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="verified tenant_id"):
        require_tenant_id("default", source="production stack")


def test_default_tenant_is_allowed_for_local_auth_nonproduction_profile(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("AUTH_MODE", "local")
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "cloud-neutral")
    assert require_tenant_id("default", source="local compose stack") == "default"


def test_signed_event_returns_verified_tenant() -> None:
    signed = sign_event_envelope(_envelope(), key="k" * 32, issuer="approval-service")

    assert verify_event_envelope(
        signed,
        key="k" * 32,
        expected_issuer="approval-service",
    ) == "tenant-a"


def test_tampered_event_is_rejected() -> None:
    signed = sign_event_envelope(_envelope(), key="k" * 32, issuer="approval-service")
    signed["scope"]["tenant_id"] = "tenant-b"

    with pytest.raises(ValueError, match="signature is invalid"):
        verify_event_envelope(signed, key="k" * 32, expected_issuer="approval-service")


def test_wrong_service_issuer_is_rejected() -> None:
    signed = sign_event_envelope(_envelope(), key="k" * 32, issuer="resolution-agent")

    with pytest.raises(ValueError, match="issuer mismatch"):
        verify_event_envelope(signed, key="k" * 32, expected_issuer="approval-service")
