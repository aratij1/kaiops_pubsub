import { expect, test } from "@playwright/test";

async function signIn(page, path = "/") {
  await page.goto(path);
  const username = page.getByLabel("Username");
  await expect(username).toBeVisible({ timeout: 30_000 });
  await username.fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: /sign in/i }).click();
  await expect(page.locator(".app-layout")).toBeVisible({ timeout: 45_000 });
}

async function observeStability(page, navigationLabel, path, rootSelector, screenshot, durationMs = Number(process.env.KAIMS_STABILITY_WINDOW_MS || 65_000)) {
  await expect(page).toHaveURL(new RegExp(`${path.replace("/", "\\/")}$`));
  const root = page.locator(rootSelector);
  await expect(root).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(3_000);
  await page.evaluate((selector) => {
    const target = document.querySelector(selector);
    window.__kaiStability = { mutations: 0, shifts: 0, shiftEntries: [], replacements: 0, startHeight: target?.getBoundingClientRect().height || 0 };
    window.__kaiRoot = target;
    window.__kaiObserver = new MutationObserver((records) => {
      window.__kaiStability.mutations += records.filter((record) => record.type === "childList").length;
    });
    if (target) window.__kaiObserver.observe(target, { childList: true, subtree: true });
    window.__kaiLayoutObserver = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) if (!entry.hadRecentInput) {
        window.__kaiStability.shifts += entry.value;
        window.__kaiStability.shiftEntries.push({ value: entry.value, startTime: entry.startTime, sources: (entry.sources || []).map((source) => ({ node: source.node?.className || source.node?.tagName || "unknown", previousRect: source.previousRect, currentRect: source.currentRect })) });
      }
    });
    window.__kaiLayoutObserver.observe({ type: "layout-shift", buffered: false });
    window.__kaiRootTimer = window.setInterval(() => {
      if (!window.__kaiRoot?.isConnected || document.querySelector(selector) !== window.__kaiRoot) window.__kaiStability.replacements += 1;
    }, 100);
  }, rootSelector);
  await page.waitForTimeout(durationMs);
  const result = await page.evaluate((selector) => {
    window.__kaiObserver?.disconnect();
    window.__kaiLayoutObserver?.disconnect();
    window.clearInterval(window.__kaiRootTimer);
    const target = document.querySelector(selector);
    const animated = target ? [...target.querySelectorAll("*")].filter((node) => getComputedStyle(node).animationName !== "none").length : 0;
    return { ...window.__kaiStability, animated, endHeight: target?.getBoundingClientRect().height || 0 };
  }, rootSelector);
  await page.screenshot({ path: screenshot, fullPage: true });
  const diagnostic = {
    ...result,
    shiftEntries: result.shiftEntries.slice(-8).map((entry) => ({
      value: entry.value,
      startTime: entry.startTime,
      sources: entry.sources.map((source) => ({
        node: source.node,
        dx: source.currentRect.x - source.previousRect.x,
        dy: source.currentRect.y - source.previousRect.y,
        dw: source.currentRect.width - source.previousRect.width,
        dh: source.currentRect.height - source.previousRect.height,
      })),
    })),
  };
  console.log(`${navigationLabel} stability`, JSON.stringify(diagnostic));
  expect(result.shifts).toBeLessThan(0.02);
  expect(result.replacements).toBe(0);
  expect(result.animated).toBe(0);
  expect(Math.abs(result.endHeight - result.startHeight)).toBeLessThanOrEqual(4);
  return result;
}

test("Live Alerts and Approvals remain visually stable between data events", async ({ page }) => {
  test.setTimeout(300_000);
  const failures = [];
  const pageErrors = [];
  page.on("requestfailed", (request) => failures.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`));
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await signIn(page, "/alerts");
  const alerts = await observeStability(page, "Live Alerts", "/alerts", ".ingestion-stream-page", "artifacts/live-alerts-stability.png");
  await signIn(page, "/approvals");
  const approvals = await observeStability(page, "Approvals", "/approvals", ".approval-workspace", "artifacts/approvals-stability.png");
  expect(pageErrors).toEqual([]);
  expect(failures.filter((item) => !item.includes("events/operations") && !(item.includes("/processed-result") && item.includes("ERR_ABORTED")))).toEqual([]);
  expect(alerts.mutations).toBeLessThan(15);
  expect(approvals.mutations).toBeLessThan(15);
});

test("Open incident cockpit preserves the selected alert details route", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, "/incidents");
  await page.getByRole("navigation", { name: "Operations workflow" })
    .getByRole("button").filter({ hasText: "Live Alerts" }).click();
  const openCockpit = page.getByRole("button", { name: /Open incident|Review alert|View audit details/ }).first();
  await expect(openCockpit).toBeVisible({ timeout: 45_000 });
  await openCockpit.click();
  await expect(page).toHaveURL(/\/?\?workspace=alert&alert_id=[^&]+$/, { timeout: 30_000 });
  await expect(page.locator(".alert-details-cockpit")).toBeVisible({ timeout: 30_000 });
  await expect(page.locator(".alert-details-cockpit").getByRole("heading", { name: "Incident Response" })).toBeVisible();
  const cockpitTabs = page.getByRole("tablist", { name: "Incident workspace sections" });
  await expect(cockpitTabs.getByRole("tab", { name: "Resolve incident" })).toHaveCount(1);
  await expect(cockpitTabs.getByRole("tab", { name: "Resolution" })).toHaveCount(0);
  await cockpitTabs.getByRole("tab", { name: "Resolve incident" }).click();
  await expect(page.getByRole("heading", { name: "Decision & Approval" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Plan editor and guarded execution" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Execution Plan" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Complete the current step" })).toBeVisible();
});

test("incident service search converges when changed during initial loading", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page, "/incidents");
  await expect(page.getByRole("navigation", { name: "Operations workflow" })
    .getByRole("button").filter({ hasText: "Incidents" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: "Alerts & Incidents" })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("textbox", { name: "Service" }).fill("kaiops-core1");
  await expect(page.getByRole("row", { name: /kaiops-core1/ }).first()).toBeVisible({ timeout: 30_000 });
});

test("administrator dashboard uses the application workspace selected at sign-in", async ({ page }) => {
  test.setTimeout(120_000);
  await signIn(page);
  await expect(page.getByLabel("Application scope")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Reliability Overview" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Service Risk" })).toBeVisible();
  await expect(page.locator(".hero-user")).toContainText("Administrator");
});
