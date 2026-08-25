import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { useRouteRuntime } from "../../app/routeRuntime";
import { ConfirmationDialog } from "../../components/design-system";
import {
  applicationDetailsQueryOptions,
  applicationKeys,
  applicationsQueryOptions,
  deleteApplication,
  suppressObservedApplication,
  updateApplication,
} from "../../services/applications";
import type {
  Application,
  ApplicationUpdate,
} from "../../schemas/applications";

const editableFields = [
  "name",
  "owner_team",
  "owner_email",
  "namespace",
  "region",
  "technology",
  "metrics_endpoint",
] as const;

function updateInput(row: Application): ApplicationUpdate {
  const payload =
    row.payload && typeof row.payload === "object"
      ? (row.payload as Record<string, unknown>)
      : {};
  const labels =
    payload.labels && typeof payload.labels === "object"
      ? (payload.labels as Record<string, string>)
      : {};
  const environment = ["dev", "staging", "prod"].includes(
    String(row.environment),
  )
    ? (row.environment as "dev" | "staging" | "prod")
    : "prod";
  return {
    tenant_id: String(row.tenant_id || "default"),
    name: row.name,
    owner_team: String(row.owner_team || "platform-ops"),
    owner_email: row.owner_email || null,
    environment,
    namespace: String(row.namespace || "default"),
    region: String(row.region || "us-east-1"),
    technology: String(row.technology || "unknown"),
    metrics_endpoint: String(
      row.metrics_endpoint || "http://api-gateway:8000/metrics",
    ),
    monitoring_platform: String(row.monitoring_platform || "prometheus"),
    labels,
    status: String(row.status || "registered"),
  };
}

type DetailRow = Record<string, unknown>;
const nested = (row: DetailRow, key: string) =>
  row[key] && typeof row[key] === "object" ? (row[key] as DetailRow) : {};
const dateTime = (value: unknown) =>
  value ? `${new Date(String(value)).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST` : "-";
const check = (value: unknown) => (
  <span className={`pill ${value ? "status-open" : "status-failed"}`}>
    {value ? "Yes" : "No"}
  </span>
);

