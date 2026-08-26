import { expect, test } from "@playwright/test";

test.skip(!process.env.KAIOPS_LIVE_E2E, "Set KAIOPS_LIVE_E2E=1 to run against a live API stack");

test("live RCA regenerates context, impact, and resolution", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto("/");
  const username = page.getByLabel("Username");
  if (await username.isVisible().catch(() => false)) {
    await username.fill(process.env.KAIOPS_E2E_USERNAME || "admin");
    await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
    await page.getByRole("button", { name: "Sign in securely" }).click();
    await expect(page.getByRole("heading", { name: "Operations Overview" })).toBeVisible({ timeout: 30_000 });
  }
  await page.getByRole("button", { name: "Unified Inbox" }).click();
  await expect(page.getByRole("heading", { name: "Unified Inbox" })).toBeVisible({ timeout: 30_000 });
  const incident = page.locator(".unified-inbox-card.is-incident").first();
  await expect(incident).toBeVisible({ timeout: 30_000 });
  await incident.getByRole("button", { name: "Open incident" }).click();
  await page.getByRole("tab", { name: "Evidence, RCA, and impact" }).click();
  await expect(page.getByRole("heading", { name: "Evidence & Understanding" })).toBeVisible({ timeout: 30_000 });
  const button = page.getByRole("button", { name: "Rerun RCA" });
  await expect(button).toBeVisible({ timeout: 30_000 });
  const contextResponse = page.waitForResponse(
    (response) => response.url().includes("/context-agent/collect") && response.request().method() === "POST",
    { timeout: 180_000 },
  );
  const resolutionResponse = page.waitForResponse(
    (response) => response.url().includes("/resolution-agent/resolve") && response.request().method() === "POST",
    { timeout: 180_000 },
  );
  await button.click();
  expect((await contextResponse).ok()).toBeTruthy();
  expect((await resolutionResponse).ok()).toBeTruthy();
  await expect(page.getByText(/Smart analysis completed|Fresh context and RCA analysis completed|Verified cached context and RCA loaded/)).toBeVisible({ timeout: 180_000 });
  await expect(page.getByText("What happened", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("Why it matters", { exact: false }).first()).toBeVisible();
  await expect(page.getByText("What to do next", { exact: false }).first()).toBeVisible();
  await page.getByRole("tab", { name: "Resolve incident" }).click();
  await expect(page.getByText("Recommended response", { exact: true })).toBeVisible({ timeout: 30_000 });
});
