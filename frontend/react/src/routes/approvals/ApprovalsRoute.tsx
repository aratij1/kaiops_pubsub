import { useCallback, useEffect, useState, type FormEvent } from "react";

import { useRouteRuntimeSlice, type ApprovalForm } from "../../app/routeRuntime";
import { OperationsWorkflowNav } from "../../components/operations/OperationsWorkflowNav";

type ApprovalSection = "queue" | "capacity" | "review" | "history";
interface CapacityRow { username: string; resource_names: string[]; weekly_hours: number; allocated_hours: number; remaining_hours: number; timezone: string; working_days: number[]; work_start: string; work_end: string; active: boolean; }
interface AssignmentRow { incident_id: string; assignee: string; service: string; estimated_hours: number; status: string; assignment_reason: string; created_at?: string; }

let capacitySnapshot: { token: string; fetchedAt: number; rows: CapacityRow[]; assignments: AssignmentRow[] } = { token: "", fetchedAt: 0, rows: [], assignments: [] };
let capacityLoadPromise: Promise<{ rows: CapacityRow[]; assignments: AssignmentRow[] }> | null = null;

const unwrap = (payload: any) => payload?.data?.rows ? payload.data : payload?.data?.data || payload?.data || payload;

export default function ApprovalsRoute() {
  const approvals = useRouteRuntimeSlice("approvals");
  const session = useRouteRuntimeSlice("session");
  const [section, setSection] = useState<ApprovalSection>("queue");
  const [capacity, setCapacity] = useState<{ rows: CapacityRow[]; loading: boolean; error: string }>({ rows: [], loading: true, error: "" });
  const [assignments, setAssignments] = useState<AssignmentRow[]>([]);
  const [capacityStatus, setCapacityStatus] = useState("");
  const [capacityForm, setCapacityForm] = useState({ username: "", resource_names: "", weekly_hours: "8", timezone: "Asia/Kolkata", working_days: [0, 1, 2, 3, 4], work_start: "09:00", work_end: "17:00", active: true });
  const authHeaders = useCallback(() => ({ "Content-Type": "application/json", ...(session.accessToken ? { Authorization: `Bearer ${session.accessToken}` } : {}) }), [session.accessToken]);

  const loadCapacity = useCallback(async (forceOrEvent: boolean | unknown = false) => {
    const force = typeof forceOrEvent === "boolean" ? forceOrEvent : false;
    const token = session.accessToken || "anonymous";
    if (!force && capacitySnapshot.token === token && Date.now() - capacitySnapshot.fetchedAt < 30_000) {
      setCapacity({ rows: capacitySnapshot.rows, loading: false, error: "" });
      setAssignments(capacitySnapshot.assignments);
      return;
    }
    setCapacity((current) => ({ ...current, loading: current.rows.length === 0, error: "" }));
    try {
      if (!capacityLoadPromise) {
        capacityLoadPromise = (async () => {
          const [capacityResponse, assignmentResponse] = await Promise.all([
            fetch("/api-gateway/approval/capacity", { headers: authHeaders() }),
            fetch("/api-gateway/approval/assignments", { headers: authHeaders() }),
          ]);
          if (!capacityResponse.ok || !assignmentResponse.ok) throw new Error("Capacity service is unavailable.");
          const capacityData = unwrap(await capacityResponse.json());
          const assignmentData = unwrap(await assignmentResponse.json());
          return {
            rows: Array.isArray(capacityData?.rows) ? capacityData.rows : [],
            assignments: Array.isArray(assignmentData?.rows) ? assignmentData.rows : [],
          };
        })().finally(() => { capacityLoadPromise = null; });
      }
      const result = await capacityLoadPromise;
      capacitySnapshot = { token, fetchedAt: Date.now(), ...result };
      setCapacity({ rows: result.rows, loading: false, error: "" });
      setAssignments(result.assignments);
    } catch (error) {
      setCapacity((current) => ({ ...current, loading: false, error: String((error as Error).message || error) }));
    }
  }, [authHeaders]);

  useEffect(() => { void loadCapacity(); }, [loadCapacity]);

  async function saveCapacity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCapacityStatus("Saving capacity…");
    const payload = { ...capacityForm, weekly_hours: Number(capacityForm.weekly_hours), resource_names: capacityForm.resource_names.split(",").map((value) => value.trim()).filter(Boolean) };
    try {
      const response = await fetch(`/api-gateway/approval/capacity/${encodeURIComponent(capacityForm.username.trim())}`, { method: "PUT", headers: authHeaders(), body: JSON.stringify(payload) });
      if (!response.ok) throw new Error(`Capacity was not saved (${response.status}).`);
      setCapacityStatus("Capacity saved and available for assignment.");
      await loadCapacity(true);
    } catch (error) { setCapacityStatus(String((error as Error).message || error)); }
  }

  async function autoAssign() {
    const tickets = approvals.rows.map((row) => ({ incident_id: approvals.incidentId(row), service: String(row.service || "unknown"), severity: String(row.severity || row.risk_tier || "medium"), resource_names: [String(row.service || "")].filter(Boolean) })).filter((row) => row.incident_id);
    if (!tickets.length) { setCapacityStatus("There are no pending tickets to assign."); return; }
    setCapacityStatus("Matching tickets to current on-duty capacity…");
    try {
      const response = await fetch("/api-gateway/approval/auto-assign", { method: "POST", headers: authHeaders(), body: JSON.stringify({ tickets }) });
      if (!response.ok) throw new Error(`Auto-assignment failed (${response.status}).`);
      const result = unwrap(await response.json());
      setCapacityStatus(`${Number(result?.assigned || 0)} ticket(s) assigned. Unmatched tickets remain visible for manual routing.`);
      await loadCapacity(true);
    } catch (error) { setCapacityStatus(String((error as Error).message || error)); }
  }

  const field = (label: string, name: keyof ApprovalForm) => <label>{label}<input value={approvals.form[name]} onChange={(event) => approvals.updateForm(name, event.target.value)} /></label>;
  const selected = approvals.rows.find((row) => approvals.incidentId(row) === approvals.selectedIncidentId);

  return <section className="grid single-col approval-workspace">
    <OperationsWorkflowNav active="approvals" />
    <article className="panel approval-hero"><div><span className="eyebrow">HUMAN DECISION OPERATIONS</span><h2>Approval Workspace</h2><p>Balance responder capacity, route pending tickets, and make one evidence-backed decision at a time.</p></div><div className="approval-summary"><div><strong>{approvals.rows.length}</strong><span>Pending</span></div><div><strong>{capacity.rows.filter((row) => row.active).length}</strong><span>Available profiles</span></div><div><strong>{assignments.filter((row) => ["assigned", "in_progress"].includes(row.status)).length}</strong><span>Assigned</span></div></div></article>
    <nav className="approval-section-tabs" aria-label="Approval workspace sections">{([['queue','Queue'],['capacity','Capacity & assignment'],['review','Review & decide'],['history','Assignment history']] as const).map(([id,label]) => <button type="button" key={id} className={section === id ? "active" : ""} aria-current={section === id ? "page" : undefined} onClick={() => setSection(id)}>{label}</button>)}</nav>

    {section === "queue" ? <article className="panel"><div className="panel-head"><div><h3>Pending approval queue</h3><p>Select a ticket to review, or assign the queue using responder capacity.</p></div><button type="button" className="button-primary" onClick={() => { setSection("capacity"); void autoAssign(); }}>Auto-assign pending tickets</button></div><div className="filter-grid approval-compact-filter"><label>Filter<select value={approvals.filter} onChange={(event) => approvals.setFilter(event.target.value)}>{["all", "awaiting_approval", "critical", "high", "medium", "low"].map((value) => <option key={value}>{value}</option>)}</select></label></div><div className="approval-card-list">{approvals.rows.map((row, index) => { const incidentId=approvals.incidentId(row); const assignment=assignments.find((item) => item.incident_id===incidentId); return <button type="button" className={incidentId===approvals.selectedIncidentId ? "approval-ticket selected" : "approval-ticket"} key={incidentId || index} onClick={() => { approvals.select(row); setSection("review"); }}><span><b>{row.service || "Unknown service"}</b><small>{incidentId}</small></span><span className={`pill status-${String(row.status || "pending").toLowerCase()}`}>{row.status || "pending"}</span><span><small>Severity</small><b>{row.severity || row.risk_tier || "unknown"}</b></span><span><small>Assigned to</small><b>{assignment?.assignee || "Unassigned"}</b></span><strong>Review →</strong></button>})}{!approvals.rows.length ? <p className="empty-state">No pending approvals match this filter.</p> : null}</div></article> : null}

    {section === "capacity" ? <div className="approval-capacity-layout"><article className="panel"><div className="panel-head"><div><h3>Responder capacity</h3><p>Contribution hours are weekly. Working windows determine who is eligible right now.</p></div><button type="button" className="button-primary" onClick={autoAssign}>Run auto-assignment</button></div>{capacity.error ? <p className="error">{capacity.error}</p> : null}{capacityStatus ? <p className="status-message" aria-live="polite">{capacityStatus}</p> : null}<div className="capacity-card-grid">{capacity.rows.map((row) => <article className="capacity-card" key={row.username}><div><strong>{row.username}</strong><span className={`pill ${row.active ? "status-active" : "status-disabled"}`}>{row.active ? "Active" : "Inactive"}</span></div><p>{row.resource_names.join(", ")}</p><div className="capacity-meter"><span style={{ width: `${Math.min(100, (row.allocated_hours / Math.max(1,row.weekly_hours))*100)}%` }} /></div><small>{row.allocated_hours}h allocated · {row.remaining_hours}h remaining of {row.weekly_hours}h</small><small>{row.work_start}–{row.work_end} · {row.timezone}</small></article>)}{!capacity.rows.length && !capacity.loading ? <p>No capacity profiles yet. Add the first responder.</p> : null}</div></article><article className="panel"><h3>Publish my availability</h3><form className="form capacity-form" onSubmit={saveCapacity}><label>Resource / user name<input required value={capacityForm.username} onChange={(event)=>setCapacityForm({...capacityForm,username:event.target.value})} placeholder="ashish.singh" /></label><label>Resource skills or services<input required value={capacityForm.resource_names} onChange={(event)=>setCapacityForm({...capacityForm,resource_names:event.target.value})} placeholder="payments, kubernetes, database" /><small>Comma-separated; use “all” for general approval coverage.</small></label><label>Weekly contribution hours<input required type="number" min="1" max="168" value={capacityForm.weekly_hours} onChange={(event)=>setCapacityForm({...capacityForm,weekly_hours:event.target.value})} /></label><div className="field-grid"><label>Start<input type="time" value={capacityForm.work_start} onChange={(event)=>setCapacityForm({...capacityForm,work_start:event.target.value})} /></label><label>End<input type="time" value={capacityForm.work_end} onChange={(event)=>setCapacityForm({...capacityForm,work_end:event.target.value})} /></label></div><label>Timezone<input value={capacityForm.timezone} onChange={(event)=>setCapacityForm({...capacityForm,timezone:event.target.value})} /></label><fieldset><legend>Working days</legend><div className="weekday-picker">{["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map((day,index)=><label key={day}><input type="checkbox" checked={capacityForm.working_days.includes(index)} onChange={()=>setCapacityForm({...capacityForm,working_days:capacityForm.working_days.includes(index)?capacityForm.working_days.filter((value)=>value!==index):[...capacityForm.working_days,index].sort()})}/>{day}</label>)}</div></fieldset><label className="checkbox-row"><input type="checkbox" checked={capacityForm.active} onChange={(event)=>setCapacityForm({...capacityForm,active:event.target.checked})}/>Available for automatic assignment</label><button className="button-primary" type="submit">Save capacity</button></form></article></div> : null}

    {section === "review" ? <article className="panel approval-review"><div className="panel-head"><div><h3>Review and decide</h3><p>{selected ? `${selected.service || "Service"} · ${approvals.selectedIncidentId}` : "Choose a pending ticket from the queue."}</p></div><button type="button" className="button-secondary" onClick={()=>setSection("queue")}>Back to queue</button></div>{!selected ? <p className="empty-state">No ticket selected.</p> : <><div className="approval-review-summary"><div><small>Incident</small><strong>{approvals.selectedIncidentId}</strong></div><div><small>Recommendation</small><strong>{approvals.selectedRecommendationId || "Sync required"}</strong></div><div><small>Flow</small><strong>{approvals.selectedFlowContext || "Not available"}</strong></div></div><div className="approval-nav-actions"><button className="button-secondary" type="button" onClick={approvals.sync} disabled={approvals.contextLoading}>{approvals.contextLoading ? "Syncing…" : "Sync evidence"}</button><button className="button-secondary" type="button" onClick={()=>approvals.open(selected)}>Open incident cockpit</button><button className="button-secondary" type="button" onClick={approvals.openAgentFlow}>Agent flow</button></div>{approvals.contextError ? <p className="error">{approvals.contextError}</p> : null}<div className="approval-decision-bar"><button className="button-primary" type="button" onClick={()=>approvals.approve(selected)} disabled={!approvals.selectedRecommendationId || approvals.actionLoading}>Approve recommendation</button><button className="button-secondary" type="button" onClick={()=>approvals.toggleReject(approvals.selectedIncidentId)}>Reject with reason</button><button className="button-secondary" type="button" onClick={approvals.toggleAdvanced}>Modify plan</button></div>{approvals.inlineReject.incidentId===approvals.selectedIncidentId ? <div className="inline-decision"><label>Rejection reason<textarea rows={3} value={approvals.inlineReject.comment} onChange={(event)=>approvals.setRejectComment(approvals.selectedIncidentId,event.target.value)}/></label><button className="button-primary" type="button" onClick={()=>approvals.reject(selected)} disabled={!approvals.inlineReject.comment.trim()}>Confirm rejection</button></div> : null}{approvals.showAdvanced ? <form className="form approval-advanced" onSubmit={approvals.submit}><label>Action<select value={approvals.form.action} onChange={(event)=>approvals.updateForm("action",event.target.value)}><option value="approve">approve</option><option value="reject">reject</option><option value="modify">modify</option></select></label>{field("Incident ID","incident_id")}{field("Recommendation ID","recommendation_id")}{field("Approver","approver")}<label>Comment<textarea rows={3} value={approvals.form.comment} onChange={(event)=>approvals.updateForm("comment",event.target.value)}/></label><button className="button-primary" disabled={!approvals.ready || approvals.actionLoading}>Submit action</button></form> : null}{approvals.actionError ? <p className="error">{approvals.actionError}</p> : null}</>}</article> : null}

    {section === "history" ? <article className="panel"><div className="panel-head"><div><h3>Assignment history</h3><p>Why each ticket was assigned and how much capacity it consumed.</p></div><button className="button-secondary" type="button" onClick={loadCapacity}>Refresh</button></div><div className="table-wrap"><table><thead><tr><th>Incident</th><th>Assignee</th><th>Service</th><th>Hours</th><th>Status</th><th>Assignment reason</th></tr></thead><tbody>{assignments.map((row)=><tr key={row.incident_id}><td>{row.incident_id}</td><td>{row.assignee}</td><td>{row.service}</td><td>{row.estimated_hours}</td><td>{row.status}</td><td>{row.assignment_reason}</td></tr>)}{!assignments.length?<tr><td colSpan={6}>No assignments have been recorded.</td></tr>:null}</tbody></table></div></article> : null}
  </section>;
}
