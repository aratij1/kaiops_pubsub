import { NAVIGATION_ITEMS, type LegacyTabId, type NavigationId, type NavigationRole } from "./navigation";

export type KaiOpsRole = NavigationRole;

export function canAccessDestination(role: string, navigationId: NavigationId): boolean {
  const item = NAVIGATION_ITEMS.find((candidate) => candidate.id === navigationId);
  return Boolean(item?.allowedRoles.includes(role as NavigationRole));
}

export function canAccessTab(role: KaiOpsRole, tabId: LegacyTabId): boolean {
  return NAVIGATION_ITEMS.some((item) => item.legacyTab === tabId && item.allowedRoles.includes(role));
}

export function allowedLegacyTabsForRole(role: string): readonly LegacyTabId[] {
  return [...new Set(NAVIGATION_ITEMS.filter((item) => item.allowedRoles.includes(role as NavigationRole)).map((item) => item.legacyTab))];
}

export function permissionExplanation(role: string, navigationId: NavigationId): string | null {
  const item = NAVIGATION_ITEMS.find((candidate) => candidate.id === navigationId);
  if (!item || item.allowedRoles.includes(role as NavigationRole)) return null;
  return `${item.label} is not available to the ${role.replaceAll("_", " ")} role. Contact an administrator if your responsibilities require access.`;
}
