import { expect, test } from "@playwright/test";

// The existing accessibility.spec.js and discovery-layout.spec.js mock the
// alert list with 0-3 rows, so the alert-stream table has never actually
// been exercised at the row counts it's meant to handle (AlertStreamTable in
// App.jsx uses @tanstack/react-virtual specifically so a large row count
// doesn't degrade). The product keeps at most 30 rows for each of five source
// channels, so 150 is the largest valid balanced stream.

function buildMockAlertRows(count) {
  const rows = [];
  for (let i = 0; i < count; i += 1) {
    rows.push({
      alert_id: `capacity-alert-${i}`,
      id: `capacity-alert-${i}`,
      name: `Capacity alert ${i}`,
      service: `service-${i % 12}`,
      application: "KaiOps",
      labels: { project_name: "KaiOps" },
      severity: ["critical", "high", "warning"][i % 3],
      status: "active",
      source: ["prometheus", "telemetry", "email", "jira", "opensearch"][i % 5],
      created_at: new Date(Date.now() - i * 1000).toISOString(),
    });
  }
  return rows;
}

test("live alert stream bounds and scrolls the 150-row source-balanced input", async ({ page }) => {
  test.setTimeout(90_000);
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  const mockRows = buildMockAlertRows(150);

  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/login"
      ? { access_token: "virtual-token", refresh_token: "virtual-refresh", user: { id: 1, username: "admin", role_name: "Administrator" } }
      : path === "/healthz"
        ? { status: "ok", service: "api-gateway" }
        : path.startsWith("/alerts/all")
          ? { data: { rows: mockRows } }
          : path.startsWith("/landing-pad/recent")
            ? { data: { rows: [] } }
            : { data: [], rows: [], summary: {}, items: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/alerts");
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Operations Feed" })).toBeVisible();

  const stream = page.locator(".ingestion-stream-list");
  await expect(stream).toBeVisible({ timeout: 30_000 });

  // A row near the top of the mocked data should be visible immediately...
  await expect(page.getByText("Capacity alert 0", { exact: true }).first()).toBeVisible();

  // The operational view intentionally bounds the visible working set to 50.
  await expect(page.getByText("Capacity alert 149", { exact: true })).toHaveCount(0);
  await expect(page.locator(".ingestion-event")).toHaveCount(50);

  // Scrolling the virtualized container to the bottom must bring that row
  // into view without a page error, proving the virtualizer keeps rendering
  // newly-scrolled-into-view rows correctly.
  await stream.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  await expect(page.getByText("Capacity alert 49", { exact: true }).first()).toBeVisible({ timeout: 15_000 });

  expect(pageErrors).toEqual([]);
});
