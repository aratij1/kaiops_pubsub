import { expect, test } from "@playwright/test";

test("extracted Copilot and Closed Incidents routes render exactly once", async ({ page }) => {
  test.setTimeout(90_000);
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

  await page.goto("/copilot");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Ask KAI", exact: true })).toHaveCount(1);

  await page.goto("/closed-incidents");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page).toHaveURL(/\/closed-incidents$/);
  await expect(page.getByRole("heading", { name: "Closed Tickets", exact: true })).toHaveCount(1);

  await page.goto("/approvals");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page).toHaveURL(/\/approvals$/);
  await expect(page.getByRole("heading", { name: "Approval Workspace", exact: true })).toHaveCount(1);

  await page.goto("/executive");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Executive Dashboard", exact: true })).toHaveCount(1);
});
