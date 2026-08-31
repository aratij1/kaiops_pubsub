from __future__ import annotations

from enum import StrEnum
from typing import Iterable


class OperationalRole(StrEnum):
    """The only roles that grant KaiOps operational capabilities."""

    ADMIN = "ADMIN"
    HITL_APPROVER = "HITL_APPROVER"


# Existing identities are migrated lazily so stored records and audit history do
# not need to be rewritten in-place. Read-only historical roles deliberately map
# to None to avoid granting new write or approval privileges.
LEGACY_OPERATIONAL_ROLE_MAP: dict[str, OperationalRole | None] = {
    "Administrator": OperationalRole.ADMIN,
    "admin": OperationalRole.ADMIN,
    "L3 Engineer": OperationalRole.HITL_APPROVER,
    "L2 Engineer": OperationalRole.HITL_APPROVER,
    "hitl-reviewer": OperationalRole.HITL_APPROVER,
    "HITL_REVIEWER": OperationalRole.HITL_APPROVER,
    "Executive": None,
    "L1 Operator": None,
}


def operational_role(role: str | None) -> OperationalRole | None:
    value = str(role or "").strip()
    try:
        return OperationalRole(value)
    except ValueError:
        return LEGACY_OPERATIONAL_ROLE_MAP.get(value)


def role_is_allowed(role: str | None, allowed_roles: Iterable[str | OperationalRole]) -> bool:
    actual = operational_role(role)
    if actual is None:
        return False
    return actual in {operational_role(str(candidate)) for candidate in allowed_roles}
