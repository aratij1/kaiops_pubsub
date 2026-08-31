from __future__ import annotations

import re
from typing import Any


_EPHEMERAL_ENVIRONMENT = re.compile(r"^(e2e|smoke(?:-test)?|ux(?:-test)?|test)(?:[-_].*)?$", re.I)


def environment_family(value: Any) -> str:
    """Return the operational environment, excluding per-run test suffixes."""
    normalized = str(value or "unknown").strip().lower().replace("_", "-") or "unknown"
    aliases = {"production": "prod", "development": "dev", "staging": "stage"}
    normalized = aliases.get(normalized, normalized)
    match = _EPHEMERAL_ENVIRONMENT.match(normalized)
    if not match:
        return normalized
    prefix = match.group(1).lower()
    if prefix.startswith("smoke"):
        return "smoke-test"
    if prefix.startswith("ux"):
        return "ux-test"
    return prefix


def is_ephemeral_environment(value: Any) -> bool:
    normalized = str(value or "").strip().lower().replace("_", "-")
    return bool(_EPHEMERAL_ENVIRONMENT.match(normalized))


def same_environment_family(left: Any, right: Any) -> bool:
    return environment_family(left) == environment_family(right)
