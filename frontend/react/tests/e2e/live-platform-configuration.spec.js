import { expect, test } from "@playwright/test";

test.skip(!process.env.KAIOPS_LIVE_E2E, "Set KAIOPS_LIVE_E2E=1 to run against a live API stack");

test("live platform navigation and discovered connection remain distinct and usable", async ({ page, request }) => {
  test.setTimeout(120_000);
  const loginResponse = await request.post("/api-gateway/auth/login", { data: {
    username: process.env.KAIOPS_E2E_USERNAME || "admin",
    password: process.env.KAIOPS_E2E_PASSWORD || "Admin@123456",
    device: "playwright-live-platform",
  } });
  expect(loginResponse.ok()).toBeTruthy();
  const login = await loginResponse.json();
  await page.addInitScript((tokens) => window.sessionStorage.setItem("kaims.auth.session.v1", JSON.stringify(tokens)), {
    accessToken: login.access_token,
    refreshToken: login.refresh_token,
  });
  await page.goto("/cloud-ops/connections");

  await expect(page.getByRole("heading", { name: "Provider connections" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "KaiMS local simulator" })).toBeVisible();
  const navigation = page.getByRole("navigation", { name: "Primary navigation" }).first();
  await expect(navigation.getByRole("button", { name: "Platform Settings", exact: true })).toHaveCount(0);

  await navigation.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/settings$/);
  await expect(page.getByRole("heading", { level: 2, name: "Platform Settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Operate the platform as one system." })).toHaveCount(0);

  await navigation.getByRole("button", { name: "Control Plane", exact: true }).click();
  await expect(page).toHaveURL(/\/platform$/);
  await expect(page.getByRole("heading", { name: "Operate the platform as one system." })).toBeVisible();
});
