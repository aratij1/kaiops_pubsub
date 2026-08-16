import { expect, test } from "@playwright/test";

const json = (payload) => ({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });

test("connectivity loss is explicit and preserves the workspace", async ({ page, context }) => {
  test.setTimeout(90_000);
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    if (path === "/auth/login") {
      await route.fulfill(json({ access_token: "offline-token", refresh_token: "offline-refresh", user: { id: 1, username: "admin", role_name: "Administrator" } }));
      return;
    }
    await route.fulfill(json({ status: "ok", data: { rows: [] }, rows: [], summary: {}, items: [] }));
  });
  await page.goto("/");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("admin-password");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Reliability Overview" })).toBeVisible();

  await context.setOffline(true);
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.getByRole("alert")).toContainText("Connection lost");
  await expect(page.getByRole("heading", { name: "Reliability Overview" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry connection" })).toBeVisible();
  await context.setOffline(false);
});
