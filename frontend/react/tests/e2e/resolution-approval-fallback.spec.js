import { expect, test } from "@playwright/test";

// Regression test for a bug found during Resolution UI review: selectedExecutionPlan.requiresApproval
// (App.jsx) used to fall back to the string "-" when no routing/decision/approval data was present on
// the workflow -- a non-empty string is truthy in JS, so a sparse-routing incident silently rendered
// "Approval Required: yes" and routed "Continue to..." to Approval instead of Execution. The fix
// changes that fallback to `false`. This workflow fixture intentionally omits `decision`,
// `orchestration_decision`, `approval`, and any `events`/`workflow_events` array -- exactly the sparse
// shape that triggered the bug.
test("Resolution tab treats missing routing/approval data as false, not truthy", async ({ page }) => {
  const workflow = {
    alert: { id: "sparse-routing-1", name: "Sparse routing incident", service: "checkout", severity: "high" },
    incident: { id: "incident-sparse-routing-1", status: "investigating" },
    recommendation: {
      id: "33333333-3333-4333-8333-333333333333",
      root_cause: "Checkout pods are crash looping.",
      impact: "Checkout is degraded for a subset of customers.",
      recommended_action: "Restart the affected pod.",
      confidence: 0.8,
      metadata: {
        rca_analysis: { root_cause: "Checkout pods are crash looping.", evidence_used: [], confidence_score: 0.8 },
      },
    },
    // Deliberately no `decision`, `orchestration_decision`, `approval`, or `events`/`workflow_events` --
    // this is what makes selectedAlertRouting, decision, and workflow.approval.required all resolve
    // to nothing on the frontend.
  };

  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/login"
      ? { access_token: "admin-token", refresh_token: "refresh-token", user: { id: 1, username: "admin", role_name: "Administrator" } }
      : path === "/healthz"
        ? { status: "ok", service: "api-gateway" }
        : path.endsWith("/processed-result")
          ? { data: { workflow } }
          : path.startsWith("/alerts/all")
            ? { data: { rows: [
                { alert_id: "sparse-routing-1", id: "sparse-routing-1", name: "Sparse routing incident", service: "checkout", application: "KaiOps", labels: { project_name: "KaiOps" }, severity: "high", status: "active", source: "prometheus" },
              ] } }
            : path.startsWith("/landing-pad/recent")
              ? { data: { rows: [] } }
              : { data: [], rows: [], summary: {}, items: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.route("**/monitoring-adapter/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { workflow } }) });
  });

  await page.goto("/alerts");
  await page.getByLabel("Username").fill(process.env.KAIOPS_E2E_USERNAME || "admin");
  await page.getByLabel("Password").fill(process.env.KAIOPS_E2E_PASSWORD || "Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Operations Feed" })).toBeVisible();

  await page.getByRole("button", { name: "Open incident", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Incident Response" })).toBeVisible();

  const sectionNavigation = page.getByRole("tablist", { name: "Incident workspace sections" });
  await sectionNavigation.getByRole("tab", { name: "Resolve incident", exact: true }).click();

  await expect(page.getByRole("heading", { name: "Decision & Approval" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Plan editor and guarded execution" })).toBeVisible();
});
