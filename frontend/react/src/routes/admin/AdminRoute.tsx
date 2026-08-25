import { useEffect, useState } from "react";
import { useRouteRuntime, type AdminUserForm } from "../../app/routeRuntime";
import "./AdminRoute.css";

type SettingsView = "overview" | "access" | "capacity" | "security";
type AccessTask = "none" | "create" | "edit" | "reset";

export default function AdminRoute() {
  const { admin, session } = useRouteRuntime();
  const [view, setView] = useState<SettingsView>("overview");
  const [task, setTask] = useState<AccessTask>("none");
  const [capacity, setCapacity] = useState<{ rows: any[]; loading: boolean; error: string }>({ rows: [], loading: false, error: "" });
  const [capacityForm, setCapacityForm] = useState({ username: "", resource_names: "", weekly_hours: "20", timezone: "UTC", work_start: "09:00", work_end: "17:00", active: true });
  const roles = admin.roles.length ? admin.roles : [{ id: 1, name: "Administrator" }];
  const activeUsers = admin.users.filter((user) => user.is_active).length;
  const field = (label: string, name: keyof AdminUserForm, mode: "create" | "edit", type = "text") => {
    const form = mode === "create" ? admin.createForm : admin.editForm;
    const update = mode === "create" ? admin.updateCreate : admin.updateEdit;
    return <label>{label}<input type={type} value={String(form[name] ?? "")} onChange={(event) => update(name, event.target.value)} /></label>;
  };
  const chooseUser = (row: (typeof admin.users)[number], next: AccessTask) => { admin.selectUser(row); setTask(next); };
  const headers = { Authorization: `Bearer ${session.accessToken}`, "Content-Type": "application/json" };
  async function loadCapacity() {
    setCapacity((current) => ({ ...current, loading: true, error: "" }));
    try {
      let response: Response | null = null;
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          response = await fetch("/api-gateway/approval/capacity", { headers });
          if (response.ok || ![404, 408, 425, 429, 502, 503, 504].includes(response.status)) break;
        } catch (error) {
          if (attempt === 2) throw error;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 600 * (2 ** attempt)));
      }
      if (!response?.ok) throw new Error(`Reviewer capacity is temporarily unavailable${response ? ` (HTTP ${response.status})` : ""}. Retry after the services finish starting.`);
      const payload = await response.json();
      const data = payload?.data && typeof payload.data === "object" ? payload.data : payload;
      setCapacity({ rows: Array.isArray(data?.rows) ? data.rows : [], loading: false, error: "" });
    } catch (error) { setCapacity((current) => ({ ...current, loading: false, error: String((error as Error).message || error) })); }
  }
  useEffect(() => { if (view === "capacity" && session.accessToken) void loadCapacity(); }, [view, session.accessToken]);
  async function saveCapacity(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const username = capacityForm.username.trim();
    if (!username) return;
    setCapacity((current) => ({ ...current, loading: true, error: "" }));
    try {
      const body = { ...capacityForm, username, weekly_hours: Number(capacityForm.weekly_hours), resource_names: capacityForm.resource_names.split(",").map((value) => value.trim()).filter(Boolean), working_days: [0, 1, 2, 3, 4] };
      const response = await fetch(`/api-gateway/approval/capacity/${encodeURIComponent(username)}`, { method: "PUT", headers, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(`Capacity update returned HTTP ${response.status}`);
      await loadCapacity();
    } catch (error) { setCapacity((current) => ({ ...current, loading: false, error: String((error as Error).message || error) })); }
  }

  return <section className="grid single-col platform-settings">
    <article className="panel settings-hero"><div><span className="discovery-eyebrow">Administration</span><h2>Platform Settings</h2><p>Manage people, permissions, and authentication from one protected workspace.</p></div><span className="workflow-pill workflow-pill-active">Administrator</span></article>
    <nav className="settings-tabs" aria-label="Platform settings sections">{([ ["overview", "Overview"], ["access", "Users & access"], ["capacity", "Reviewer capacity"], ["security", "Security"] ] as const).map(([id, label]) => <button type="button" key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>{label}</button>)}</nav>

    {view === "capacity" ? <section className="approval-capacity-layout"><article className="panel"><div className="panel-head"><div><h3>Reviewer capacity</h3><p>Tenant-scoped availability used for assignment planning.</p></div><button className="button-secondary" type="button" onClick={() => void loadCapacity()} disabled={capacity.loading}>{capacity.loading ? "Refreshing…" : "Refresh"}</button></div>{capacity.error ? <p className="error" role="alert">{capacity.error}</p> : null}<div className="capacity-card-grid">{capacity.rows.map((row) => <article className="capacity-card" key={row.id || row.username}><div><strong>{row.username}</strong><span className={`pill ${row.active ? "status-active" : "status-disabled"}`}>{row.active ? "Active" : "Inactive"}</span></div><p>{(row.resource_names || []).join(", ") || "No service coverage recorded"}</p><small>{row.allocated_hours || 0}h allocated · {row.remaining_hours || 0}h remaining of {row.weekly_hours || 0}h</small><small>{row.work_start}–{row.work_end} · {row.timezone}</small></article>)}{!capacity.rows.length && !capacity.loading ? <p className="empty-state">No reviewer capacity is configured for this tenant.</p> : null}</div></article><article className="panel"><h3>Add or update capacity</h3><form className="form capacity-form" onSubmit={saveCapacity}><label>Reviewer username<input required value={capacityForm.username} onChange={(event) => setCapacityForm({ ...capacityForm, username: event.target.value })} /></label><label>Services and skills<input required value={capacityForm.resource_names} onChange={(event) => setCapacityForm({ ...capacityForm, resource_names: event.target.value })} placeholder="payments, kubernetes" /><small>Comma-separated tenant-local service coverage.</small></label><label>Weekly hours<input required type="number" min="1" max="168" value={capacityForm.weekly_hours} onChange={(event) => setCapacityForm({ ...capacityForm, weekly_hours: event.target.value })} /></label><label>Timezone<input required value={capacityForm.timezone} onChange={(event) => setCapacityForm({ ...capacityForm, timezone: event.target.value })} /></label><div className="field-grid"><label>Work starts<input type="time" value={capacityForm.work_start} onChange={(event) => setCapacityForm({ ...capacityForm, work_start: event.target.value })} /></label><label>Work ends<input type="time" value={capacityForm.work_end} onChange={(event) => setCapacityForm({ ...capacityForm, work_end: event.target.value })} /></label></div><label className="checkbox-row"><input type="checkbox" checked={capacityForm.active} onChange={(event) => setCapacityForm({ ...capacityForm, active: event.target.checked })} />Available for assignment</label><button className="button-primary" disabled={capacity.loading}>Save capacity</button></form></article></section> : null}

    {view === "overview" ? <><section className="control-plane-status-grid"><article><span>Administrator</span><strong>{admin.sessionUser?.username || "Unknown"}</strong><p>{admin.sessionUser?.role_name || "Role unavailable"}</p></article><article><span>Active users</span><strong>{activeUsers}/{admin.users.length}</strong><p>Accounts permitted to sign in.</p></article><article><span>Access profiles</span><strong>{roles.length}</strong><p>Available role-based policies.</p></article><article><span>Authentication</span><strong>Protected</strong><p>Role-gated administrative actions.</p></article></section><article className="panel settings-actions"><button type="button" onClick={() => setView("access")}><strong>Users and roles</strong><span>Onboard users, change access, or reset credentials.</span><b>Manage access →</b></button><button type="button" onClick={() => setView("security")}><strong>Authentication controls</strong><span>Review SSO, session, secret, and audit boundaries.</span><b>Review security →</b></button></article></> : null}

    {view === "access" ? <article className="panel access-workspace"><div className="panel-head"><div><h3>Users and access</h3><p>Select an account action only when needed; forms stay out of the way.</p></div><div className="settings-toolbar"><button className="button-primary" type="button" onClick={() => setTask("create")}>New user</button><button className="button-secondary" type="button" onClick={admin.refresh} disabled={!admin.authenticated || admin.loading}>{admin.loading ? "Refreshing…" : "Refresh"}</button></div></div>{admin.error ? <p className="error">{admin.error}</p> : null}<div className="contained-table settings-users-table"><table><thead><tr><th>User</th><th>Email</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead><tbody>{admin.users.map((row, index) => <tr key={row.id || index}><td><strong>{row.username || "-"}</strong><small className="table-secondary">{row.first_name} {row.last_name}</small></td><td>{row.email || "-"}</td><td>{row.role_name || row.role_id || "-"}</td><td><span className={`workflow-pill ${row.is_active ? "workflow-pill-active" : "workflow-pill-idle"}`}>{row.status || "unknown"}</span></td><td><div className="row-actions"><button type="button" className="button-secondary" onClick={() => chooseUser(row, "edit")}>Edit</button><button type="button" className="button-secondary" onClick={() => chooseUser(row, "reset")}>Reset</button></div></td></tr>)}</tbody></table></div>
      {task !== "none" ? <section className="settings-task-drawer"><header><div><span className="discovery-eyebrow">Account task</span><h3>{task === "create" ? "Create a user" : task === "edit" ? `Edit ${admin.editForm.username}` : `Reset ${admin.editForm.username}'s password`}</h3></div><button type="button" className="button-secondary" onClick={() => setTask("none")}>Close</button></header>
        {task === "create" ? <form className="form settings-inline-form" onSubmit={admin.create}>{field("Username", "username", "create")}{field("Work email", "email", "create")}{field("First name", "first_name", "create")}{field("Last name", "last_name", "create")}{field("Temporary password", "password", "create", "password")}<label>Role<select value={admin.createForm.role_id} onChange={(event) => admin.updateCreate("role_id", Number(event.target.value))}>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label><button className="button-primary" disabled={!admin.authenticated || admin.loading}>Create account</button></form> : null}
        {task === "edit" ? <form className="form settings-inline-form" onSubmit={admin.update}><label>Username<input value={admin.editForm.username} readOnly /></label>{field("Email", "email", "edit")}<label>Role<select value={admin.editForm.role_id} onChange={(event) => admin.updateEdit("role_id", Number(event.target.value))}>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label><label>Status<select value={admin.editForm.status} onChange={(event) => admin.updateEdit("status", event.target.value)}>{["active", "inactive", "suspended"].map((value) => <option key={value}>{value}</option>)}</select></label><button className="button-primary" disabled={!admin.editForm.id || admin.loading}>Save changes</button></form> : null}
        {task === "reset" ? <form className="form settings-inline-form" onSubmit={admin.reset}><label>Selected user<input value={admin.editForm.username || admin.resetUserId || ""} readOnly /></label><label>New temporary password<input type="password" value={admin.resetPassword} onChange={(event) => admin.setResetPassword(event.target.value)} /></label><button className="button-primary" disabled={!admin.resetUserId || !admin.resetPassword.trim() || admin.loading}>Reset password</button></form> : null}
      </section> : null}</article> : null}

    {view === "security" ? <article className="panel security-guidance"><div><span>01</span><section><strong>Use SSO in production</strong><p>Local passwords are intended only for local development and demonstrations.</p></section><b>Identity</b></div><div><span>02</span><section><strong>Apply least privilege</strong><p>Operators investigate; engineers approve; administrators manage access.</p></section><b>Authorization</b></div><div><span>03</span><section><strong>Keep secrets external</strong><p>Save only references to credentials held in an enterprise secret manager.</p></section><b>Secrets</b></div><div><span>04</span><section><strong>Audit privileged changes</strong><p>Retain actor, time, target, and outcome for every privileged action.</p></section><b>Governance</b></div></article> : null}
  </section>;
}
