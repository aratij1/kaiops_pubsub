import { expect, test } from "@playwright/test";

const json = (payload) => ({
  status: 200,
  contentType: "application/json",
  body: JSON.stringify(payload),
});

test.beforeEach(async ({ page }) => {
  await page.route("**/api-gateway/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api-gateway/, "");

    if (path === "/auth/login") {
      await route.fulfill(json({
        access_token: "admin-token",
        refresh_token: "refresh-token",
        user: { id: 1, username: "admin", role_name: "Administrator" },
      }));
      return;
    }

    if (path === "/users") {
      await route.fulfill(json({ rows: [{ id: 1, username: "admin", role_name: "Administrator", status: "active", is_active: true }] }));
      return;
    }

    if (path === "/roles") {
      await route.fulfill(json([{ id: 1, name: "Administrator" }, { id: 2, name: "L3 Engineer" }]));
      return;
    }

    if (path === "/onboarding/rules/capabilities") {
      await route.fulfill(json({
        data: {
          rows: [
            {
              platform: "prometheus",
              contract_mode: "real",
              contract_status: "partial",
              contract_label: "Real adapter: file-backed Prometheus rule generation",
              can_pull_rules: true,
              can_push_rules: true,
              supports_simulation: true,
              supports_dashboard_refs: false,
            },
            {
              platform: "datadog",
              contract_mode: "simulated",
              contract_status: "stub",
              contract_label: "Simulated adapter: generated rules are not pushed to the provider",
              can_pull_rules: true,
              can_push_rules: true,
              supports_simulation: true,
              supports_dashboard_refs: true,
            },
          ],
        },
      }));
      return;
    }

    if (path === "/onboarding/state") {
      await route.fulfill(json({ data: [] }));
      return;
    }

    if (path === "/rag/documents") {
      await route.fulfill(json({ data: [] }));
      return;
    }

    await route.fulfill(json({ data: [], rows: [], summary: {}, items: [] }));
  });
});

test("project onboarding exposes a complete monitoring integration contract", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("admin-password");
  await page.getByRole("button", { name: "Sign In" }).click();

  await page.getByRole("button", { name: "Project Onboarding", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Integrations & Monitoring" })).toBeVisible();
  await expect(page.getByLabel("tenant id")).toBeVisible();
  await expect(page.getByLabel("owner team")).toBeVisible();
  await expect(page.getByLabel("Metrics Endpoint")).toBeVisible();
  await expect(page.getByLabel("Labels (comma-separated key=value)")).toBeVisible();
  await expect(page.getByRole("button", { name: "Register Application" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Configured Monitoring Integrations" })).toBeVisible();
});
