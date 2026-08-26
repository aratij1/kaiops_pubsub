export type LegacyTabId =
  | "home"
  | "stream"
  | "copilot"
  | "executive"
  | "admin"
  | "trace"
  | "safety"
  | "audit"
  | "rag"
  | "closed"
  | "summary"
  | "approval";

export type NavigationGroup = "operations" | "governance" | "platform" | "administration";
export type NavigationRole = "administrator" | "l1_operator" | "l2_engineer" | "l3_engineer" | "executive";
export type NavigationIcon = "dashboard" | "alerts" | "incidents" | "approvals" | "copilot" | "agentFlow" | "knowledge" | "safety" | "audit" | "closed" | "applications" | "integrations" | "admin" | "settings" | "executive";
export type NavigationId = NavigationIcon;

export interface NavigationItem {
  id: NavigationId;
  legacyTab: LegacyTabId;
  path: string;
  label: string;
  pageTitle: string;
  group: NavigationGroup;
  routeModule: string;
  icon: NavigationIcon;
  keywords: readonly string[];
  allowedRoles: readonly NavigationRole[];
  related?: readonly NavigationId[];
  showInNavigation?: boolean;
}

const ALL_ROLES = ["administrator", "l1_operator", "l2_engineer", "l3_engineer", "executive"] as const;
const ENGINEERING_ROLES = ["administrator", "l2_engineer", "l3_engineer"] as const;
const INCIDENT_ROLES = ["administrator", "l2_engineer", "l3_engineer", "executive"] as const;

export const NAVIGATION_GROUPS = [
  { id: "operations", label: "Operations" },
  { id: "platform", label: "Platform" },
  { id: "governance", label: "Governance" },
  { id: "administration", label: "Administration" },
] as const satisfies readonly { id: NavigationGroup; label: string }[];

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
  { id: "dashboard", legacyTab: "home", path: "/", label: "Overview", pageTitle: "Operations Overview", group: "operations", routeModule: "dashboard", icon: "dashboard", keywords: ["attention", "reliability", "overview", "incident", "summary"], allowedRoles: ALL_ROLES },
  { id: "incidents", legacyTab: "summary", path: "/incidents", label: "Unified Inbox", pageTitle: "Unified Inbox", group: "operations", routeModule: "incidents", icon: "incidents", keywords: ["signals", "alerts", "problems", "case", "investigation", "resolution"], allowedRoles: ALL_ROLES, related: ["alerts", "approvals"] },
  { id: "alerts", legacyTab: "stream", path: "/alerts", label: "Alerts", pageTitle: "Alert Signals", group: "operations", routeModule: "alerts", icon: "alerts", keywords: ["signals", "live", "ingestion", "stream", "events"], allowedRoles: ALL_ROLES, related: ["incidents"] },
  { id: "approvals", legacyTab: "approval", path: "/approvals", label: "Approvals", pageTitle: "Approvals", group: "operations", routeModule: "approvals", icon: "approvals", keywords: ["review", "decision", "human gate"], allowedRoles: INCIDENT_ROLES, related: ["incidents", "closed"], showInNavigation: true },
  { id: "copilot", legacyTab: "copilot", path: "/copilot", label: "Kai Assistant", pageTitle: "Kai Assistant", group: "operations", routeModule: "copilot", icon: "copilot", keywords: ["ask", "assistant", "analysis", "ai"], allowedRoles: INCIDENT_ROLES, showInNavigation: false },
  { id: "agentFlow", legacyTab: "trace", path: "/agent-flow", label: "Agent Flow", pageTitle: "Agent Flow", group: "governance", routeModule: "agent-flow", icon: "agentFlow", keywords: ["trace", "workflow", "agents"], allowedRoles: ENGINEERING_ROLES, showInNavigation: false },
  { id: "applications", legacyTab: "admin", path: "/applications", label: "Applications", pageTitle: "Application Portfolio", group: "platform", routeModule: "applications", icon: "applications", keywords: ["projects", "services", "inventory", "readiness"], allowedRoles: ENGINEERING_ROLES },
  { id: "integrations", legacyTab: "admin", path: "/integrations", label: "Integrations", pageTitle: "Integration Launchpad", group: "platform", routeModule: "integrations", icon: "integrations", keywords: ["connectors", "monitoring", "providers", "onboarding"], allowedRoles: ENGINEERING_ROLES },
  { id: "knowledge", legacyTab: "rag", path: "/knowledge", label: "Knowledge", pageTitle: "Operational Knowledge", group: "platform", routeModule: "knowledge", icon: "knowledge", keywords: ["runbooks", "rag", "documents", "evidence"], allowedRoles: ENGINEERING_ROLES },
  { id: "safety", legacyTab: "safety", path: "/automation", label: "Automation", pageTitle: "AI Trust & Automation", group: "governance", routeModule: "gateway-safety", icon: "safety", keywords: ["autonomy", "policy", "risk", "guardrail", "trust"], allowedRoles: ENGINEERING_ROLES },
  { id: "audit", legacyTab: "audit", path: "/audit", label: "Audit", pageTitle: "Audit Trail", group: "governance", routeModule: "audit", icon: "audit", keywords: ["history", "compliance", "events"], allowedRoles: ENGINEERING_ROLES },
  { id: "closed", legacyTab: "closed", path: "/closed-incidents", label: "Closed Incidents", pageTitle: "Closed Incidents", group: "governance", routeModule: "closed-incidents", icon: "closed", keywords: ["resolved", "historical", "tickets"], allowedRoles: INCIDENT_ROLES, related: ["incidents"], showInNavigation: false },
  { id: "admin", legacyTab: "admin", path: "/admin/users", label: "Users & Access", pageTitle: "Users & Access", group: "administration", routeModule: "admin", icon: "admin", keywords: ["users", "roles", "access", "identity"], allowedRoles: ["administrator"] },
  { id: "settings", legacyTab: "admin", path: "/service-control", label: "Service Control", pageTitle: "Service Control Panel", group: "platform", routeModule: "admin", icon: "settings", keywords: ["platform", "services", "health", "status", "control panel"], allowedRoles: ENGINEERING_ROLES },
  { id: "executive", legacyTab: "executive", path: "/executive", label: "Executive Dashboard", pageTitle: "Executive Dashboard", group: "governance", routeModule: "executive", icon: "executive", keywords: ["leadership", "business", "metrics"], allowedRoles: ["administrator", "l3_engineer", "executive"], showInNavigation: false },
];

