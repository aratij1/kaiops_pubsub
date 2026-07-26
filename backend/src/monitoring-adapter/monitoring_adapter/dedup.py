from __future__ import annotations

import hashlib
from typing import Any


def compute_fingerprint(mapped_payload: dict[str, Any]) -> str:
    """One canonical fingerprint function shared by every ingestion path
    that routes through the centralized Jira dedup step (Prometheus, logs,
    email) — the actual "centralized" part of "Monitoring Adapter performs
    centralized deduplication".

    Prefers a real upstream fingerprint when one exists (Alertmanager
    already computes `alert_fingerprint` per firing series — reusing it
    keeps this consistent with the fingerprint already used for landing-pad
    dedup elsewhere in this file). Falls back to a stable hash of
    name+service+environment for sources with no native fingerprint (log
    lines, emails).
    """
    labels = mapped_payload.get("labels", {}) if isinstance(mapped_payload.get("labels"), dict) else {}
    existing = str(labels.get("alert_fingerprint") or "").strip()
    if existing:
        return existing
    error_signature = str(labels.get("error_signature") or "").strip()
    if error_signature:
        service = str(mapped_payload.get("service") or "").strip().lower()
        environment = str(mapped_payload.get("environment") or "prod").strip().lower()
        seed = f"{error_signature.lower()}|{service}|{environment}"
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]

    name = str(mapped_payload.get("name") or "").strip().lower()
    service = str(mapped_payload.get("service") or "").strip().lower()
    environment = str(mapped_payload.get("environment") or "prod").strip().lower()
    seed = f"{name}|{service}|{environment}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
