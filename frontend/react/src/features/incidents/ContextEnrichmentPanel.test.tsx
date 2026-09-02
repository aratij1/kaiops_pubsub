// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ContextEnrichmentPanel from "./ContextEnrichmentPanel";

const { fetchJson } = vi.hoisted(() => ({ fetchJson: vi.fn() }));

vi.mock("../../services/routeApi", () => ({ routeJson: fetchJson }));
vi.mock("../../utils/presentation", () => ({ formatUtcTimestamp: (value: string) => value }));

describe("ContextEnrichmentPanel polling", () => {
  afterEach(() => {
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
    expect(await screen.findByText(/Provide the incident-window trace/)).toBeInTheDocument();

    view.rerender(<ContextEnrichmentPanel {...props} reviewRequestToken={1} />);

    expect(await screen.findByLabelText("Response for traces")).toHaveValue(expect.stringContaining("Evidence requirement: Provide the incident-window trace"));
    expect(screen.getByLabelText("Response for traces")).toHaveValue(expect.stringContaining("AI hypothesis to verify or correct"));
    expect(screen.getByLabelText("Source reference for traces")).toHaveValue("jaeger://trace/verified-trace-id");
  });
});
