import { expect, test } from "@playwright/test";

const rows = Array.from({ length: 12 }, (_, index) => ({
  alert_id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
  id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
  name: `Checkout latency signal ${index + 1}`,
  description: "P95 latency exceeded the service objective and requires operator review.",
  service: `checkout-${index % 3}`,
  application: "KaiOps",
  severity: ["critical", "high", "warning"][index % 3],
  status: "active",
  source_channel: ["prometheus", "log", "email"][index % 3],
  created_at: new Date(Date.now() - index * 60000).toISOString(),
}));

test("all alert views render, switch, and reflow without page overflow", async ({ page }) => {
  test.setTimeout(90_000);
  await page.route("**/api-gateway/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api-gateway/, "");
    const body = path === "/auth/login"
      ? { access_token: "alerts-token", refresh_token: "refresh", user: { id: 1, username: "admin", role_name: "Administrator" } }
      : path === "/healthz" ? { status: "ok" }
        : path.startsWith("/alerts/all") ? { data: { rows } }
          : path.startsWith("/landing-pad/recent") ? { data: { rows: [] } }
            : { data: {}, rows: [], summary: {}, items: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });

  await page.goto("/alerts");
  await page.getByLabel("Username").fill("admin");
  await page.getByLabel("Password").fill("Admin@123456");
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Operations Feed" })).toBeVisible();
  const heroStyle = await page.locator(".operations-feed-hero").evaluate((element) => {
    const style = getComputedStyle(element);
    return { color: style.color, backgroundImage: style.backgroundImage };
  });
  expect(heroStyle.color).toBe("rgb(23, 32, 51)");
  expect(heroStyle.backgroundImage).toContain("rgb(255, 255, 255)");

  await page.evaluate(() => document.documentElement.setAttribute("data-ui-theme", "dark"));
  const darkStyle = await page.locator(".operations-feed-hero").evaluate((element) => {
    const style = getComputedStyle(element);
    const bodyStyle = getComputedStyle(document.body);
    return {
      color: style.color,
      backgroundImage: style.backgroundImage,
      bodyBackground: bodyStyle.backgroundImage,
    };
  });
  expect(darkStyle.color).toBe("rgb(231, 237, 247)");
  expect(darkStyle.backgroundImage).toContain("rgb(17, 30, 50)");
  expect(darkStyle.bodyBackground).toContain("rgb(8, 15, 27)");

  for (const name of [/Unified Signal Inbox/, /Alert \+ Stream/, /Correlation Timeline/]) {
    const radio = page.getByRole("radio", { name });
    await expect(radio).toBeVisible();
    await radio.click();
    await expect(radio).toHaveAttribute("aria-checked", "true");
  }

  await page.getByRole("radio", { name: /Alert \+ Stream/ }).click();
  await expect(page.locator(".alert-split-workspace")).toBeVisible();
  await expect(page.locator(".alert-split-queue")).toBeVisible();
  await expect(page.locator(".alert-split-evidence")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBeTruthy();

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBeTruthy();
  await expect(page.getByRole("radio", { name: /Unified Signal Inbox/ })).toBeVisible();
});
