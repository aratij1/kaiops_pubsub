import { expect, test } from "@playwright/test";

const json = (body) => ({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

test("KaiMS starts without runtime errors and reaches an interactive login promptly", async ({ page }) => {
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(message.text());
  });
  await page.route("**/api-gateway/auth/config", (route) => route.fulfill(json({ mode: "local", local_development_only: true })));
  await page.route("**/api-gateway/applications", (route) => route.fulfill(json({ data: { rows: [
    { id: "app-mono", name: "mono", environment: "prod", status: "registered" },
  ] } })));

  const started = Date.now();
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Welcome back" })).toBeVisible();
  await expect(page.getByLabel("Application workspace")).toContainText("mono");
  expect(Date.now() - started).toBeLessThan(5_000);
  expect(runtimeErrors).toEqual([]);
});

test("hashed production assets are compressed and immutable", async ({ request }) => {
  const index = await request.get("/");
  const html = await index.text();
  const assetPath = html.match(/<script[^>]+src="([^"]*\/assets\/[^"]+\.js)"/)?.[1];
  expect(assetPath).toBeTruthy();
  const asset = await request.get(assetPath, { headers: { "Accept-Encoding": "gzip" } });
  expect(asset.status()).toBe(200);
  expect(asset.headers()["cache-control"]).toContain("immutable");
  expect(asset.headers()["content-encoding"]).toBe("gzip");
});
