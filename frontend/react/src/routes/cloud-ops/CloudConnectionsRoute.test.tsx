// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CloudConnectionsRoute from "./CloudConnectionsRoute";
import * as cloudApi from "./cloudOpsApi";

vi.mock("../../app/routeRuntime", () => ({
  useRouteRuntimeSlice: () => ({ accessToken: "session-token" }),
}));

vi.mock("./cloudOpsApi", async () => {
  const actual = await vi.importActual<typeof import("./cloudOpsApi")>("./cloudOpsApi");
  return {
    ...actual,
    createSimulatorConnection: vi.fn(),
    discoverConnection: vi.fn(),
    listConnections: vi.fn(),
    validateConnection: vi.fn(),
  };
});

const connection = (projectId: string, id = `${projectId}-connection`) => ({
  id,
  tenant_id: "tenant-a",
  project_id: projectId,
  connection_name: `${projectId} provider`,
  provider_type: "simulator",
  status: "ready",
  allowed_regions: ["global"],
  read_capability: true,
  write_capability: false,
  connection_owner: "platform",
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

describe("CloudConnectionsRoute project isolation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(cloudApi.listConnections).mockReset();
    vi.mocked(cloudApi.validateConnection).mockReset().mockResolvedValue({ status: "ready", checks: [], warnings: [], errors: [] });
    vi.mocked(cloudApi.discoverConnection).mockReset().mockResolvedValue({ run_id: "run-1", status: "complete", resources: [], relationships: [] });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("aborts stale loads and never lets an older project replace the selected project", async () => {
    const first = deferred<ReturnType<typeof connection>[]>();
    const second = deferred<ReturnType<typeof connection>[]>();
    vi.mocked(cloudApi.listConnections)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    render(<CloudConnectionsRoute />);
    await act(async () => { vi.advanceTimersByTime(250); });
    const firstSignal = vi.mocked(cloudApi.listConnections).mock.calls[0][2];

    fireEvent.change(screen.getByLabelText("Project ID"), { target: { value: " project-b " } });
    expect(firstSignal?.aborted).toBe(true);
    await act(async () => { vi.advanceTimersByTime(250); });

    await act(async () => { second.resolve([connection("project-b")]); await second.promise; });
    expect(screen.getByText("project-b provider")).toBeInTheDocument();

    await act(async () => { first.resolve([connection("demo-project")]); await first.promise; });
    expect(screen.queryByText("demo-project provider")).not.toBeInTheDocument();
  });

  it("refresh uses the normalized selected project rather than the click event", async () => {
    vi.mocked(cloudApi.listConnections).mockResolvedValue([connection("demo-project")]);
    render(<CloudConnectionsRoute />);
    await act(async () => { vi.advanceTimersByTime(250); await Promise.resolve(); });
    expect(screen.getByText("demo-project provider")).toBeInTheDocument();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /refresh/i })); await Promise.resolve(); });
    expect(cloudApi.listConnections).toHaveBeenCalledTimes(2);
    expect(vi.mocked(cloudApi.listConnections).mock.calls[1][1]).toBe("demo-project");
  });

  it("binds validate and discover to the displayed connection project", async () => {
    vi.mocked(cloudApi.listConnections).mockResolvedValue([connection("demo-project", "connection-1")]);
    render(<CloudConnectionsRoute />);
    await act(async () => { vi.advanceTimersByTime(250); await Promise.resolve(); });
    expect(screen.getByText("demo-project provider")).toBeInTheDocument();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /validate/i })); await Promise.resolve(); });
    expect(cloudApi.validateConnection).toHaveBeenCalled();
    expect(cloudApi.validateConnection).toHaveBeenCalledWith("session-token", "connection-1", expect.any(AbortSignal));

    expect(screen.getByRole("button", { name: /discover/i })).not.toBeDisabled();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /discover/i })); await Promise.resolve(); });
    expect(cloudApi.discoverConnection).toHaveBeenCalled();
    expect(cloudApi.discoverConnection).toHaveBeenCalledWith(
      "session-token", "connection-1", "demo-project", "checkout-api", "prod", expect.any(AbortSignal),
    );
  });

  it("disables actions for a connection returned outside the selected project", async () => {
    vi.mocked(cloudApi.listConnections).mockResolvedValue([connection("other-project")]);
    render(<CloudConnectionsRoute />);
    await act(async () => { vi.advanceTimersByTime(250); await Promise.resolve(); });
    expect(screen.getByText("other-project provider")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: /validate/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /discover/i })).toBeDisabled();
  });
});
