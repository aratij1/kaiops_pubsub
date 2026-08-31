from __future__ import annotations

import hmac
import json
import os
from hashlib import sha256
from typing import Any


INVALID_TENANTS = frozenset({"", "default", "unknown", "none", "null"})


def require_tenant_id(value: Any, *, source: str) -> str:
    tenant_id = str(value or "").strip()
    environment = str(os.getenv("ENVIRONMENT") or "").strip().lower()
    auth_mode = str(os.getenv("AUTH_MODE") or "").strip().lower()
    profile = str(os.getenv("DEPLOYMENT_PROFILE") or "").strip().lower()
    local_runtime = environment in {"local", "demo", "test"} or (
        auth_mode == "local" and profile in {"local", "onprem", "cloud-neutral"}
    )
    if tenant_id.lower() == "default" and local_runtime:
        return tenant_id
    if tenant_id.lower() in INVALID_TENANTS:
        raise ValueError(f"verified tenant_id from verified identity is required from {source}")
    if len(tenant_id) > 128:
        raise ValueError("tenant_id exceeds 128 characters")
    return tenant_id


def _signature_payload(envelope: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in envelope.items() if key != "security"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()


def sign_event_envelope(envelope: dict[str, Any], *, key: str, issuer: str) -> dict[str, Any]:
    if not key:
        raise ValueError("event envelope signing key is required")
    normalized_issuer = str(issuer or "").strip()
    if not normalized_issuer:
        raise ValueError("event envelope issuer is required")
    signature = hmac.new(key.encode(), _signature_payload(envelope), sha256).hexdigest()
    return {
        **envelope,
        "security": {
            "algorithm": "hmac-sha256",
            "issuer": normalized_issuer,
            "signature": signature,
        },
    }


def verify_event_envelope(
    envelope: dict[str, Any],
    *,
    key: str,
    expected_issuer: str | None = None,
) -> str:
    security = envelope.get("security") if isinstance(envelope.get("security"), dict) else {}
    if security.get("algorithm") != "hmac-sha256" or not key:
        raise ValueError("event envelope signature is missing or unsupported")
    issuer = str(security.get("issuer") or "").strip()
    if expected_issuer and not hmac.compare_digest(issuer, expected_issuer):
        raise ValueError("event envelope issuer mismatch")
    expected = hmac.new(key.encode(), _signature_payload(envelope), sha256).hexdigest()
    supplied = str(security.get("signature") or "")
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise ValueError("event envelope signature is invalid")
    scope = envelope.get("scope") if isinstance(envelope.get("scope"), dict) else {}
    return require_tenant_id(scope.get("tenant_id"), source="signed event envelope")
