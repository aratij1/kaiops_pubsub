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

export type NavigationGroup = "operations" | "intelligence" | "automation" | "platform";
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
  { id: "operations", label: "Operations" },
  { id: "intelligence", label: "Intelligence" },
  { id: "automation", label: "Automation" },
  { id: "platform", label: "Platform" },
] as const satisfies readonly { id: NavigationGroup; label: string }[];

export const NAVIGATION_ITEMS: readonly NavigationItem[] = [
  { id: "dashboard", legacyTab: "home", path: "/", label: "Overview", pageTitle: "Operations Command Center", description: "Production health, attention, automation, approvals, changes, and readiness.", group: "operations", routeModule: "dashboard", icon: "dashboard", keywords: ["operations", "overview", "command center"], allowedRoles: ALL_ROLES },
  { id: "incidents", legacyTab: "summary", path: "/incidents", label: "Unified Inbox", pageTitle: "Unified Inbox", description: "Triage correlated signals, investigate evidence, and prepare governed decisions.", group: "operations", routeModule: "incidents", icon: "incidents", keywords: ["signals", "alerts", "case", "investigate", "evidence", "rca"], allowedRoles: ALL_ROLES, related: ["alerts", "approvals"] },
  { id: "applications", legacyTab: "admin", path: "/applications", label: "Applications", pageTitle: "Applications", description: "Onboard and manage business applications.", group: "operations", routeModule: "applications", icon: "applications", keywords: ["projects", "applications", "onboarding"], allowedRoles: ADMIN_ROLES },
  { id: "cloudResources", legacyTab: "admin", path: "/cloud-ops/resources", label: "Estate", pageTitle: "Resource Estate", description: "Browse resources, ownership, tags, and topology evidence.", group: "operations", routeModule: "cloud-ops/resources", icon: "cloudResources", keywords: ["estate", "inventory", "resources", "topology", "cloud"], allowedRoles: ADMIN_ROLES, related: ["cloudConnections", "services"] },
  { id: "copilot", legacyTab: "copilot", path: "/copilot", label: "Kai", pageTitle: "Kai Intelligence", description: "Grounded operational intelligence and investigation.", group: "intelligence", routeModule: "copilot", icon: "copilot", keywords: ["kai", "assistant", "analysis", "insight"], allowedRoles: ALL_ROLES },
  { id: "knowledge", legacyTab: "rag", path: "/knowledge", label: "Knowledge", pageTitle: "Knowledge", description: "Govern evidence sources and approved runbooks.", group: "intelligence", routeModule: "knowledge", icon: "knowledge", keywords: ["rag", "documents", "runbooks"], allowedRoles: ADMIN_ROLES },
  { id: "approvals", legacyTab: "approval", path: "/approvals", label: "Approvals", pageTitle: "Approvals", description: "Review complete decision packets assigned to you.", group: "automation", routeModule: "approvals", icon: "approvals", keywords: ["review", "decision", "human gate"], allowedRoles: ALL_ROLES, related: ["incidents", "closed"] },
  { id: "operationsCockpit", legacyTab: "admin", path: "/cloud-ops/cockpit", label: "Capabilities", pageTitle: "Automation Capabilities", description: "Inspect readiness and safely simulate governed capabilities.", group: "automation", routeModule: "cloud-ops/cockpit", icon: "operationsCockpit", keywords: ["capabilities", "automation", "readiness", "execution"], allowedRoles: ADMIN_ROLES, related: ["cloudResources", "services"] },
  { id: "cloudConnections", legacyTab: "admin", path: "/cloud-ops/connections", label: "Integrations", pageTitle: "Integrations", description: "Register and validate provider-neutral connections.", group: "platform", routeModule: "cloud-ops/connections", icon: "cloudConnections", keywords: ["integrations", "connectors", "cloud", "providers"], allowedRoles: ADMIN_ROLES, related: ["cloudResources", "services"] },
  { id: "admin", legacyTab: "admin", path: "/admin", label: "Settings", pageTitle: "Platform Settings", description: "Manage identities, access, policy, and platform settings.", group: "platform", routeModule: "admin", icon: "admin", keywords: ["settings", "users", "roles", "access"], allowedRoles: ADMIN_ROLES },
  { id: "alerts", legacyTab: "stream", path: "/alerts", label: "Alert Stream", pageTitle: "Alert Stream", description: "Technical alert intake.", group: "operations", routeModule: "alerts", icon: "alerts", keywords: ["triage", "alerts", "events"], allowedRoles: ALL_ROLES, related: ["incidents"], showInNavigation: false },
  { id: "closed", legacyTab: "closed", path: "/closed-incidents", label: "Closed Incidents", pageTitle: "Closed Incidents", description: "Verified outcomes and immutable decision history.", group: "operations", routeModule: "closed-incidents", icon: "closed", keywords: ["resolved", "historical", "outcomes"], allowedRoles: ALL_ROLES, related: ["incidents"], showInNavigation: false },
  { id: "serviceOnboarding", legacyTab: "admin", path: "/services/onboarding", label: "Service Onboarding", pageTitle: "Service Onboarding", description: "Compatibility onboarding route.", group: "platform", routeModule: "services/onboarding", icon: "serviceOnboarding", keywords: ["onboarding", "templates"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
  { id: "services", legacyTab: "admin", path: "/services/360", label: "Service 360", pageTitle: "Service 360", description: "Service readiness context.", group: "operations", routeModule: "services/360", icon: "services", keywords: ["service", "readiness"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
  { id: "audit", legacyTab: "safety", path: "/audit", label: "Platform Health & Audit", pageTitle: "Platform Health & Audit", description: "Platform health and immutable audit events.", group: "platform", routeModule: "audit", icon: "audit", keywords: ["health", "audit", "compliance"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
  { id: "integrations", legacyTab: "admin", path: "/integrations", label: "Integration setup", pageTitle: "Integration setup", description: "Compatibility route.", group: "platform", routeModule: "integrations", icon: "integrations", keywords: ["connectors"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
  { id: "agentFlow", legacyTab: "trace", path: "/agent-flow", label: "Kai Trace", pageTitle: "Kai Trace", description: "Developer-mode workflow details.", group: "platform", routeModule: "agent-flow", icon: "agentFlow", keywords: ["trace", "developer"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
  { id: "safety", legacyTab: "safety", path: "/gateway-safety", label: "Gateway safety details", pageTitle: "Gateway safety details", description: "Developer-mode policy details.", group: "platform", routeModule: "gateway-safety", icon: "safety", keywords: ["policy", "developer"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
  { id: "executive", legacyTab: "executive", path: "/executive", label: "Reliability report", pageTitle: "Reliability report", description: "Compatibility reporting route.", group: "operations", routeModule: "executive", icon: "executive", keywords: ["metrics"], allowedRoles: ADMIN_ROLES, showInNavigation: false },
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
