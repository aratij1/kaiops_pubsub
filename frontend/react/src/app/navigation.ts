export type LegacyTabId =
  | "home"
  | "stream"
  | "copilot"
  | "executive"
  | "admin"
  | "trace"
  | "safety"
  | "rag"
  | "closed"
  | "summary"
  | "approval";

export type NavigationGroup = "work" | "administration";
export type NavigationRole = "admin" | "hitl_reviewer";
export type NavigationIcon = "dashboard" | "alerts" | "incidents" | "approvals" | "copilot" | "agentFlow" | "knowledge" | "safety" | "audit" | "closed" | "applications" | "operationsCockpit" | "cloudConnections" | "cloudResources" | "serviceOnboarding" | "services" | "integrations" | "admin" | "executive";
export type NavigationId = NavigationIcon;

export interface NavigationItem {
  id: NavigationId;
  legacyTab: LegacyTabId;
  path: string;
  label: string;
  pageTitle: string;
  description: string;
  group: NavigationGroup;
  routeModule: string;
  icon: NavigationIcon;
  keywords: readonly string[];
  allowedRoles: readonly NavigationRole[];
  related?: readonly NavigationId[];
  showInNavigation?: boolean;
}

const ALL_ROLES = ["admin", "hitl_reviewer"] as const;
const ADMIN_ROLES = ["admin"] as const;