export const LEGACY_REDIRECTS = [
  { from: "/approval", to: "/approvals" },
  { from: "/approval-queue-legacy", to: "/approvals" },
  { from: "/stream", to: "/alerts" },
  { from: "/summary", to: "/incidents" },
  { from: "/gateway-safety", to: "/automation" },
  { from: "/admin", to: "/admin/users" },
  { from: "/admin/settings", to: "/service-control" },
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
  const normalized = pathname.length > 1 ? pathname.replace(/\/$/, "") : pathname;
  const candidates = NAVIGATION_ITEMS
    .filter((item) => item.path === "/" ? normalized === "/" : normalized === item.path || normalized.startsWith(`${item.path}/`))
    .sort((left, right) => right.path.length - left.path.length);
  return candidates[0] ?? NAVIGATION_ITEMS[0];
}

export function tabForPath(pathname: string): LegacyTabId {
  return navigationItemForPath(pathname).legacyTab;
}

export function navigationForRole(role: string): readonly NavigationItem[] {
  return NAVIGATION_ITEMS.filter((item) => item.showInNavigation !== false && item.allowedRoles.includes(role as NavigationRole));
}

export function groupedNavigationForRole(role: string) {
  const permitted = navigationForRole(role);
  return NAVIGATION_GROUPS.map((group) => ({ ...group, items: permitted.filter((item) => item.group === group.id) })).filter((group) => group.items.length);
}

export function searchNavigation(query: string, role: string): readonly NavigationItem[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return navigationForRole(role);
  return NAVIGATION_ITEMS.filter((item) => item.allowedRoles.includes(role as NavigationRole)).filter((item) => {
    const corpus = [item.label, item.pageTitle, item.group, ...item.keywords].join(" ").toLowerCase();
    return words.every((word) => corpus.includes(word));
  });
}

export function breadcrumbForPath(pathname: string) {
  const item = navigationItemForPath(pathname);
  const group = NAVIGATION_GROUPS.find((candidate) => candidate.id === item.group);
  return [{ label: group?.label ?? "KaiMS" }, { label: item.label, path: item.path }] as const;
}
