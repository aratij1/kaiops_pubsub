from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from common.config import Settings

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_FILENAME = "orchestration_config.json"

DEFAULT_ORCHESTRATION_CONFIG: dict[str, Any] = {
    "policy_version": "policy-v1",
    "approval_severities": ["high", "critical"],
    "confidence_guided_execute_threshold": 0.75,
    "confidence_auto_execute_threshold": 0.9,
    "default_correlation_threshold": 0.72,
    "risk_tiers_by_severity": {
        "critical": "high",
        "high": "high",
        "warning": "medium",
        "info": "low",
    },
    "message_bus": {
        "dynamic_routing": True,
        "default_provider": "rabbitmq",
        "stream_threshold": 500,
    },
    "workflow_definitions": {
        "critical-auto-remediation": {
            "steps": [
                "alert-intelligence-agent",
                "context-agent",
                "knowledge-agent",
                "rca-agent",
                "impact-agent",
                "approval-agent",
                "automation-agent",
                "validation-agent",
                "notification-agent",
                "closure-agent",
            ],
            "next_action": "collect-context",
        },
        "guided-remediation": {
            "steps": [
                "alert-intelligence-agent",
                "context-agent",
                "knowledge-agent",
                "rca-agent",
                "impact-agent",
                "approval-agent",
                "automation-agent",
                "validation-agent",
                "closure-agent",
            ],
            "next_action": "collect-context",
        },
        "triage-only": {
            "steps": [
                "alert-intelligence-agent",
                "context-agent",
                "knowledge-agent",
                "rca-agent",
                "notification-agent",
            ],
            "next_action": "collect-context",
        },
    },
}

_ALLOWED_BUS_PROVIDERS = {"kafka", "rabbitmq", "azure-service-bus", "servicebus", "azure"}


def _default_config_path() -> Path:
    return Path(__file__).with_name(_DEFAULT_CONFIG_FILENAME)


def _deep_copy_default() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_ORCHESTRATION_CONFIG))


def _normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = _deep_copy_default()

    if isinstance(config.get("policy_version"), str) and config["policy_version"].strip():
        normalized["policy_version"] = config["policy_version"].strip()

    approval_severities = config.get("approval_severities")
    if isinstance(approval_severities, list):
        values = {str(item).strip().lower() for item in approval_severities if str(item).strip()}
        if values:
            normalized["approval_severities"] = sorted(values)

    for key in (
        "confidence_guided_execute_threshold",
        "confidence_auto_execute_threshold",
        "default_correlation_threshold",
    ):
        try:
            normalized[key] = float(config.get(key, normalized[key]))
        except Exception:
            logger.warning("Invalid orchestration config numeric value for %s; using default", key)

    risk_map = config.get("risk_tiers_by_severity")
    if isinstance(risk_map, dict):
        cleaned_risk_map = {
            str(severity).strip().lower(): str(tier).strip().lower()
            for severity, tier in risk_map.items()
            if str(severity).strip() and str(tier).strip()
        }
        if cleaned_risk_map:
            normalized["risk_tiers_by_severity"] = {
                **normalized["risk_tiers_by_severity"],
                **cleaned_risk_map,
            }

    message_bus = config.get("message_bus")
    if isinstance(message_bus, dict):
        dynamic_routing = message_bus.get("dynamic_routing")
        if isinstance(dynamic_routing, bool):
            normalized["message_bus"]["dynamic_routing"] = dynamic_routing

        provider = str(message_bus.get("default_provider") or "").strip().lower()
        if provider in _ALLOWED_BUS_PROVIDERS:
            normalized["message_bus"]["default_provider"] = provider

        try:
            stream_threshold = int(message_bus.get("stream_threshold", normalized["message_bus"]["stream_threshold"]))
            normalized["message_bus"]["stream_threshold"] = max(0, stream_threshold)
        except Exception:
            logger.warning("Invalid message_bus.stream_threshold in orchestration config; using default")

    definitions = config.get("workflow_definitions")
    if isinstance(definitions, dict):
        cleaned_definitions: dict[str, dict[str, Any]] = {}
        for name, raw_definition in definitions.items():
            definition_name = str(name).strip()
            if not definition_name or not isinstance(raw_definition, dict):
                continue
            steps = raw_definition.get("steps")
            next_action = str(raw_definition.get("next_action") or "collect-context").strip() or "collect-context"
            if not isinstance(steps, list):
                continue
            cleaned_steps = [str(step).strip() for step in steps if str(step).strip()]
            if not cleaned_steps:
                continue
            cleaned_definitions[definition_name] = {
                "steps": cleaned_steps,
                "next_action": next_action,
            }
        if cleaned_definitions:
            normalized["workflow_definitions"] = cleaned_definitions

    return normalized


def load_orchestration_config(settings: Settings) -> dict[str, Any]:
    configured_path = str(getattr(settings, "orchestration_config_path", "") or "").strip()
    config_path = Path(configured_path) if configured_path else _default_config_path()

    raw: dict[str, Any] = {}
    try:
        if config_path.exists():
            parsed = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                raw = parsed
            else:
                logger.warning("Orchestration config at %s is not a JSON object; using defaults", config_path)
        else:
            logger.warning("Orchestration config file not found at %s; using defaults", config_path)
    except Exception as exc:
        logger.warning("Failed to read orchestration config from %s: %s", config_path, exc)

    normalized = _normalize_config(raw)

    # Preserve environment overrides only when explicitly set.
    explicit_fields = set(getattr(settings, "model_fields_set", set()))

    if "orchestration_approval_severities" in explicit_fields:
        approval_severities_raw = str(getattr(settings, "orchestration_approval_severities", "") or "")
        from_env = {item.strip().lower() for item in approval_severities_raw.split(",") if item.strip()}
        if from_env:
            normalized["approval_severities"] = sorted(from_env)

    if "confidence_guided_execute_threshold" in explicit_fields:
        normalized["confidence_guided_execute_threshold"] = float(
            getattr(settings, "confidence_guided_execute_threshold", normalized["confidence_guided_execute_threshold"])
        )
    if "confidence_auto_execute_threshold" in explicit_fields:
        normalized["confidence_auto_execute_threshold"] = float(
            getattr(settings, "confidence_auto_execute_threshold", normalized["confidence_auto_execute_threshold"])
        )
    if "alert_correlation_threshold" in explicit_fields:
        normalized["default_correlation_threshold"] = float(
            getattr(settings, "alert_correlation_threshold", normalized["default_correlation_threshold"])
        )

    message_bus = normalized["message_bus"]
    if "message_bus_dynamic_routing" in explicit_fields:
        message_bus["dynamic_routing"] = bool(getattr(settings, "message_bus_dynamic_routing", message_bus["dynamic_routing"]))
    if "message_bus_default_provider" in explicit_fields:
        provider = str(getattr(settings, "message_bus_default_provider", message_bus["default_provider"]) or "").strip().lower()
        message_bus["default_provider"] = provider if provider in _ALLOWED_BUS_PROVIDERS else "rabbitmq"
    if "message_bus_stream_threshold" in explicit_fields:
        message_bus["stream_threshold"] = max(
            0,
            int(getattr(settings, "message_bus_stream_threshold", message_bus["stream_threshold"]) or 0),
        )

    return normalized