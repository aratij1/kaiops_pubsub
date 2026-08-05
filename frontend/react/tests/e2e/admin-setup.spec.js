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

test("admin setup keeps source downloads below file inputs and labels adapter contracts", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("admin-password");
  await page.getByRole("button", { name: "Sign In" }).click();

  await page.getByRole("button", { name: /Admin/ }).click();
  await page.getByRole("button", { name: /Continue (guided )?setup|Open workflow status|Review generated artifacts/ }).click();
  await expect(page.getByRole("heading", { name: "Setup Wizard" })).toBeVisible();
  await page.getByRole("button", { name: "Show full setup" }).click();

  await page.getByText("Optional supporting file", { exact: true }).click();
  const sourceCard = page.locator(".source-doc-upload-card").filter({ hasText: "runbook, ticket export, or notes" });
  await expect(sourceCard.locator("input[type=file]")).toBeVisible();
  await expect(page.getByRole("link", { name: "Download sample file" })).toBeVisible();

  await expect(page.getByLabel("Setup Details")).toBeVisible();
  await page.getByText("Advanced Settings (Optional)").click();
  await page.locator("label").filter({ hasText: "Deployment" }).first().locator("select").selectOption("azure_cloud");
  await expect(page.getByLabel("Azure Subscription ID")).toBeVisible();

  await page.getByText("Open Advanced Tools").click();
  await expect(page.getByText("Monitoring Platform Capabilities")).toBeVisible();
  await expect(page.getByText("real / partial")).toBeVisible();
  await expect(page.getByText("simulated / stub")).toBeVisible();
});
