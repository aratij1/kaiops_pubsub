// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RouteRuntimeProvider, type AdminUserForm, type RouteRuntime } from "../../app/routeRuntime";
import AdminRoute from "./AdminRoute";

/**
 * Regression coverage for the Edit User form's Username field.
 *
 * This is the component the /admin route actually renders (wired via
 * app/router.tsx's routeModule: "admin" -> AdminRoute). An earlier fix
 * mistakenly edited the legacy inline admin panel still present in
 * App.jsx, which is not mounted by the current router -- this component's
 * own hardcoded `readOnly` on the Username input was the real bug and is
 * what these tests exercise directly.
 */

const testUser = { id: 42, username: "old-name", email: "old-name@kaiops.example.com", first_name: "Original", last_name: "Name", role_id: 1, role_name: "Administrator", status: "active", is_active: true };

const baseEditForm: AdminUserForm = { id: testUser.id, username: testUser.username, email: testUser.email, first_name: testUser.first_name, last_name: testUser.last_name, role_id: 1, status: "active", is_active: true };

function buildRuntime(overrides: Partial<RouteRuntime["admin"]> = {}): RouteRuntime {
  return {
    session: { accessToken: "test-token" },
    dashboard: {} as any,
    copilot: {} as any,
    closed: {} as any,
    agentFlow: {} as any,
    safety: {} as any,
    knowledge: {} as any,
    incidents: {} as any,
    alerts: {} as any,
    executive: {} as any,
    approvals: {} as any,
    admin: {
      sessionUser: { username: "admin", role_name: "Administrator" },
      sessionError: "",
      authenticated: true,
      users: [testUser],
      roles: [{ id: 1, name: "Administrator" }],
      loading: false,
      error: "",
      createForm: { username: "", email: "", first_name: "", last_name: "", password: "", role_id: 1, status: "active", is_active: true },
      editForm: baseEditForm,
      resetUserId: undefined,
      resetPassword: "",
      refresh: () => {},
      selectUser: () => {},
      updateCreate: () => {},
      updateEdit: vi.fn(),
      setResetPassword: () => {},
      create: (event) => event.preventDefault(),
      update: (event) => event.preventDefault(),
      reset: (event) => event.preventDefault(),
      ...overrides,
    },
  };
}

/** Wraps AdminRoute with real React state for editForm, so the controlled
 * Username <input> actually updates on each keystroke -- the same as it
 * does in the real app (App.jsx's updateEdit sets adminEditUser state,
 * which flows back in as admin.editForm on the next render). A plain
 * `vi.fn()` mock for updateEdit, with no state behind it, would leave the
 * input's value frozen and make every keystroke look like it appended to
 * the original text instead of genuinely editing it. */
function StatefulAdminRouteHarness({ onUpdateEdit }: { onUpdateEdit?: (name: string, value: unknown) => void }) {
  const [editForm, setEditForm] = useState<AdminUserForm>(baseEditForm);
  const runtime = buildRuntime({
    editForm,
    updateEdit: (name, value) => {
      setEditForm((current) => ({ ...current, [name]: value }));
      onUpdateEdit?.(name, value);
    },
  });
  return (
    <RouteRuntimeProvider value={runtime}>
      <AdminRoute />
    </RouteRuntimeProvider>
  );
}

describe("AdminRoute edit user form", () => {
  afterEach(() => {
    cleanup();
  });

  async function openEditForm(runtime: RouteRuntime) {
    render(
      <RouteRuntimeProvider value={runtime}>
        <AdminRoute />
      </RouteRuntimeProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Users & access" }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await screen.findByRole("heading", { name: `Edit ${testUser.username}` });
  }

  it("renders the Username field as an editable input, not read-only", async () => {
    const runtime = buildRuntime();
    await openEditForm(runtime);

    const usernameInput = screen.getByLabelText("Username") as HTMLInputElement;
    expect(usernameInput).not.toHaveAttribute("readonly");
    expect(usernameInput).toBeEnabled();
  });

  it("lets an operator clear the field and type a new username end to end", async () => {
    render(<StatefulAdminRouteHarness />);
    await userEvent.click(screen.getByRole("button", { name: "Users & access" }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await screen.findByRole("heading", { name: `Edit ${testUser.username}` });

    const usernameInput = screen.getByLabelText("Username") as HTMLInputElement;
    expect(usernameInput.value).toBe("old-name");

    await userEvent.clear(usernameInput);
    await userEvent.type(usernameInput, "new-name");

    // If the field were still read-only, none of the above keystrokes
    // would have been accepted and the value would remain "old-name".
    expect(usernameInput.value).toBe("new-name");
  });

  it("reports every keystroke through updateEdit so the change reaches the save handler", async () => {
    const onUpdateEdit = vi.fn();
    render(<StatefulAdminRouteHarness onUpdateEdit={onUpdateEdit} />);
    await userEvent.click(screen.getByRole("button", { name: "Users & access" }));
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await screen.findByRole("heading", { name: `Edit ${testUser.username}` });

    const usernameInput = screen.getByLabelText("Username") as HTMLInputElement;
    await userEvent.clear(usernameInput);
    await userEvent.type(usernameInput, "renamed");

    const usernameCalls = onUpdateEdit.mock.calls.filter(([field]) => field === "username");
    expect(usernameCalls.length).toBeGreaterThan(0);
    expect(usernameCalls[usernameCalls.length - 1][1]).toBe("renamed");
  });

  it("leaves the read-only 'Selected user' field in the Reset password form untouched", async () => {
    const runtime = buildRuntime();
    render(
      <RouteRuntimeProvider value={runtime}>
        <AdminRoute />
      </RouteRuntimeProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Users & access" }));
    await userEvent.click(await screen.findByRole("button", { name: "Reset" }));

    const selectedUserInput = await screen.findByLabelText("Selected user");
    expect(selectedUserInput).toHaveAttribute("readonly");
  });
});
