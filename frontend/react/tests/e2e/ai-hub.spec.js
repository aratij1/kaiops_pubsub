import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/config"
      ? { mode: "local", local_development_only: true }
      : path === "/auth/login"
        ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
        : path === "/healthz"
          ? { status: "ok", service: "api-gateway" }
          : path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent")
            ? { data: { rows: [] } }
            : { data: [], rows: [], summary: {}, items: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
});

async function signInToAiHub(page) {
  await page.goto("/knowledge");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page).toHaveURL(/\/knowledge$/);
}

test("AI Hub presents health, capabilities, and accessible section navigation", async ({ page }) => {
  await signInToAiHub(page);
  await expect(page.getByRole("heading", { level: 1, name: "Knowledge & Runbooks", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 2, name: "Operational intelligence" })).toBeVisible();
  await expect(page.getByRole("region", { name: "AI platform health" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "From evidence to governed action" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: /Agent observability/ }).click();
  await expect(page.getByRole("tab", { name: "Agent activity" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "Observed agent activity" })).toBeVisible();
  await page.getByRole("tab", { name: "Knowledge development" }).click();
  await expect(page.getByRole("heading", { name: "Periodic knowledge development" })).toBeVisible();
  await page.getByRole("tab", { name: "Pipeline queues" }).click();
  await expect(page.getByRole("heading", { name: "Pipeline Queue Manager" })).toBeVisible();
  await page.getByRole("tab", { name: "Topology", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Advanced message topology" })).toBeVisible();
});

test("AI Hub overview reflows without horizontal page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signInToAiHub(page);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await expect(page.getByRole("button", { name: "Refresh status" })).toBeVisible();
});
