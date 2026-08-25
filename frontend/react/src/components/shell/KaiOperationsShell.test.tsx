// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NAVIGATION_ITEMS } from "../../app/navigation";
import { KaiOperationsShell } from "./KaiOperationsShell";

const overview = NAVIGATION_ITEMS.find((item) => item.id === "dashboard")!;
const incidents = NAVIGATION_ITEMS.find((item) => item.id === "incidents")!;

afterEach(cleanup);

function renderShell() {
  const onQuery = vi.fn();
  render(<KaiOperationsShell
    navigationGroups={[{ id: "operations", label: "Operations", items: [overview, incidents] }]}
    currentItem={overview}
    currentPath="/"
    role="l1_operator"
    onNavigate={vi.fn()}
    projects={["Payments"]}
    project="Payments"
    onProjectChange={vi.fn()}
    environment="production"
    health={{ ok: true, message: "Healthy" }}
    approvalCount={1}
    notificationCount={1}
    operationalQuery=""
    onOperationalQueryChange={onQuery}
    operationalResults={[]}
    notifications={[{ kind: "Approval reminder", label: "INC-21", meta: "Production change needs review" }]}
    onOpenOperationalItem={vi.fn()}
    onOpenNotifications={vi.fn()}
    onAskKai={vi.fn()}
    user={{ username: "operator", role_name: "l1_operator" }}
    density="comfortable"
    theme="auto"
    onDensityChange={vi.fn()}
    onThemeChange={vi.fn()}
    onLogout={vi.fn()}
  ><p>Route content</p></KaiOperationsShell>);
  return { onQuery };
}

describe("Kai operations shell", () => {
  it("keeps production context visible and opens the keyboard command palette", async () => {
    const user = userEvent.setup();
    renderShell();
    expect(screen.getByText("Payments")).toBeInTheDocument();
    expect(screen.getByText("production")).toBeInTheDocument();
    await user.keyboard("{Control>}k{/Control}");
    const palette = screen.getByRole("dialog", { name: "Search, navigate, or ask Kai" });
    expect(palette).toBeVisible();
    expect(within(palette).getByRole("button", { name: /Unified Inbox/ })).toBeVisible();
    expect(screen.queryByText("Users & Access")).not.toBeInTheDocument();
  });

  it("shows only meaningful operational notifications", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.click(screen.getByRole("button", { name: "1 operational notifications" }));
    expect(screen.getByText("Approval reminder: INC-21")).toBeVisible();
    expect(screen.getByText("Production change needs review")).toBeVisible();
  });
});
