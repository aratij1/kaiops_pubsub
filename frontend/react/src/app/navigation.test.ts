import { describe, expect, it } from "vitest";

import { breadcrumbForPath, LEGACY_REDIRECTS, NAVIGATION_GROUPS, NAVIGATION_ITEMS, PATH_BY_TAB, searchNavigation, tabForPath } from "./navigation";
import { allowedLegacyTabsForRole, canAccessDestination, canAccessTab, permissionExplanation } from "./permissions";

describe("authoritative navigation", () => {
  it("has unique canonical paths and destination identifiers", () => {
    expect(new Set(NAVIGATION_ITEMS.map((item) => item.path)).size).toBe(NAVIGATION_ITEMS.length);
    expect(new Set(NAVIGATION_ITEMS.map((item) => item.id)).size).toBe(NAVIGATION_ITEMS.length);
    expect(NAVIGATION_GROUPS.map((group) => group.label)).toEqual(["Operations", "Intelligence", "Governance", "Platform", "Administration"]);
  });

  it("maps every route through its legacy compatibility tab", () => {
    for (const item of NAVIGATION_ITEMS) {
      expect(tabForPath(item.path)).toBe(item.legacyTab);
      expect(PATH_BY_TAB[item.legacyTab]).toBeTruthy();
    }
  });

  it("redirects legacy approval and page aliases to canonical bookmarks", () => {
    expect(LEGACY_REDIRECTS).toContainEqual({ from: "/approval", to: "/approvals" });
    expect(LEGACY_REDIRECTS).toContainEqual({ from: "/approval-queue-legacy", to: "/approvals" });
    expect(LEGACY_REDIRECTS).toContainEqual({ from: "/stream", to: "/alerts" });
  });

  it("keeps restricted destinations out of role navigation and explains why", () => {
    expect(canAccessTab("l1_operator", "home")).toBe(true);
    expect(canAccessDestination("l1_operator", "alerts")).toBe(true);
    expect(canAccessDestination("l1_operator", "admin")).toBe(false);
    expect(allowedLegacyTabsForRole("l1_operator")).toEqual(["home", "stream", "summary"]);
    expect(allowedLegacyTabsForRole("administrator")).toContain("executive");
    expect(permissionExplanation("l1_operator", "admin")).toMatch(/not available.*l1 operator/i);
  });

  it("uses the same permitted registry for global navigation search", () => {
    expect(searchNavigation("connector", "administrator").map((item) => item.id)).toEqual(["integrations"]);
    expect(searchNavigation("connector", "l1_operator")).toEqual([]);
    expect(searchNavigation("human gate", "administrator").map((item) => item.id)).toEqual(["approvals"]);
  });

  it("derives breadcrumbs and contextual workflow relationships", () => {
    expect(breadcrumbForPath("/approvals").map((item) => item.label)).toEqual(["Operations", "Approvals"]);
    expect(NAVIGATION_ITEMS.find((item) => item.id === "incidents")?.related).toEqual(["alerts", "approvals"]);
  });
});
