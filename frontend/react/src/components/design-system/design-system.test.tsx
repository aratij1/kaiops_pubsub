// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button } from "react-aria-components";
import { describe, expect, it, vi } from "vitest";

import { ConfirmationDialog, LoadingState, SectionNavigation, StatusBadge } from ".";

describe("KaiMS design system", () => {
  it("exposes meaningful status text while keeping the icon decorative", () => {
    const { container } = render(<StatusBadge tone="critical">Critical</StatusBadge>);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("announces loading activity", () => {
    render(<LoadingState label="Collecting evidence" />);
    expect(screen.getByRole("status")).toHaveTextContent("Collecting evidence");
  });

  it("changes sections with keyboard navigation", async () => {
    const user = userEvent.setup();
    render(<SectionNavigation items={[{ id: "one", label: "Context", content: "Context panel" }, { id: "two", label: "Evidence", content: "Evidence panel" }]} />);
    const contextTab = screen.getByRole("tab", { name: "Context" });
    contextTab.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Evidence" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Evidence panel")).toBeVisible();
  });

  it("requires confirmation and returns focus after a destructive action", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn();
    render(<ConfirmationDialog trigger={<Button>Delete record</Button>} title="Delete this record?" description="This cannot be undone." confirmLabel="Delete" destructive onConfirm={confirm} />);
    const trigger = screen.getByRole("button", { name: "Delete record" });
    await user.click(trigger);
    expect(screen.getByRole("alertdialog")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(confirm).toHaveBeenCalledOnce();
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});
