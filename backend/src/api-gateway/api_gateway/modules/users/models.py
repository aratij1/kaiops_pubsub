from __future__ import annotations

from enum import StrEnum

from common.authorization import OperationalRole


class SystemRole(StrEnum):
    ADMINISTRATOR = "Administrator"
    EXECUTIVE = "Executive"
    L3_ENGINEER = "L3 Engineer"
    L2_ENGINEER = "L2 Engineer"
    L1_OPERATOR = "L1 Operator"


SYSTEM_ROLES: tuple[str, ...] = tuple(role.value for role in SystemRole)

# New assignments must use these roles. SystemRole remains for non-destructive
# reads and migration of existing database records.
CORE_SYSTEM_ROLES: tuple[str, ...] = tuple(role.value for role in OperationalRole)
