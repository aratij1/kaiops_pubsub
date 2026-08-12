import { expect, test } from "@playwright/test";

test("incident detail preserves nested alert identity while details load", async ({ page }) => {
  const alertId = "11111111-1111-4111-8111-111111111111";
  const incidentId = "22222222-2222-4222-8222-222222222222";
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    let body = { data: [], rows: [], summary: {}, items: [] };
    if (path === "/auth/config") body = { mode: "local", local_development_only: true };
    else if (path === "/auth/login") body = { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } };
    else if (path === "/healthz") body = { status: "ok" };
    else if (path.startsWith("/incidents/metadata")) body = { rows: [{ incident_id: incidentId, title: "Context agent incident", service: "kaiops-context-agent", environment: "prod", status: "investigating", projection_payload: { alert_id: alertId, event_payload: { alert_id: alertId, incident_id: incidentId } } }] };
    else if (path.startsWith(`/alerts/${alertId}/processed-result`)) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      body = { data: { alert: { id: alertId, name: "ContextAgentFailure", service: "kaiops-context-agent", severity: "high" }, incident: { id: incidentId, service: "kaiops-context-agent", environment: "prod", status: "investigating" }, context: { metadata: {} }, timeline: [] } };
    } else if (path.startsWith("/alerts/all") || path.startsWith("/landing-pad/recent") || path === "/applications") body = { data: { rows: [] } };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/incidents");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("button", { name: "Context agent incident", exact: true })).toBeVisible();
  await expect(page.getByText(incidentId, { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Context agent incident", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`alert_id=${alertId}`));
  await expect(page.getByRole("heading", { name: "Incident Response" })).toBeVisible();
  await expect(page.getByText("Select an alert in Alert Stream to open the detail tabs workspace.")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "kaiops-context-agent: ContextAgentFailure" })).toBeVisible({ timeout: 5000 });
  await expect(page.getByText(incidentId, { exact: true })).toBeVisible();
  await expect(page.locator(".detail-context")).toContainText("Severity: HIGH");
  await expect(page.locator(".detail-context")).toContainText("Status: investigating");
});
