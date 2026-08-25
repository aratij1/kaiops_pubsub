// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RouteRuntimeProvider, type RouteRuntime } from "../../app/routeRuntime";
import KnowledgeRoute from "./KnowledgeRoute";

/**
 * Regression coverage for the "Stop one alert" / "Purge this queue" /
 * per-job rerun-remove / "Purge all ready jobs" confirmation fields all
 * sharing a single queueManager.reason/confirmation state pair. Typing
 * into one panel's confirmation input previously overwrote what any other
 * panel would submit, so e.g. preparing a "Stop selected alert" request
 * and then touching the per-queue purge field silently invalidated the
 * stop confirmation (and vice versa).
 */

const baseRuntime: RouteRuntime = {
  session: { accessToken: "test-token" },
  dashboard: {} as any,
  copilot: {} as any,
  closed: {} as any,
  agentFlow: {} as any,
  safety: {} as any,
  incidents: {} as any,
  alerts: {} as any,
  executive: {} as any,
  approvals: {} as any,
  admin: {} as any,
  knowledge: {
    actual: { rows: [], published: [], consumed: [] },
    configuredRows: [],
    routing: null,
    primaryTopic: "raw-alerts",
    application: "KaiMS",
    refresh: () => {},
  },
};

const queueRow = {
  name: "queue.raw-alerts",
  stage: "raw-alerts",
  consumer_service: "alert-intelligence",
  ready: 3,
  in_flight: 0,
  consumers: 1,
  state: "running",
  dead_letter: false,
};

const sampleMessage = {
  alert_id: "alert-123",
  job_id: "job-789",
  name: "PaymentLatencyHigh",
  service: "payments",
  severity: "critical",
  incident_id: "incident-456",
  payload_bytes: 512,
};

function mockFetchJson(body: unknown, ok = true) {
  return {
    ok,
    status: ok ? 200 : 422,
    json: async () => body,
  } as Response;
}

describe("KnowledgeRoute pipeline queue manager", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async (url: string) => {
      const path = String(url).replace(/^\/api-gateway/, "");
      if (path === "/knowledge-development/model/providers/status" || path === "/model/providers/status") {
        return mockFetchJson({ data: { providers: {} } });
      }
      if (path.endsWith("/operations/queues")) {
        return mockFetchJson({ data: { queues: [queueRow], summary: { queues: 1, ready: 3, in_flight: 0, dead_letter: 0 } } });
      }
      if (path.endsWith("/sample")) {
        return mockFetchJson({ data: { messages: [sampleMessage] } });
      }
      if (path.endsWith("/cancel-alert") || path.endsWith("/messages") || path.endsWith("/ready-messages") || /\/jobs\//.test(path)) {
        return mockFetchJson({ data: { status: "ok" } });
      }
      return mockFetchJson({ data: {} });
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    cleanup();
  });

  async function openQueuesTab() {
    render(
      <RouteRuntimeProvider value={baseRuntime}>
        <KnowledgeRoute />
      </RouteRuntimeProvider>,
    );
    await screen.findByRole("heading", { name: "Operational intelligence" });
    await userEvent.click(screen.getByRole("tab", { name: "Pipeline queues" }));
    await screen.findByRole("heading", { name: "Pipeline Queue Manager" });
    await userEvent.click(await screen.findByRole("button", { name: "Inspect" }));
    await screen.findByRole("heading", { name: "raw-alerts" });
  }

  it("keeps the 'Stop selected alert' confirmation independent from the 'Purge this queue' confirmation", async () => {
    await openQueuesTab();

    await userEvent.click(screen.getByRole("button", { name: "Prepare stop" }));

    const dangerZone = screen.getByText("Stop one alert").closest("section") as HTMLElement;
    const stopConfirmation = within(dangerZone).getByPlaceholderText("STOP alert-id");
    await userEvent.type(stopConfirmation, `STOP ${sampleMessage.alert_id}`);

    const stopButton = within(dangerZone).getByRole("button", { name: "Stop selected alert" });
    const purgeQueueButton = within(dangerZone).getByRole("button", { name: "Purge this queue" });

    // The reason field is required too (matching the backend's len(reason) < 8
    // rejection) -- fill it before asserting the button actually enables.
    const stopReason = within(dangerZone).getAllByRole("textbox")[0];
    await userEvent.type(stopReason, "operator requested cancellation");

    expect(stopButton).toBeEnabled();
    // Typing into the purge-queue section's own confirmation field must not
    // touch the stop-alert confirmation or re-disable the stop button --
    // this is exactly the bug: both used to read/write the same state.
    const purgeConfirmation = within(dangerZone).getByPlaceholderText(`PURGE ${queueRow.name}`);
    await userEvent.type(purgeConfirmation, "not the right phrase");

    expect(stopButton).toBeEnabled();
    expect(purgeQueueButton).toBeDisabled();
  });

  it("keeps the per-job rerun/remove confirmation independent from the alert-stop and queue-purge confirmations", async () => {
    await openQueuesTab();

    // Prime the alert-stop confirmation first.
    await userEvent.click(screen.getByRole("button", { name: "Prepare stop" }));
    const dangerZone = screen.getByText("Stop one alert").closest("section") as HTMLElement;
    const stopConfirmation = within(dangerZone).getByPlaceholderText("STOP alert-id");
    await userEvent.type(stopConfirmation, `STOP ${sampleMessage.alert_id}`);

    // Now prepare a per-job rerun and fill its own confirmation/reason.
    await userEvent.click(screen.getByRole("button", { name: "Prepare rerun" }));
    const jobConfirmation = await screen.findByLabelText("Exact confirmation");
    await userEvent.type(jobConfirmation, "wrong value");
    const rerunButton = screen.getByRole("button", { name: "Rerun job" });
    expect(rerunButton).toBeDisabled();

    // The earlier alert-stop confirmation must be untouched by the above.
    expect(stopConfirmation).toHaveValue(`STOP ${sampleMessage.alert_id}`);
  });

  it("keeps the emergency 'Purge all ready jobs' confirmation independent from the per-queue purge confirmation", async () => {
    await openQueuesTab();

    const queueConfirmation = screen.getByPlaceholderText(`PURGE ${queueRow.name}`);
    await userEvent.type(queueConfirmation, `PURGE ${queueRow.name}`);

    await userEvent.click(screen.getByText("Emergency: purge all ready pipeline jobs"));
    const purgeAllConfirmation = screen.getByPlaceholderText("PURGE ALL READY JOBS");
    await userEvent.type(purgeAllConfirmation, "PURGE ALL READY JOBS");

    // Filling the emergency confirmation must not disturb the per-queue one.
    expect(queueConfirmation).toHaveValue(`PURGE ${queueRow.name}`);

    const purgeAllButton = screen.getByRole("button", { name: "Purge all ready jobs" });
    // The reason field also has its own minimum length (backend requires
    // len(reason) >= 12) -- it should still gate the button independently.
    expect(purgeAllButton).toBeDisabled();
  });
});
