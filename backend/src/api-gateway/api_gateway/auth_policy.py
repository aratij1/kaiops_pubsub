from __future__ import annotations

from api_gateway.modules.users.models import SystemRole
from common.authorization import OperationalRole

ADMIN_ROLE = SystemRole.ADMINISTRATOR.value
L3_AND_ADMIN_ROLES = {
    SystemRole.ADMINISTRATOR.value,
    SystemRole.L3_ENGINEER.value,
}
HITL_COMPATIBILITY_ROLES = {
    ADMIN_ROLE,
    SystemRole.L2_ENGINEER.value,
    SystemRole.L3_ENGINEER.value,
}
DOCUMENT_PROVIDER_ROLES = {
    SystemRole.ADMINISTRATOR.value,
    SystemRole.L2_ENGINEER.value,
    SystemRole.L3_ENGINEER.value,
}
AUTHENTICATED_WRITE_RULES: tuple[tuple[set[str] | None, str, set[str] | None], ...] = (
    (None, "/evaluations", None),
    ({"GET"}, "/events/operations", None),
    (None, "/applications", {ADMIN_ROLE}),
    (None, "/onboarding", {ADMIN_ROLE}),
    (None, "/monitoring", {ADMIN_ROLE}),
    ({"GET"}, "/operations/queue-health", DOCUMENT_PROVIDER_ROLES),
    (None, "/operations/queues", {ADMIN_ROLE}),
    (None, "/knowledge-development/configuration", {ADMIN_ROLE}),
    ({"POST"}, "/knowledge-development/run", L3_AND_ADMIN_ROLES),
    ({"GET"}, "/knowledge-development", DOCUMENT_PROVIDER_ROLES),
    (None, "/knowledge-development", DOCUMENT_PROVIDER_ROLES),
    ({"POST", "PUT", "DELETE", "PATCH"}, "/rag", DOCUMENT_PROVIDER_ROLES),
    ({"POST", "PUT", "DELETE", "PATCH"}, "/model", {ADMIN_ROLE}),
    ({"GET"}, "/model/providers/status", DOCUMENT_PROVIDER_ROLES),
    ({"GET"}, "/model", DOCUMENT_PROVIDER_ROLES),
    (None, "/approval/capacity", {ADMIN_ROLE}),
    (None, "/approval/assignments", {ADMIN_ROLE}),
    (None, "/approval/auto-assign", {ADMIN_ROLE}),
    ({"GET"}, "/approval/incident", None),
    ({"POST"}, "/incidents", {ADMIN_ROLE, SystemRole.L3_ENGINEER.value}),
    ({"POST"}, "/analysis", None),
    ({"POST", "PUT", "DELETE", "PATCH"}, "/approval", HITL_COMPATIBILITY_ROLES),
    ({"POST", "PUT", "DELETE", "PATCH"}, "/remediation", HITL_COMPATIBILITY_ROLES),
    ({"POST"}, "/copilot", None),
    # Any authenticated role -- incident/closure data is read broadly across
    # the Overview, Live Stream, Alerts & Incidents, and Dashboard views by
    # every operator role (including L1), not just governance-facing roles.
    ({"GET"}, "/incidents", None),
    # Administrator/L2/L3 only -- gateway trace and safety-decision data
    # backs Agent Flow and Gateway Safety, which are engineering-role-only
    # in the UI navigation (see frontend ENGINEERING_ROLES).
    ({"GET"}, "/observability", DOCUMENT_PROVIDER_ROLES),
)


def route_auth_rule(method: str, path: str) -> set[str] | None | bool:
    normalized_method = method.upper()
    normalized_path = path.rstrip("/") or "/"
    for methods, prefix, roles in AUTHENTICATED_WRITE_RULES:
        if methods is not None and normalized_method not in methods:
            continue
        if normalized_path == prefix or normalized_path.startswith(f"{prefix}/"):
            return roles
    return False


def canonical_route_auth_rule(method: str, path: str) -> set[str] | None | bool:
    """Return the two-role policy used for live authorization.

    ``route_auth_rule`` remains the legacy projection for compatibility with
    older policy consumers during the migration window.
    """
    rule = route_auth_rule(method, path)
    if rule is False or rule is None:
        return rule
    canonical: set[str] = set()
    if SystemRole.ADMINISTRATOR.value in rule:
        canonical.add(OperationalRole.ADMIN.value)
    if rule.intersection({SystemRole.L2_ENGINEER.value, SystemRole.L3_ENGINEER.value}):
        canonical.add(OperationalRole.HITL_APPROVER.value)
    return canonical