export const NAVIGATION_GROUPS = [
  { id: "work", label: "Review work" },
  { id: "administration", label: "Administration" },
] as const satisfies readonly { id: NavigationGroup; label: string }[];

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
  { id: "dashboard", legacyTab: "home", path: "/", label: "Operations Overview", pageTitle: "Operations Overview", description: "See operational work that needs your next decision.", group: "work", routeModule: "dashboard", icon: "dashboard", keywords: ["operations", "overview", "incident", "summary"], allowedRoles: ALL_ROLES },
  { id: "alerts", legacyTab: "stream", path: "/alerts", label: "Alert Stream", pageTitle: "Alert Stream", description: "Triage and correlate incoming operational alerts.", group: "work", routeModule: "alerts", icon: "alerts", keywords: ["triage", "stream", "alerts", "events"], allowedRoles: ALL_ROLES, related: ["incidents"] },
  { id: "incidents", legacyTab: "summary", path: "/incidents", label: "Incident Queue", pageTitle: "Incident Queue", description: "Investigate evidence and prepare a governed decision.", group: "work", routeModule: "incidents", icon: "incidents", keywords: ["case", "investigate", "evidence", "rca"], allowedRoles: ALL_ROLES, related: ["alerts", "approvals"] },
  { id: "approvals", legacyTab: "approval", path: "/approvals", label: "My Approvals", pageTitle: "My Approvals", description: "Review complete decision packets assigned to you.", group: "work", routeModule: "approvals", icon: "approvals", keywords: ["review", "decision", "human gate"], allowedRoles: ALL_ROLES, related: ["incidents", "closed"] },
  { id: "closed", legacyTab: "closed", path: "/closed-incidents", label: "Closed Incidents", pageTitle: "Closed Incidents", description: "Review verified outcomes and immutable decision history.", group: "work", routeModule: "closed-incidents", icon: "closed", keywords: ["resolved", "historical", "outcomes"], allowedRoles: ALL_ROLES, related: ["incidents"] },
  { id: "applications", legacyTab: "admin", path: "/applications", label: "Projects & Integrations", pageTitle: "Projects & Integrations", description: "Onboard projects and manage their data-source connections.", group: "administration", routeModule: "applications", icon: "applications", keywords: ["projects", "integrations", "connectors", "onboarding"], allowedRoles: ADMIN_ROLES },
  { id: "operationsCockpit", legacyTab: "admin", path: "/cloud-ops/cockpit", label: "Operations Cockpit", pageTitle: "Operations Cockpit", description: "See cross-cloud health, inventory distribution, and service readiness.", group: "administration", routeModule: "cloud-ops/cockpit", icon: "operationsCockpit", keywords: ["cockpit", "cloud", "service", "health", "readiness", "operations"], allowedRoles: ADMIN_ROLES, related: ["cloudResources", "services"] },
  { id: "cloudConnections", legacyTab: "admin", path: "/cloud-ops/connections", label: "Cloud Connections", pageTitle: "Cloud Connections", description: "Register provider-neutral cloud sources and validate read-only access.", group: "administration", routeModule: "cloud-ops/connections", icon: "cloudConnections", keywords: ["cloud", "providers", "connections", "aws", "azure", "gcp", "kubernetes"], allowedRoles: ADMIN_ROLES, related: ["cloudResources", "services"] },
  { id: "cloudResources", legacyTab: "admin", path: "/cloud-ops/resources", label: "Cloud Inventory", pageTitle: "Cloud Inventory", description: "Browse discovered resources, ownership, tags, and topology evidence.", group: "administration", routeModule: "cloud-ops/resources", icon: "cloudResources", keywords: ["inventory", "resources", "topology", "discovery", "assets"], allowedRoles: ADMIN_ROLES, related: ["cloudConnections", "services"] },
  { id: "serviceOnboarding", legacyTab: "admin", path: "/services/onboarding", label: "Service Onboarding", pageTitle: "Service Onboarding", description: "Capture service ownership, telemetry, knowledge, validation, and HITL policies.", group: "administration", routeModule: "services/onboarding", icon: "serviceOnboarding", keywords: ["onboarding", "templates", "ownership", "slo", "telemetry"], allowedRoles: ADMIN_ROLES, related: ["operationsCockpit", "services"] },
  { id: "services", legacyTab: "admin", path: "/services/360", label: "Service 360", pageTitle: "Service 360", description: "See service-to-resource mappings and readiness context.", group: "administration", routeModule: "services/360", icon: "services", keywords: ["service", "360", "readiness", "mapping", "ownership"], allowedRoles: ADMIN_ROLES, related: ["cloudResources", "cloudConnections"] },
  { id: "knowledge", legacyTab: "rag", path: "/knowledge", label: "Knowledge & Runbooks", pageTitle: "Knowledge & Runbooks", description: "Govern evidence sources and approved resolution runbooks.", group: "administration", routeModule: "knowledge", icon: "knowledge", keywords: ["rag", "documents", "runbooks"], allowedRoles: ADMIN_ROLES },
  { id: "admin", legacyTab: "admin", path: "/admin", label: "Users & Access", pageTitle: "Users & Access", description: "Manage identities and the two KaiMS business roles.", group: "administration", routeModule: "admin", icon: "admin", keywords: ["users", "roles", "access"], allowedRoles: ADMIN_ROLES },
  { id: "audit", legacyTab: "safety", path: "/audit", label: "Platform Health & Audit", pageTitle: "Platform Health & Audit", description: "Inspect platform health, enforcement, and immutable audit events.", group: "administration", routeModule: "audit", icon: "audit", keywords: ["health", "audit", "compliance"], allowedRoles: ADMIN_ROLES },
  { id: "integrations", legacyTab: "admin", path: "/integrations", label: "Integration setup", pageTitle: "Integration setup", description: "Compatibility route for project onboarding.", group: "administration", routeModule: "integrations", icon: "integrations", keywords: ["connectors"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
  { id: "copilot", legacyTab: "copilot", path: "/copilot", label: "KaiMS Assistant", pageTitle: "KaiMS Assistant", description: "Contextual grounded assistance.", group: "work", routeModule: "copilot", icon: "copilot", keywords: ["assistant"], allowedRoles: ALL_ROLES, showInNavigation: false },
  { id: "agentFlow", legacyTab: "trace", path: "/agent-flow", label: "Technical Timeline", pageTitle: "Technical Timeline", description: "Internal workflow details.", group: "administration", routeModule: "agent-flow", icon: "agentFlow", keywords: ["trace"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
  { id: "safety", legacyTab: "safety", path: "/gateway-safety", label: "Gateway safety details", pageTitle: "Gateway safety details", description: "Internal policy enforcement details.", group: "administration", routeModule: "gateway-safety", icon: "safety", keywords: ["policy"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
  { id: "executive", legacyTab: "executive", path: "/executive", label: "Reliability report", pageTitle: "Reliability report", description: "Compatibility reporting route.", group: "administration", routeModule: "executive", icon: "executive", keywords: ["metrics"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
];

export const LEGACY_REDIRECTS = [
  { from: "/approval", to: "/approvals" },
  { from: "/approval-queue-legacy", to: "/approvals" },
  { from: "/stream", to: "/alerts" },
  { from: "/summary", to: "/incidents" },
] as const;

export const TAB_SHORTCUT_BY_CODE: Readonly<Record<string, LegacyTabId>> = Object.freeze({
  Digit1: "home", Digit2: "stream", Digit3: "summary", Digit4: "approval", Digit5: "copilot",
  Digit6: "trace", Digit7: "rag", Digit8: "safety", Digit9: "closed", Digit0: "admin",
});

export const VALID_LEGACY_TABS: ReadonlySet<LegacyTabId> = new Set(NAVIGATION_ITEMS.map((item) => item.legacyTab));

export const PATH_BY_TAB: Readonly<Record<LegacyTabId, string>> = Object.freeze(
  NAVIGATION_ITEMS.reduce((paths, item) => {
    if (!paths[item.legacyTab]) paths[item.legacyTab] = item.path;
    return paths;
  }, {} as Record<LegacyTabId, string>),
);

export function navigationItemForPath(pathname: string): NavigationItem {
  return NAVIGATION_ITEMS.find((item) => item.path === pathname) ?? NAVIGATION_ITEMS[0];
}

/** Compatibility mapping while stored users are migrated to the two-role model. */
export function canonicalNavigationRole(role: string): NavigationRole {
  const normalized = role.trim().toLowerCase().replaceAll(" ", "_");
  if (["admin", "administrator"].includes(normalized)) return "admin";
  return "hitl_reviewer";
}

export function tabForPath(pathname: string): LegacyTabId {
  return navigationItemForPath(pathname).legacyTab;
}

export function navigationForRole(role: string): readonly NavigationItem[] {
  const canonicalRole = canonicalNavigationRole(role);
  return NAVIGATION_ITEMS.filter((item) => item.showInNavigation !== false && item.allowedRoles.includes(canonicalRole));
}

export function groupedNavigationForRole(role: string) {
  const permitted = navigationForRole(role);
  return NAVIGATION_GROUPS.map((group) => ({ ...group, items: permitted.filter((item) => item.group === group.id) })).filter((group) => group.items.length);
}

export function searchNavigation(query: string, role: string): readonly NavigationItem[] {
  const canonicalRole = canonicalNavigationRole(role);
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return navigationForRole(role);
  return NAVIGATION_ITEMS.filter(
    (item) => item.showInNavigation !== false && item.allowedRoles.includes(canonicalRole),
  ).filter((item) => {
    const corpus = [item.label, item.pageTitle, item.group, ...item.keywords].join(" ").toLowerCase();
    return words.every((word) => corpus.includes(word));
  });
}

export function breadcrumbForPath(pathname: string) {
  const item = navigationItemForPath(pathname);
  const group = NAVIGATION_GROUPS.find((candidate) => candidate.id === item.group);
  return [{ label: group?.label ?? "KaiMS" }, { label: item.label, path: item.path }] as const;
}
