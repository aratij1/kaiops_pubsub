from __future__ import annotations

import re
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


_PLACEHOLDER = re.compile(r"\$\{[^}]+\}|<[^>]+>|\{\{[^}]+\}\}")


class RunbookVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runbook_id: UUID
    version: int = Field(ge=1)
    status: Literal["draft", "testing", "approved", "deprecated", "disabled"]
    owner: str = Field(min_length=1)
    service: str = Field(min_length=1)
    alert_family: str = Field(min_length=1)
    risk: Literal["low", "medium", "high", "critical"]
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    preflight: list[str] = Field(default_factory=list)
    action: list[str] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    rollback: list[str] = Field(default_factory=list)
    canary_supported: bool = False
    timeout_seconds: int = Field(default=300, ge=1, le=3600)
    max_attempts: int = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def approved_versions_are_safe(self) -> "RunbookVersion":
        if self.status == "approved" and self.action and (not self.validation or not self.rollback):
            raise ValueError("approved mutating runbooks require validation and rollback")
        return self


def validate_runbook_parameters(schema: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    unknown = sorted(set(parameters) - set(properties)) if properties else []
    missing = sorted(str(name) for name in required if name not in parameters)
    if unknown:
        raise ValueError(f"unknown runbook parameters: {', '.join(unknown)}")
    if missing:
        raise ValueError(f"missing runbook parameters: {', '.join(missing)}")
    for name, value in parameters.items():
        if _PLACEHOLDER.search(str(value)):
            raise ValueError(f"unresolved placeholder in runbook parameter: {name}")
        definition = properties.get(name, {}) if isinstance(properties.get(name), dict) else {}
        expected = definition.get("type")
        if expected == "string" and not isinstance(value, str):
            raise ValueError(f"runbook parameter {name} must be a string")
        if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(f"runbook parameter {name} must be an integer")
        if expected == "boolean" and not isinstance(value, bool):
            raise ValueError(f"runbook parameter {name} must be a boolean")
        if isinstance(definition.get("enum"), list) and value not in definition["enum"]:
            raise ValueError(f"runbook parameter {name} is not an allowed value")
    return dict(parameters)


def contains_unresolved_placeholders(commands: list[str]) -> bool:
    return any(_PLACEHOLDER.search(str(command)) for command in commands)
