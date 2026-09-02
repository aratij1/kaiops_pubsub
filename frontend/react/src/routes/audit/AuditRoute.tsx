import { useEffect, useState } from "react";
import { FileClock, Filter, LockKeyhole, RefreshCw, ScrollText } from "lucide-react";
import { Link } from "react-router-dom";
import { useSession } from "../../app/SessionContext";
import { durableIncidentPath } from "../../domain/incidentNavigation";
import "./AuditRoute.css";

type AuditRow = { id: number; actor: string; action: string; resource_type: string; resource_id: string; payload: Record<string, unknown>; created_at: string };
type AuditPage = { rows: AuditRow[]; count: number; page: number; page_size: number };
const PAGE_SIZE = 50;
const relatedPath = (row: AuditRow) => row.resource_type === "incident" ? durableIncidentPath({ incident_id: row.resource_id }) : row.resource_type === "approval" ? `/approvals?approval_id=${encodeURIComponent(row.resource_id)}` : null;

export default function AuditRoute() {
  const { accessToken } = useSession();
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [reload, setReload] = useState(0);
  const [state, setState] = useState<{ loading: boolean; data: AuditPage; error: string }>({ loading: true, data: { rows: [], count: 0, page: 1, page_size: PAGE_SIZE }, error: "" });
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (action.trim()) params.set("action", action.trim());
    setState((current) => ({ ...current, loading: true, error: "" }));
    fetch(`/api-gateway/audit-logs?${params}`, { headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` }, signal: controller.signal })
      .then(async (response) => { if (!response.ok) throw new Error(`Audit service returned HTTP ${response.status}`); return response.json(); })
      .then((data: AuditPage) => setState({ loading: false, data, error: "" }))
      .catch((error) => { if (!controller.signal.aborted) setState((current) => ({ ...current, loading: false, error: String(error.message || error) })); });
    return () => controller.abort();
  }, [accessToken, action, page, reload]);
  const pages = Math.max(1, Math.ceil(state.data.count / PAGE_SIZE));
  return <section className="audit-workspace">
    <header className="audit-hero"><ScrollText aria-hidden="true" /><div><span>Governance record</span><h2>Audit trail</h2><p>Tenant-scoped, immutable records returned in deterministic newest-first order.</p></div><button type="button" onClick={() => setReload((value) => value + 1)} disabled={state.loading}><RefreshCw aria-hidden="true" />Refresh</button></header>
    <section className="audit-controls"><label><Filter aria-hidden="true" />Filter by exact action<input value={action} onChange={(event) => { setPage(1); setAction(event.target.value); }} placeholder="recommendation.generated" /></label><span><LockKeyhole aria-hidden="true" />Read only</span></section>
    {state.error ? <p className="error" role="alert">{state.error}</p> : null}
    <div className="table-wrap"><table><caption className="sr-only">Immutable tenant audit history</caption><thead><tr><th>Recorded</th><th>Actor</th><th>Action</th><th>Resource</th><th>Reference</th></tr></thead><tbody>
      {state.data.rows.map((row) => { const path = relatedPath(row); return <tr key={row.id}><td>{new Date(row.created_at).toLocaleString()}</td><td>{row.actor}</td><td><code>{row.action}</code></td><td>{row.resource_type}</td><td>{path ? <Link to={path}>{row.resource_id}</Link> : <code>{row.resource_id}</code>}</td></tr>; })}
      {!state.loading && !state.data.rows.length ? <tr><td colSpan={5}><div className="table-empty-state"><FileClock aria-hidden="true" /><strong>No audit records match this scope</strong><span>Change the action filter or refresh.</span></div></td></tr> : null}
    </tbody></table></div>
    <footer className="audit-pagination"><span>{state.data.count} immutable record(s)</span><div><button type="button" disabled={page <= 1 || state.loading} onClick={() => setPage((value) => value - 1)}>Previous</button><span>{page} / {pages}</span><button type="button" disabled={page >= pages || state.loading} onClick={() => setPage((value) => value + 1)}>Next</button></div></footer>
  </section>;
}