function HistoryTable({ rows }: { rows: DetailRow[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Event</th>
          <th>Status</th>
          <th>Actor</th>
          <th>Agent</th>
          <th>Decision</th>
          <th>Duration</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={String(row.id || index)}>
            <td>{dateTime(row.created_at)}</td>
            <td>
              <strong>{String(row.event_type || "-")}</strong>
            </td>
            <td>
              <span
                className={`pill status-${String(row.status || "unknown").toLowerCase()}`}
              >
                {String(row.status || "-")}
              </span>
            </td>
            <td>{String(row.actor || "-")}</td>
            <td>{String(row.agent || "-")}</td>
            <td>{String(row.decision || "-")}</td>
            <td>
              {row.execution_time_ms == null
                ? "-"
                : `${Number(row.execution_time_ms).toFixed(2)} ms`}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ValidationTable({ rows }: { rows: DetailRow[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Status</th>
          <th>Target up</th>
          <th>Metrics</th>
          <th>Alerts</th>
          <th>Rules</th>
          <th>Discovery</th>
          <th>Dashboard</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => {
          const payload = nested(row, "payload");
          return (
            <tr key={String(row.id || index)}>
              <td>{dateTime(row.created_at)}</td>
              <td>
                <span
                  className={`pill status-${String(payload.status || "validated").toLowerCase()}`}
                >
                  {String(payload.status || "Validated")}
                </span>
              </td>
              <td>{check(row.target_up)}</td>
              <td>{check(row.metrics_available)}</td>
              <td>{check(row.alerts_loaded)}</td>
              <td>{check(row.recording_rules_loaded)}</td>
              <td>{check(row.service_discovery_ok)}</td>
              <td>{check(row.dashboard_ready)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function DashboardTable({ rows }: { rows: DetailRow[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Title</th>
          <th>UID</th>
          <th>Status</th>
          <th>Panels</th>
          <th>Updated</th>
          <th>Link</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => {
          const payload = nested(row, "payload");
          const dashboard = nested(payload, "dashboard");
          const panels = Array.isArray(dashboard.panels)
            ? dashboard.panels.length
            : 0;
          return (
            <tr key={String(row.id || index)}>
              <td>
                <strong>{String(row.title || "-")}</strong>
              </td>
              <td>
                <code>{String(row.dashboard_uid || "-")}</code>
              </td>
              <td>
                <span
                  className={`pill status-${String(payload.status || "unknown").toLowerCase()}`}
                >
                  {String(payload.status || "-")}
                </span>
              </td>
              <td>{panels}</td>
              <td>{dateTime(row.updated_at || payload.created_at)}</td>
              <td>
                {row.url ? (
                  <a
                    className="button-secondary"
                    href={String(row.url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open dashboard
                  </a>
                ) : (
                  "-"
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

const onboardingSteps = [
  {
    status: "registered",
    event: "application.onboard.requested",
    label: "Registration",
    detail: "Application profile accepted",
  },
  {
    status: "discovered",
    event: "application.discovery.completed",
    label: "Discovery",
    detail: "Resources and code signals discovered",
  },
  {
    status: "metrics_validated",
    event: "application.metrics.validated",
    label: "Metrics",
    detail: "Metrics endpoint and exporter checked",
  },
  {
    status: "rules_generated",
    event: "application.rules.generated",
    label: "Rules",
    detail: "Alert and recording rules generated",
  },
  {
    status: "prometheus_updated",
    event: "application.prometheus.updated",
    label: "Prometheus",
    detail: "Scrape configuration and rules applied",
  },
  {
    status: "validated",
    event: "application.validation.completed",
    label: "Validation",
    detail: "Targets, rules, and discovery validated",
  },
  {
    status: "dashboard_created",
    event: "application.dashboard.created",
    label: "Dashboard",
    detail: "Operational dashboard generated",
  },
] as const;

function OnboardingPipeline({
  application,
  history,
}: {
  application: Application;
  history: DetailRow[];
}) {
  const currentIndex = onboardingSteps.findIndex(
    (step) => step.status === String(application.status || "registered"),
  );
  const failed = String(application.status || "").toLowerCase() === "failed";
  const evidence = new Map(
    history.map((row) => [String(row.event_type || ""), row]),
  );
  const firstIncomplete = onboardingSteps.findIndex(
    (step, index) => !evidence.has(step.event) && index > currentIndex,
  );
  return (
    <section className="project-stepper-panel">
      <div className="panel-head">
        <div>
          <h3>Onboarding Pipeline</h3>
          <p>
            Every stage required to make this project observable and
            operational.
          </p>
        </div>
        <span
          className={`pill status-${String(application.status || "registered").toLowerCase()}`}
        >
          {String(application.status || "registered").replaceAll("_", " ")}
        </span>
      </div>
      <ol className="execution-stepper">
        {onboardingSteps.map((step, index) => {
          const event = evidence.get(step.event);
          const complete = Boolean(event) || (!failed && currentIndex >= index);
          const current =
            !complete &&
            (firstIncomplete === index ||
              (failed && index === Math.max(0, currentIndex + 1)));
          return (
            <li
              key={step.status}
              className={
                complete
                  ? "is-complete"
                  : current
                    ? failed
                      ? "is-failed"
                      : "is-current"
                    : ""
              }
            >
              <span>{complete ? "✓" : index + 1}</span>
              <div>
                <strong>{step.label}</strong>
                <small>
                  {complete
                    ? `Completed${event?.created_at ? ` · ${dateTime(event.created_at)}` : ""}`
                    : current
                      ? failed
                        ? "Failed"
                        : "In progress"
                      : "Pending"}
                </small>
                <small>{step.detail}</small>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default function ApplicationsRoute() {
  const { session, dashboard, copilot } = useRouteRuntime();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const detailRef = useRef<HTMLElement>(null);
  const legacyKnowledgeWorkspace =
    new URLSearchParams(location.search).get("workspace") === "knowledge";
  const applications = useQuery(applicationsQueryOptions(session.accessToken));
  const [selectedId, setSelectedId] = useState("");
  const [editing, setEditing] = useState(false);
  const [checkedIds, setCheckedIds] = useState<Set<string>>(() => new Set());
  const [bulkOutcomes, setBulkOutcomes] = useState<
    Array<{ name: string; ok: boolean; message: string }>
  >([]);
  const [form, setForm] = useState<ApplicationUpdate | null>(null);
  const rows = useMemo(() => {
    const registered = applications.data || [];
    const names = new Set(
      registered.map((row) => String(row.name || "").toLowerCase()),
    );
    const managedScopes = new Set(["kaims", "telemetry"]);
    const observed = dashboard.observedProjects
      .filter((name) => !names.has(name.toLowerCase()))
      .map((name) => {
        const managedPlatform = managedScopes.has(name.toLowerCase());
        return {
          id: `observed:${name}`,
          name,
          status: managedPlatform ? "Managed platform" : "Observed",
          environment: managedPlatform ? "platform" : "-",
          owner_team: managedPlatform ? "KaiMS platform" : "Not registered",
          technology: managedPlatform ? "Built-in monitoring" : "Alert traffic",
          managed_platform: managedPlatform,
        };
      });
    return [...registered, ...observed];
  }, [applications.data, dashboard.observedProjects]);
  useEffect(() => {
    if (selectedId && rows.some((row) => String(row.id) === selectedId)) return;
    setSelectedId(
      String(
        rows.find((row) => !String(row.id).startsWith("observed:"))?.id || "",
      ),
    );
  }, [rows, selectedId]);
  const registeredId = selectedId.startsWith("observed:") ? "" : selectedId;
  const selectableRows = rows.filter(
    (row) => !("managed_platform" in row && row.managed_platform),
  );
  const allSelected =
    selectableRows.length > 0 &&
    selectableRows.every((row) => checkedIds.has(String(row.id)));
  const history = useQuery(
    applicationDetailsQueryOptions(
      session.accessToken,
      registeredId,
      "history",
    ),
  );
  const validations = useQuery(
    applicationDetailsQueryOptions(
      session.accessToken,
      registeredId,
      "validations",
    ),
  );
  const dashboards = useQuery(
    applicationDetailsQueryOptions(
      session.accessToken,
      registeredId,
      "dashboards",
    ),
  );
  const selected = applications.data?.find(
    (row) => String(row.id) === registeredId,
  );
  useEffect(() => {
    if (selected) setForm(updateInput(selected));
  }, [selected]);
  const refresh = () => {
    applications.refetch();
    dashboard.refreshProjects();
  };
  const inspect = (id: string) => {
    setSelectedId(id);
    setEditing(false);
    window.setTimeout(
      () =>
        detailRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        }),
      0,
    );
  };
  const saveMutation = useMutation({
    mutationFn: (input: ApplicationUpdate) =>
      updateApplication(session.accessToken, registeredId, input),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: applicationKeys.all });
      setEditing(false);
    },
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteApplication(session.accessToken, id),
    onSuccess: async () => {
      setSelectedId("");
      setEditing(false);
      await queryClient.invalidateQueries({ queryKey: applicationKeys.all });
      await dashboard.refreshProjects();
    },
  });
  const bulkDeleteMutation = useMutation({
    mutationFn: async (targets: typeof rows) => {
      const results: Array<{ name: string; ok: boolean; message: string }> = [];
      for (const row of targets) {
        const id = String(row.id);
        try {
          await (id.startsWith("observed:")
            ? suppressObservedApplication(session.accessToken, String(row.name))
            : deleteApplication(session.accessToken, id));
          results.push({
            name: String(row.name),
            ok: true,
            message: id.startsWith("observed:")
              ? "Removed from inventory; alert history preserved"
              : "Registration deleted",
          });
        } catch (error) {
          results.push({
            name: String(row.name),
            ok: false,
            message: error instanceof Error ? error.message : "Removal failed",
          });
        }
      }
      return results;
    },
    onSuccess: async (outcomes) => {
      setBulkOutcomes(outcomes);
      setCheckedIds(
        new Set(
          outcomes
            .filter((row) => !row.ok)
            .map((row) =>
              String(rows.find((item) => item.name === row.name)?.id || ""),
            )
            .filter(Boolean),
        ),
      );
      setSelectedId("");
      setEditing(false);
      await queryClient.invalidateQueries({ queryKey: applicationKeys.all });
      await dashboard.refreshProjects();
    },
  });
  const submitEdit = (event: FormEvent) => {
    event.preventDefault();
    if (form) saveMutation.mutate(form);
  };
  const remove = () => {
    if (
      !selected ||
      !window.confirm(
        `Remove ${selected.name}? This deletes its application registration and cannot be undone.`,
      )
    )
      return;
    deleteMutation.mutate(String(selected.id));
  };
  const toggleRow = (id: string) =>
    setCheckedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const toggleAll = () =>
    setCheckedIds(
      allSelected
        ? new Set()
        : new Set(selectableRows.map((row) => String(row.id))),
    );
  const bulkRemove = () => {
    const targets = rows.filter((row) => checkedIds.has(String(row.id)));
    if (!targets.length) return;
    setBulkOutcomes([]);
    bulkDeleteMutation.mutate(targets);
  };
  if (legacyKnowledgeWorkspace) return null;
  return (
    <section className="grid single-col">
      <article className="panel">
        <div className="panel-head">
          <div>
            <h2>Application Portfolio</h2>
            <p>
              Onboarded applications, managed platform services, and services
              observed in live alerts.
            </p>
          </div>
          <div className="button-row">
            {copilot.isAdministrator ? (
              <ConfirmationDialog
                trigger={
                  <button
                    className="button-danger"
                    type="button"
                    disabled={!checkedIds.size || bulkDeleteMutation.isPending}
                  >
                    {bulkDeleteMutation.isPending
                      ? "Removing..."
                      : `Remove selected (${checkedIds.size})`}
                  </button>
                }
                title={`Remove ${checkedIds.size} selected application${checkedIds.size === 1 ? "" : "s"}?`}
                description="Registered applications will be deleted. Observed services will be removed from the portfolio while historical alerts remain available for audit."
                confirmLabel="Remove applications"
                destructive
                onConfirm={bulkRemove}
              />
            ) : null}
            <button
              className="button-secondary"
              type="button"
              onClick={refresh}
              disabled={applications.isFetching}
            >
              {applications.isFetching ? "Refreshing..." : "Refresh portfolio"}
            </button>
          </div>
        </div>
        {bulkOutcomes.length ? (
          <div className="bulk-action-results" role="status">
            <strong>Bulk removal results</strong>
            <ul>
              {bulkOutcomes.map((outcome) => (
                <li
                  key={outcome.name}
                  className={outcome.ok ? "success" : "error"}
                >
                  <span>{outcome.name}</span>: {outcome.message}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {applications.error ? (
          <p className="error">{applications.error.message}</p>
        ) : null}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th className="portfolio-select-column">
                  {copilot.isAdministrator && selectableRows.length ? (
                    <input type="checkbox" aria-label="Select all removable applications" checked={allSelected} onChange={toggleAll} />
                  ) : null}
                </th>
                <th>Name</th>
                <th>Environment</th>
                <th>Owner</th>
                <th>Technology</th>
                <th>Registration</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const id = String(row.id);
                const observed = id.startsWith("observed:");
                const managed = Boolean(
                  "managed_platform" in row && row.managed_platform,
                );
                return (
                  <tr
                    key={row.id}
                    className={id === selectedId ? "row-selected" : ""}
                  >
                    <td className="portfolio-select-column">
                      {copilot.isAdministrator && !managed ? (
                        <input type="checkbox" aria-label={`Select ${row.name}`} checked={checkedIds.has(id)} onChange={() => toggleRow(id)} />
                      ) : null}
                    </td>
                    <td>
                      <strong>{row.name}</strong>
                    </td>
                    <td>{row.environment || "-"}</td>
                    <td>{row.owner_team || "-"}</td>
                    <td>{row.technology || "-"}</td>
                    <td>
                      <span
                        className={`pill ${observed && !managed ? "status-awaiting_approval" : "status-open"}`}
                      >
                        {managed
                          ? "Managed—built in"
                          : observed
                            ? "Observed—not onboarded"
                            : row.status || "Registered"}
                      </span>
                    </td>
                    <td>
                      {managed ? (
                        <span className="field-hint">
                          No onboarding required
                        </span>
                      ) : observed ? (
                        <button
                          className="button-secondary"
                          type="button"
                          onClick={() => navigate("/integrations")}
                        >
                          Onboard
                        </button>
                      ) : (
                        <button
                          className="button-secondary"
                          type="button"
                          onClick={() => inspect(id)}
                        >
                          Inspect
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!applications.isLoading && !rows.length ? (
                <tr>
                  <td colSpan={7}>
                    No applications have been registered or observed.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </article>
      {selected && form ? (
        <article className="panel" ref={detailRef}>
          <div className="panel-head">
            <div>
              <h2>{selected.name}</h2>
              <p>
                {selected.metrics_endpoint || "No metrics endpoint supplied"}
              </p>
            </div>
            {copilot.isAdministrator ? (
              <div className="button-row">
                <button
                  className="button-secondary"
                  type="button"
                  onClick={() => setEditing((value) => !value)}
                >
                  {editing ? "Cancel edit" : "Edit project"}
                </button>
                <button
                  className="button-danger"
                  type="button"
                  onClick={remove}
                  disabled={deleteMutation.isPending}
                >
                  {deleteMutation.isPending ? "Removing..." : "Remove project"}
                </button>
              </div>
            ) : null}
          </div>
          {saveMutation.error ? (
            <p className="error">{saveMutation.error.message}</p>
          ) : null}
          {deleteMutation.error ? (
            <p className="error">{deleteMutation.error.message}</p>
          ) : null}
          {editing ? (
            <form className="form" onSubmit={submitEdit}>
              <div className="filter-grid">
                {editableFields.map((name) => (
                  <label key={name}>
                    {name.replaceAll("_", " ")}
                    <input
                      type={
                        name === "owner_email"
                          ? "email"
                          : name === "metrics_endpoint"
                            ? "url"
                            : "text"
                      }
                      value={String(form[name] || "")}
                      onChange={(event) =>
                        setForm((current) =>
                          current
                            ? {
                                ...current,
                                [name]:
                                  name === "owner_email"
                                    ? event.target.value || null
                                    : event.target.value,
                              }
                            : current,
                        )
                      }
                      required={name !== "owner_email"}
                    />
                  </label>
                ))}
                <label>
                  Environment
                  <select
                    value={form.environment}
                    onChange={(event) =>
                      setForm((current) =>
                        current
                          ? {
                              ...current,
                              environment: event.target
                                .value as ApplicationUpdate["environment"],
                            }
                          : current,
                      )
                    }
                  >
                    <option value="dev">dev</option>
                    <option value="staging">staging</option>
                    <option value="prod">prod</option>
                  </select>
                </label>
              </div>
              <button
                className="button-primary"
                type="submit"
                disabled={saveMutation.isPending}
              >
                {saveMutation.isPending ? "Saving..." : "Save changes"}
              </button>
            </form>
          ) : (
            <div className="stat-grid">
              <div className="stat-card">
                <strong>Environment</strong>
                <span>{selected.environment || "-"}</span>
              </div>
              <div className="stat-card">
                <strong>Region</strong>
                <span>{selected.region || "-"}</span>
              </div>
              <div className="stat-card">
                <strong>Namespace</strong>
                <span>{selected.namespace || "-"}</span>
              </div>
              <div className="stat-card">
                <strong>Status</strong>
                <span>{selected.status || "-"}</span>
              </div>
            </div>
          )}
          <OnboardingPipeline
            application={selected}
            history={history.data || []}
          />
          <section>
            <h3>Onboarding History</h3>
            {history.error ? (
              <p className="error">{history.error.message}</p>
            ) : null}
            <div className="table-wrap">
              {history.data?.length ? (
                <HistoryTable rows={history.data} />
              ) : (
                <p className="field-hint">
                  {history.isLoading
                    ? "Loading onboarding history..."
                    : "No onboarding history available."}
                </p>
              )}
            </div>
          </section>
          <section>
            <h3>Validation Results</h3>
            {validations.error ? (
              <p className="error">{validations.error.message}</p>
            ) : null}
            <div className="table-wrap">
              {validations.data?.length ? (
                <ValidationTable rows={validations.data} />
              ) : (
                <p className="field-hint">
                  {validations.isLoading
                    ? "Loading validation results..."
                    : "No validation results available."}
                </p>
              )}
            </div>
          </section>
          <section>
            <h3>Dashboards</h3>
            {dashboards.error ? (
              <p className="error">{dashboards.error.message}</p>
            ) : null}
            <div className="table-wrap">
              {dashboards.data?.length ? (
                <DashboardTable rows={dashboards.data} />
              ) : (
                <p className="field-hint">
                  {dashboards.isLoading
                    ? "Loading dashboards..."
                    : "No dashboards available."}
                </p>
              )}
            </div>
          </section>
        </article>
      ) : null}
    </section>
  );
}
