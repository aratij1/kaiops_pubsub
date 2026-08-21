from __future__ import annotations

from api_gateway.modules.users.models import SystemRole

ADMIN_ROLE = SystemRole.ADMINISTRATOR.value
DOCUMENT_PROVIDER_ROLES = {
    SystemRole.ADMINISTRATOR.value,
    SystemRole.L2_ENGINEER.value,
    SystemRole.L3_ENGINEER.value,
}
AUTHENTICATED_WRITE_RULES: tuple[tuple[set[str] | None, str, set[str] | None], ...] = (
    ({"GET"}, "/events/operations", None),
    (None, "/applications", {ADMIN_ROLE}),
    (None, "/onboarding", {ADMIN_ROLE}),
    (None, "/monitoring", {ADMIN_ROLE}),
    (None, "/operations/queues", {ADMIN_ROLE}),
    ({"POST", "PUT", "DELETE", "PATCH"}, "/rag", DOCUMENT_PROVIDER_ROLES),
    ({"POST", "PUT", "DELETE", "PATCH"}, "/model", {ADMIN_ROLE}),
    ({"POST", "PUT", "DELETE", "PATCH"}, "/approval", None),
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
