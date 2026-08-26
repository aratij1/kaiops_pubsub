import { expect, test } from "@playwright/test";

const username = process.env.KAIOPS_E2E_USERNAME || "admin";
const password = process.env.KAIOPS_E2E_PASSWORD || "Admin@123456";

function unwrap(payload) {
  return payload?.data || payload || {};
}

test("ten production incident cockpits are read-only and status-consistent", async ({ page, request }) => {
  test.setTimeout(10 * 60_000);
  const loginResponse = await request.post("/api-gateway/auth/login", {
    data: { username, password, device: "playwright-ten-incident-audit" },
  });
  expect(loginResponse.ok()).toBeTruthy();
  const login = await loginResponse.json();
  const headers = { Authorization: `Bearer ${login.access_token}` };
  const metadataResponse = await request.get("/api-gateway/incidents/metadata?limit=50", { headers });
  expect(metadataResponse.ok()).toBeTruthy();
  const metadata = unwrap(await metadataResponse.json());
  const incidents = (metadata.rows || []).filter((row) => row.alert_id).slice(0, 10);
  expect(incidents).toHaveLength(10);

  const forbiddenMutations = [];
  page.on("request", (req) => {
    if (req.method() !== "GET" && /diagnostic\/complete|remediation\/execute|approval\/approve|rollback/.test(req.url())) {
      forbiddenMutations.push(`${req.method()} ${req.url()}`);
    }
  });

  const results = [];
  for (const row of incidents) {
    const alertId = String(row.alert_id);
    const incidentId = String(row.incident_id || row.id || "");
    expect(incidentId, `persisted incident identity for ${alertId}`).not.toBe("");
    const beforeResponse = await request.get(`/api-gateway/alerts/${encodeURIComponent(alertId)}/processed-result`, { headers });
    expect(beforeResponse.ok(), `processed-result before opening ${alertId}`).toBeTruthy();
    const before = unwrap(await beforeResponse.json());
    const beforeStatus = String(before.incident?.status || row.status || "unknown").toLowerCase();

    // Audit the current incident command surface. The legacy alert cockpit
    // depends on a second processed-result read and can legitimately show its
    // bounded timeout state without saying anything about the incident route.
    await page.goto(`/incidents/${encodeURIComponent(incidentId)}`);
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: /sign in/i }).click();
    const cockpit = page.locator(".incident-command");
    await expect(cockpit).toBeVisible({ timeout: 45_000 });
    await expect(cockpit.locator(".ic-resolution")).toBeVisible({ timeout: 30_000 });
    await expect(cockpit.getByText("Recommended resolution", { exact: true })).toBeVisible();
    const cockpitText = await cockpit.innerText();
    const terminal = ["closed", "resolved"].includes(beforeStatus);
    if (!terminal) {
      expect(cockpitText, `${alertId} must not claim auto-closure while ${beforeStatus}`).not.toMatch(/auto-closing|closure in progress/i);
    }
    await page.waitForTimeout(1_500);

    const afterResponse = await request.get(`/api-gateway/alerts/${encodeURIComponent(alertId)}/processed-result`, { headers });
    expect(afterResponse.ok(), `processed-result after opening ${alertId}`).toBeTruthy();
    const after = unwrap(await afterResponse.json());
    const afterStatus = String(after.incident?.status || "unknown").toLowerCase();
    expect(afterStatus, `${alertId} status changed merely by viewing`).toBe(beforeStatus);
    results.push({ incident_id: incidentId, alert_id: alertId, before_status: beforeStatus, after_status: afterStatus, terminal });
  }

  expect(forbiddenMutations).toEqual([]);
  console.log("TEN_INCIDENT_AUDIT", JSON.stringify(results));
});
