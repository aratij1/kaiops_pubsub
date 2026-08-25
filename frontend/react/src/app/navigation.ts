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

export type NavigationGroup = "operations" | "intelligence" | "governance" | "platform" | "administration";
export type NavigationRole = "administrator" | "l1_operator" | "l2_engineer" | "l3_engineer" | "executive";
export type NavigationIcon = "dashboard" | "alerts" | "incidents" | "approvals" | "copilot" | "agentFlow" | "knowledge" | "safety" | "audit" | "closed" | "applications" | "integrations" | "admin" | "executive";
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
  { id: "intelligence", label: "Intelligence" },
  { id: "governance", label: "Governance" },
  { id: "platform", label: "Platform" },
  { id: "administration", label: "Administration" },
] as const satisfies readonly { id: NavigationGroup; label: string }[];

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
  { id: "dashboard", legacyTab: "home", path: "/", label: "Overview", pageTitle: "Incident Summary", group: "operations", routeModule: "dashboard", icon: "dashboard", keywords: ["reliability", "overview", "incident", "summary"], allowedRoles: ALL_ROLES },
  { id: "alerts", legacyTab: "stream", path: "/alerts", label: "Live Stream", pageTitle: "Live Stream", group: "operations", routeModule: "alerts", icon: "alerts", keywords: ["live", "ingestion", "stream", "alerts", "events"], allowedRoles: ALL_ROLES, related: ["incidents"] },
  { id: "incidents", legacyTab: "summary", path: "/incidents", label: "Alerts & Incidents", pageTitle: "Alerts & Incidents", group: "operations", routeModule: "incidents", icon: "incidents", keywords: ["alerts", "case", "investigation", "metadata"], allowedRoles: ALL_ROLES, related: ["alerts", "approvals"] },
  { id: "approvals", legacyTab: "approval", path: "/approvals", label: "Approvals", pageTitle: "Approvals", group: "operations", routeModule: "approvals", icon: "approvals", keywords: ["review", "decision", "human gate"], allowedRoles: INCIDENT_ROLES, related: ["incidents", "closed"], showInNavigation: true },
  { id: "copilot", legacyTab: "copilot", path: "/copilot", label: "KAI Assistant", pageTitle: "KAI Assistant", group: "intelligence", routeModule: "copilot", icon: "copilot", keywords: ["assistant", "analysis", "ai"], allowedRoles: INCIDENT_ROLES, showInNavigation: false },
  { id: "agentFlow", legacyTab: "trace", path: "/agent-flow", label: "Agent Flow", pageTitle: "Agent Flow", group: "intelligence", routeModule: "agent-flow", icon: "agentFlow", keywords: ["trace", "workflow", "agents"], allowedRoles: ENGINEERING_ROLES, showInNavigation: false },
  { id: "knowledge", legacyTab: "rag", path: "/knowledge", label: "AI Hub", pageTitle: "AI Hub", group: "intelligence", routeModule: "knowledge", icon: "knowledge", keywords: ["rag", "documents", "evidence"], allowedRoles: ENGINEERING_ROLES },
  { id: "safety", legacyTab: "safety", path: "/gateway-safety", label: "Gateway Safety", pageTitle: "Gateway Safety", group: "governance", routeModule: "gateway-safety", icon: "safety", keywords: ["policy", "risk", "guardrail"], allowedRoles: ENGINEERING_ROLES, showInNavigation: false },
  { id: "audit", legacyTab: "safety", path: "/audit", label: "Audit", pageTitle: "Audit", group: "governance", routeModule: "audit", icon: "audit", keywords: ["history", "compliance", "events"], allowedRoles: ENGINEERING_ROLES, showInNavigation: false },
  { id: "closed", legacyTab: "closed", path: "/closed-incidents", label: "Closed Incidents", pageTitle: "Closed Incidents", group: "governance", routeModule: "closed-incidents", icon: "closed", keywords: ["resolved", "historical", "tickets"], allowedRoles: INCIDENT_ROLES, related: ["incidents"], showInNavigation: false },
  { id: "applications", legacyTab: "admin", path: "/applications", label: "Project Management", pageTitle: "Project Management", group: "administration", routeModule: "applications", icon: "applications", keywords: ["projects", "services", "inventory"], allowedRoles: ENGINEERING_ROLES },
  { id: "integrations", legacyTab: "admin", path: "/integrations", label: "Project Onboarding", pageTitle: "Project Onboarding", group: "administration", routeModule: "integrations", icon: "integrations", keywords: ["connectors", "monitoring", "providers", "onboarding"], allowedRoles: ENGINEERING_ROLES },
  { id: "admin", legacyTab: "admin", path: "/admin", label: "User Management", pageTitle: "User Management", group: "administration", routeModule: "admin", icon: "admin", keywords: ["users", "roles", "access", "configuration"], allowedRoles: ["administrator"] },
  { id: "executive", legacyTab: "executive", path: "/executive", label: "Executive Dashboard", pageTitle: "Executive Dashboard", group: "governance", routeModule: "executive", icon: "executive", keywords: ["leadership", "business", "metrics"], allowedRoles: ["administrator", "l3_engineer", "executive"], showInNavigation: false },
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
