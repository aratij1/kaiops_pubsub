// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ContextEnrichmentPanel from "./ContextEnrichmentPanel";

const { fetchJson } = vi.hoisted(() => ({ fetchJson: vi.fn() }));

vi.mock("../../services/routeApi", () => ({ routeJson: fetchJson }));
vi.mock("../../utils/presentation", () => ({ formatUtcTimestamp: (value: string) => value }));

describe("ContextEnrichmentPanel polling", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("explains an expired bound trace before assignment synchronization failure", async () => {
    fetchJson.mockResolvedValue({
      schema_version: "kaiops.operations-state.v1",
      lifecycle_state: "WAITING_FOR_HUMAN",
      context: { evidence_ids: [] },
      requirements: [{
        requirement_id: "trace-gap", rca_version: 4, category: "traces",
        question: "Collect traces evidence for this incident.", status: "human_requested",
        latest_job: { connector_id: "discovery-mcp", status: "dead_letter", last_error: "TRACE_NOT_FOUND_OR_EXPIRED" },
        active_human_request: { request_id: "human-trace", expected_responder: "owner@example.com", status: "pending", assignment_failure_reason: "JIRA_SYNC_FAILED" },
      }],
      requirement_history: [],
    });

    render(<ContextEnrichmentPanel
      incidentId="incident-1" accessToken="token" declaredGaps={[{ category: "traces" }]}
      onIncidentRefresh={vi.fn().mockResolvedValue(undefined)}
    />);

    expect(await screen.findByText(/bound trace is no longer available in Jaeger/)).toBeInTheDocument();
    expect(screen.queryByText("Human evidence assignment needs attention.")).not.toBeInTheDocument();
  });

  it("does not restart polling when the parent refresh callback changes", async () => {
    vi.useFakeTimers();
    fetchJson.mockResolvedValue({
      schema_version: "kaiops.operations-state.v1",
      lifecycle_state: "DETECTED",
      context: { evidence_ids: [] },
      requirements: [],
      requirement_history: [],
    });

    const props = {
      incidentId: "incident-1",
      accessToken: "token",
      declaredGaps: [],
      onIncidentRefresh: vi.fn().mockResolvedValue(undefined),
    };
    const view = render(<ContextEnrichmentPanel {...props} />);

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(fetchJson).toHaveBeenCalledTimes(1);

    view.rerender(<ContextEnrichmentPanel {...props} onIncidentRefresh={vi.fn().mockResolvedValue(undefined)} />);
    await act(async () => { await Promise.resolve(); });

    expect(fetchJson).toHaveBeenCalledTimes(1);
  });

  it("shows an empty approved corpus before an obsolete assignment failure", async () => {
    vi.useFakeTimers();
    fetchJson.mockResolvedValue({
      schema_version: "kaiops.operations-state.v1",
      lifecycle_state: "COLLECTION_BLOCKED",
      context: { evidence_ids: [] },
      requirements: [{
        requirement_id: "requirement-1", category: "runbook", question: "Find an approved runbook.", status: "blocked",
        latest_job: { connector_id: "vector-db", status: "dead_letter", last_error: "NO_MATCHING_APPROVED_EVIDENCE" },
        active_human_request: { request_id: "request-1", status: "assignment_blocked", assignment_failure_reason: "NO_AUTHORIZED_RESPONDER" },
      }],
      requirement_history: [],
    });

    const view = render(<ContextEnrichmentPanel
      incidentId="incident-1" accessToken="token" declaredGaps={[{ category: "runbook" }]}
      onIncidentRefresh={vi.fn().mockResolvedValue(undefined)}
    />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    expect(screen.getByText(/No approved runbook matched this incident/)).toBeInTheDocument();
    expect(screen.queryByText(/No authorized responder could be resolved/)).not.toBeInTheDocument();
    view.unmount();
  });

  it("opens the active response form with requirement context and a verified source suggestion", async () => {
    fetchJson.mockResolvedValue({
      schema_version: "kaiops.operations-state.v1",
      lifecycle_state: "WAITING_FOR_HUMAN",
      context: { evidence_ids: [] },
      requirements: [{
        requirement_id: "trace-gap", category: "traces",
        question: "Provide the incident-window trace that shows the slow dependency.",
        reason: "The metric confirms latency but not its cause.",
        suggested_source_reference: "jaeger://trace/verified-trace-id",
        status: "human_requested",
        active_human_request: { request_id: "request-1", status: "pending", expected_responder: "owner@example.com" },
      }],
      requirement_history: [],
    });
    const props = {
      incidentId: "incident-1", accessToken: "token",
      declaredGaps: [{ category: "traces", reason: "Causal trace required." }],
      proposedRcaDraft: "A downstream call may explain the latency.",
      onIncidentRefresh: vi.fn().mockResolvedValue(undefined),
    };
    const view = render(<ContextEnrichmentPanel {...props} reviewRequestToken={0} />);
    expect(await screen.findByText("What KaiMS needs to establish")).toBeInTheDocument();
    expect(screen.getAllByText(/Provide the incident-window trace/).length).toBeGreaterThan(0);

    view.rerender(<ContextEnrichmentPanel {...props} reviewRequestToken={1} />);

    expect((await screen.findByLabelText("Response for traces") as HTMLTextAreaElement).value).toContain("Evidence requirement: Provide the incident-window trace");
    expect((screen.getByLabelText("Response for traces") as HTMLTextAreaElement).value).toContain("AI hypothesis to verify or correct");
    expect(screen.getByLabelText("Source reference for traces")).toHaveValue("jaeger://trace/verified-trace-id");
  });

  it("allows direct evidence input when automated assignment is blocked", async () => {
    const refresh = vi.fn().mockResolvedValue(undefined);
    fetchJson.mockResolvedValueOnce({
      schema_version: "kaiops.operations-state.v1",
      lifecycle_state: "COLLECTION_BLOCKED",
      context: { evidence_ids: [] },
      requirements: [{
        requirement_id: "runbook-gap", category: "runbook",
        question: "Provide an approved incident runbook.",
        reason: "A governed recovery procedure is required.",
        suggested_source_reference: "runbook://payments/recovery/v3",
        status: "blocked",
        latest_job: { connector_id: "vector-db", status: "dead_letter", last_error: "NO_MATCHING_APPROVED_EVIDENCE" },
        active_human_request: { request_id: "request-1", status: "assignment_blocked" },
      }],
      requirement_history: [],
    }).mockResolvedValueOnce({
      schema_version: "kaiops.operations-state.v1", lifecycle_state: "INVESTIGATING",
      context: { evidence_ids: ["HUMAN-1"] }, requirements: [], requirement_history: [],
    });

    render(<ContextEnrichmentPanel
      incidentId="incident-1" accessToken="token" declaredGaps={[{ category: "runbook" }]}
      proposedRcaDraft="Payments dependency failed." onIncidentRefresh={refresh}
    />);

    const response = await screen.findByLabelText("Response for runbook");
    expect((response as HTMLTextAreaElement).value).toContain("Evidence requirement: Provide an approved incident runbook.");
    expect(screen.getByLabelText("Source reference for runbook")).toHaveValue("runbook://payments/recovery/v3");
    fireEvent.change(response, { target: { value: "Runbook v3 was verified for the affected payments deployment." } });
    fireEvent.click(screen.getByRole("button", { name: "Submit reviewed evidence and rerun RCA" }));

    await waitFor(() => expect(fetchJson).toHaveBeenCalledWith(
      "/api-gateway/incidents/incident-1/context-gaps/runbook-gap/responses",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          response: "Runbook v3 was verified for the affected payments deployment.",
          source_reference: "runbook://payments/recovery/v3",
        }),
      }),
    ));
  });

  it("offers minimum user input while automated MCP and RAG discovery is running", async () => {
    fetchJson.mockResolvedValue({
      schema_version: "kaiops.operations-state.v1",
      lifecycle_state: "COLLECTING",
      context: { evidence_ids: [] },
      requirements: [{
        requirement_id: "topology-gap", category: "topology",
        question: "Identify affected dependencies.", status: "identified",
      }],
      requirement_history: [],
    });

    render(<ContextEnrichmentPanel
      incidentId="incident-1" accessToken="token" declaredGaps={[{ category: "topology" }]}
      onIncidentRefresh={vi.fn().mockResolvedValue(undefined)}
    />);

    expect(await screen.findByText(/searching the available MCP and governed knowledge sources/)).toBeInTheDocument();
    expect(screen.getByLabelText("Response for topology")).toBeInTheDocument();
    expect(screen.getByLabelText("Source reference for topology")).toBeInTheDocument();
  });
});
