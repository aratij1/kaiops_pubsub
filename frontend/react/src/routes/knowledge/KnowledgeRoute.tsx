import { useEffect, useState } from "react";
import { MessageBusTopology } from "../../appHelpers.jsx";
import { useRouteRuntime } from "../../app/routeRuntime";

type HubView = "overview" | "development" | "queues" | "activity" | "topology";

type DevelopmentConfiguration = { enabled: boolean; interval_hours: number; lookback_days: number; application_scope: string; collect_logs: boolean; collect_metrics: boolean; collect_traces: boolean; collect_tickets: boolean; collect_changes: boolean };
const defaultConfiguration: DevelopmentConfiguration = { enabled: true, interval_hours: 6, lookback_days: 30, application_scope: "all", collect_logs: true, collect_metrics: true, collect_traces: true, collect_tickets: true, collect_changes: true };

export default function KnowledgeRoute() {
  const { knowledge, session } = useRouteRuntime();
  const [view, setView] = useState<HubView>("overview");
  const [configuration, setConfiguration] = useState(defaultConfiguration);
  const [development, setDevelopment] = useState<{ loading: boolean; running: boolean; saving: boolean; error: string; report: any }>({ loading: false, running: false, saving: false, error: "", report: null });
  const [queueManager, setQueueManager] = useState<{ loading:boolean; actionLoading:boolean; error:string; result:string; rows:any[]; summary:any; selected:any; selectedAlertId:string; messages:any[]; reason:string; confirmation:string }>({ loading:false, actionLoading:false, error:"", result:"", rows:[], summary:{}, selected:null, selectedAlertId:"", messages:[], reason:"", confirmation:"" });
  const observed = knowledge.actual.rows.filter((row) => String(row.status || "").toLowerCase() === "observed").length;
  const provider = knowledge.actual.rows.find((row) => row.provider)?.provider || "Not observed";
  const request = async (path: string, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    headers.set("Authorization", `Bearer ${session.accessToken}`);
    const endpoint = path.startsWith("/operations/") ? `/api-gateway${path}` : `/api-gateway/knowledge-development${path}`;
    const response = await fetch(endpoint, { ...init, headers });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.detail?.data?.hint || payload?.detail || `HTTP ${response.status}`);
    return payload?.data || payload;
  };
  const loadDevelopment = async () => {
    setDevelopment((current) => ({ ...current, loading: true, error: "" }));
    try {
      const [config, report] = await Promise.all([request("/configuration"), request("/report")]);
      setConfiguration({ ...defaultConfiguration, ...config, application_scope: knowledge.application || "KaiMS" });
      setDevelopment((current) => ({ ...current, loading: false, report }));
    } catch (error: any) { setDevelopment((current) => ({ ...current, loading: false, error: error.message })); }
  };
  const saveConfiguration = async () => {
    setDevelopment((current) => ({ ...current, saving: true, error: "" }));
    try { setConfiguration(await request("/configuration", { method: "PUT", body: JSON.stringify({ ...configuration, application_scope: knowledge.application || "KaiMS" }) })); setDevelopment((current) => ({ ...current, saving: false })); }
    catch (error: any) { setDevelopment((current) => ({ ...current, saving: false, error: error.message })); }
  };
  const runNow = async () => {
    setDevelopment((current) => ({ ...current, running: true, error: "" }));
    try {
      const result = await request("/run", { method: "POST" });
      if (result?.status === "failed") throw new Error(result.error || "Analysis failed");
      await loadDevelopment();
      setDevelopment((current) => ({ ...current, running: false }));
    } catch (error: any) { setDevelopment((current) => ({ ...current, running: false, error: error.message })); }
  };
  useEffect(() => {
    if (view !== "development") return undefined;
    void loadDevelopment();
    const refresh = () => { if (document.visibilityState === "visible") void loadDevelopment(); };
    const timer = window.setInterval(refresh, 60000);
    document.addEventListener("visibilitychange", refresh);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", refresh); };
  }, [view, knowledge.application]);
  const loadQueues = async () => { setQueueManager((current)=>({...current,loading:true,error:""})); try { const data=await request("/operations/queues"); setQueueManager((current)=>({...current,loading:false,rows:data.queues||[],summary:data.summary||{}})); } catch(error:any){setQueueManager((current)=>({...current,loading:false,error:error.message}));} };
  const inspectQueue = async (row:any) => { setQueueManager((current)=>({...current,selected:row,messages:[],loading:true,error:"",result:"",reason:"",confirmation:""})); try { const data=await request(`/operations/queues/${encodeURIComponent(row.name)}/sample`,{method:"POST"}); setQueueManager((current)=>({...current,loading:false,messages:data.messages||[]})); } catch(error:any){setQueueManager((current)=>({...current,loading:false,error:error.message}));} };
  const queueAction = async (path:string, method:string, success:string) => { setQueueManager((current)=>({...current,actionLoading:true,error:"",result:""})); try { await request(`/operations/queues${path}`,{method,body:JSON.stringify({alert_id:queueManager.selectedAlertId,reason:queueManager.reason,confirmation:queueManager.confirmation})}); setQueueManager((current)=>({...current,actionLoading:false,result:success,messages:[],selectedAlertId:"",reason:"",confirmation:""})); await loadQueues(); } catch(error:any){setQueueManager((current)=>({...current,actionLoading:false,error:error.message}));} };
  useEffect(() => {
    if (view !== "queues") return undefined;
    void loadQueues();
    const refresh = () => { if (document.visibilityState === "visible") void loadQueues(); };
    const timer = window.setInterval(refresh, 30000);
    document.addEventListener("visibilitychange", refresh);
    return () => { window.clearInterval(timer); document.removeEventListener("visibilitychange", refresh); };
  }, [view]);

  return <section className="grid single-col ai-hub">
    <article className="panel ai-hub-hero"><div><span className="discovery-eyebrow">KaiMS intelligence control plane</span><h2>AI Hub</h2><p>Understand what the AI uses, confirm agent activity, and inspect routing only when troubleshooting.</p></div><button className="button-secondary" onClick={knowledge.refresh}>Refresh status</button></article>
    <nav className="settings-tabs" aria-label="AI Hub sections">{([['overview','Overview'],['development','Periodic knowledge'],['queues','Pipeline queues'],['activity','Agent activity'],['topology','Advanced topology']] as const).map(([id,label]) => <button type="button" key={id} className={view===id?'active':''} onClick={()=>setView(id)}>{label}</button>)}</nav>

    {view === "overview" ? <>
      <section className="control-plane-status-grid">
        <article><span>Knowledge grounding</span><strong>{knowledge.actual.published.length ? "Active" : "Waiting for activity"}</strong><p>Runbooks, evidence, and incident context supplied to resolution workflows.</p></article>
        <article><span>Agent communication</span><strong>{observed}/{knowledge.actual.rows.length || 0} observed</strong><p>Services seen exchanging workflow events in the currently loaded trace.</p></article>
        <article><span>Runtime transport</span><strong>{String(provider).toUpperCase()}</strong><p>Message transport observed for the selected workflow—not a model provider.</p></article>
        <article><span>Primary event path</span><strong>{knowledge.primaryTopic || "Not available"}</strong><p>The principal orchestration topic used between KaiMS agents.</p></article>
      </section>
      <article className="panel ai-hub-guide"><div><span>1</span><section><strong>Add trusted knowledge</strong><p>Onboard runbooks and application context from Platform Settings.</p></section></div><div><span>2</span><section><strong>Generate grounded RCA</strong><p>Resolution agents cite accepted evidence and abstain when context is insufficient.</p></section></div><div><span>3</span><section><strong>Review and improve</strong><p>Operator feedback and confirmed outcomes feed measurable RCA evaluation.</p></section></div></article>
    </> : null}

    {view === "development" ? <section className="periodic-knowledge-workspace">
      <article className="panel periodic-knowledge-header"><div><span className="discovery-eyebrow">Mode 02 · future incident readiness</span><h3>Periodic knowledge development</h3><p>Collect historical operational context, identify recurring failure patterns, and prepare governed runbook drafts for human review.</p></div><div className="action-row"><button className="button-secondary" onClick={loadDevelopment} disabled={development.loading}>Refresh report</button><button className="button-primary" onClick={runNow} disabled={development.running}>{development.running ? "Analyzing history…" : "Run analysis now"}</button></div></article>
      {development.error ? <div className="error" role="alert">{development.error}</div> : null}
      <section className="control-plane-status-grid">
        <article><span>Schedule</span><strong>{configuration.enabled ? `Every ${configuration.interval_hours}h` : "Paused"}</strong><p>{configuration.lookback_days}-day historical lookback.</p></article>
        <article><span>Evidence snapshots</span><strong>{development.report?.evidence_count ?? "—"}</strong><p>Persisted metadata and context available for future matching.</p></article>
        <article><span>Failure patterns</span><strong>{development.report?.patterns?.length ?? "—"}</strong><p>Recurring issue signatures identified from confirmed incidents.</p></article>
        <article><span>Awaiting review</span><strong>{development.report?.drafts?.filter((row:any)=>row.status==='draft').length ?? "—"}</strong><p>Draft runbooks cannot be auto-executed until approved.</p></article>
      </section>
      <div className="periodic-knowledge-grid">
        <article className="panel"><div className="panel-head"><div><h3>Collection configuration</h3><p>Collection runs for the application workspace selected at sign-in.</p></div><label className="checkbox-row"><input type="checkbox" checked={configuration.enabled} onChange={(event)=>setConfiguration({...configuration,enabled:event.target.checked})}/>Enabled</label></div><div className="filter-grid"><label>Run every (hours)<input type="number" min={1} max={168} value={configuration.interval_hours} onChange={(event)=>setConfiguration({...configuration,interval_hours:Number(event.target.value)})}/></label><label>History lookback (days)<input type="number" min={1} max={365} value={configuration.lookback_days} onChange={(event)=>setConfiguration({...configuration,lookback_days:Number(event.target.value)})}/></label></div><fieldset><legend>Context sources</legend><div className="check-grid">{([['collect_logs','Logs'],['collect_metrics','Metrics'],['collect_traces','Traces'],['collect_tickets','ITSM and Jira'],['collect_changes','Code and configuration changes']] as const).map(([key,label])=><label className="checkbox-row" key={key}><input type="checkbox" checked={configuration[key]} onChange={(event)=>setConfiguration({...configuration,[key]:event.target.checked})}/>{label}</label>)}</div></fieldset><button className="button-primary" onClick={saveConfiguration} disabled={development.saving}>{development.saving?'Saving…':'Save schedule'}</button></article>
        <article className="panel"><div className="panel-head"><div><h3>Latest run report</h3><p>Measurable output from the most recent historical analysis.</p></div></div><dl className="summary-list"><dt>Status</dt><dd>{development.report?.summary?.status || 'Not run'}</dd><dt>Completed</dt><dd>{development.report?.summary?.completed_at || '—'}</dd><dt>Incidents analyzed</dt><dd>{development.report?.summary?.incidents_analyzed ?? 0}</dd><dt>Patterns found</dt><dd>{development.report?.summary?.patterns ?? 0}</dd><dt>Reviewable candidates</dt><dd>{development.report?.summary?.reviewable_runbook_candidates ?? 0}</dd></dl></article>
      </div>
      <article className="panel"><div className="panel-head"><div><h3>Generated knowledge requiring review</h3><p>Edit and approve these drafts before KaiMS can use them for automatic remediation.</p></div></div><div className="table-wrap"><table><thead><tr><th>Runbook</th><th>Application</th><th>Risk</th><th>Version</th><th>Review state</th></tr></thead><tbody>{(development.report?.drafts||[]).map((row:any)=><tr key={`${row.runbook_id}-${row.version}`}><td><strong>{row.content?.name || row.runbook_id}</strong></td><td>{row.content?.application || '—'}</td><td>{row.risk_level}</td><td>{row.version}</td><td><span className={`workflow-pill ${row.status==='approved'?'workflow-pill-active':'workflow-pill-idle'}`}>{row.status}</span></td></tr>)}{!development.report?.drafts?.length?<tr><td colSpan={5}>No generated drafts yet. Run analysis after confirmed incident outcomes are available.</td></tr>:null}</tbody></table></div></article>
      <article className="panel"><div className="panel-head"><div><h3>Collected context for future incidents</h3><p>Recent normalized evidence snapshots retained for pattern matching and grounded RCA.</p></div></div><div className="table-wrap"><table><thead><tr><th>Incident</th><th>Service</th><th>Environment</th><th>Alert type</th><th>Collected</th><th>Reviewed</th></tr></thead><tbody>{(development.report?.recent_evidence||[]).map((row:any)=><tr key={row.incident_id}><td>{row.incident_id}</td><td>{row.service}</td><td>{row.environment}</td><td>{row.alert_type}</td><td>{row.collected_at||'—'}</td><td>{row.reviewed?'Yes':'No'}</td></tr>)}</tbody></table></div></article>
    </section> : null}

    {view === "queues" ? <section className="pipeline-queue-manager">
      <article className="panel periodic-knowledge-header"><div><span className="discovery-eyebrow">Administrator control · audited actions</span><h3>Pipeline Queue Manager</h3><p>See where alerts are waiting, inspect a non-destructive sample, stop one alert from future stages, or remove ready jobs from a selected queue.</p></div><button className="button-secondary" onClick={loadQueues} disabled={queueManager.loading}>{queueManager.loading?'Refreshing…':'Refresh queues'}</button></article>
      {queueManager.error?<div className="error" role="alert">{queueManager.error}</div>:null}{queueManager.result?<div className="status-message" role="status">{queueManager.result}</div>:null}
      <section className="control-plane-status-grid"><article><span>Pipeline queues</span><strong>{queueManager.summary.queues??'—'}</strong><p>KaiMS broker queues only.</p></article><article><span>Waiting</span><strong>{queueManager.summary.ready??'—'}</strong><p>Ready jobs that may be purged.</p></article><article><span>In flight</span><strong>{queueManager.summary.in_flight??'—'}</strong><p>Currently owned by consumers; not forcibly interrupted.</p></article><article><span>Dead letter</span><strong>{queueManager.summary.dead_letter??'—'}</strong><p>Failed jobs retained for diagnosis.</p></article></section>
      <article className="panel"><div className="panel-head"><div><h3>Alert pipeline</h3><p>Select a stage to inspect up to 25 queued alerts. Inspection requeues messages without changing their order or state.</p></div></div><div className="table-wrap"><table><thead><tr><th>Stage</th><th>Consumer</th><th>Waiting</th><th>In flight</th><th>Consumers</th><th>State</th><th></th></tr></thead><tbody>{queueManager.rows.map((row:any)=><tr key={row.name}><td><strong>{row.stage}</strong>{row.dead_letter?<span className="workflow-pill workflow-pill-idle">DLQ</span>:null}</td><td>{row.consumer_service}</td><td>{row.ready}</td><td>{row.in_flight}</td><td>{row.consumers}</td><td>{row.state}</td><td><button className="button-secondary" onClick={()=>inspectQueue(row)}>Inspect</button></td></tr>)}{!queueManager.rows.length?<tr><td colSpan={7}>{queueManager.loading?'Loading live broker inventory…':'No KaiMS queues were returned.'}</td></tr>:null}</tbody></table></div></article>
      {queueManager.selected?<article className="panel queue-inspector"><div className="panel-head"><div><span className="discovery-eyebrow">Selected stage</span><h3>{queueManager.selected.stage}</h3><p>{queueManager.selected.name}</p></div><button className="button-secondary" onClick={()=>setQueueManager((current)=>({...current,selected:null,messages:[]}))}>Close</button></div><div className="table-wrap"><table><thead><tr><th>Alert</th><th>Service</th><th>Severity</th><th>Incident</th><th>Size</th><th></th></tr></thead><tbody>{queueManager.messages.map((message:any,index:number)=><tr key={`${message.alert_id}-${index}`}><td>{message.name}<small>{message.alert_id||'ID not supplied'}</small></td><td>{message.service}</td><td>{message.severity}</td><td>{message.incident_id||'—'}</td><td>{message.payload_bytes} B</td><td>{message.alert_id?<button className="button-secondary" onClick={()=>setQueueManager((current)=>({...current,selectedAlertId:message.alert_id,confirmation:`STOP ${message.alert_id}`,result:`Prepared stop request for ${message.alert_id}`}))}>Prepare stop</button>:null}</td></tr>)}{!queueManager.messages.length?<tr><td colSpan={6}>No ready messages were available in this sample.</td></tr>:null}</tbody></table></div><section className="queue-danger-zone"><div><h4>Stop one alert</h4><p>The cancellation marker is checked at every subsequent RabbitMQ and Kafka stage. A currently executing atomic handler may finish.</p></div><label>Operational reason<textarea rows={2} value={queueManager.reason} onChange={(event)=>setQueueManager((current)=>({...current,reason:event.target.value}))}/></label><label>Confirmation<input value={queueManager.confirmation} onChange={(event)=>setQueueManager((current)=>({...current,confirmation:event.target.value}))} placeholder="STOP alert-id"/></label><div className="action-row"><button className="button-primary" disabled={queueManager.actionLoading||!queueManager.selectedAlertId||queueManager.confirmation!==`STOP ${queueManager.selectedAlertId}`} onClick={()=>queueAction('/cancel-alert','POST','Alert removed from future processing.')}>Stop selected alert</button><button className="button-danger" disabled={queueManager.actionLoading||queueManager.confirmation!==`PURGE ${queueManager.selected.name}`} onClick={()=>queueAction(`/${encodeURIComponent(queueManager.selected.name)}/messages`,'DELETE','Ready jobs removed from the selected queue.')}>Purge this queue</button></div><p className="field-hint">To purge this queue, enter exactly: PURGE {queueManager.selected.name}</p></section></article>:null}
      <details className="panel queue-global-danger"><summary>Emergency: purge all ready pipeline jobs</summary><p>This removes all ready KaiMS jobs across every queue. In-flight work is not interrupted. Use only during a controlled incident and record why.</p><label>Detailed operational reason<textarea rows={2} value={queueManager.reason} onChange={(event)=>setQueueManager((current)=>({...current,reason:event.target.value}))}/></label><label>Confirmation<input value={queueManager.confirmation} onChange={(event)=>setQueueManager((current)=>({...current,confirmation:event.target.value}))} placeholder="PURGE ALL READY JOBS"/></label><button className="button-danger" disabled={queueManager.actionLoading||queueManager.confirmation!=='PURGE ALL READY JOBS'} onClick={()=>queueAction('/purge-all/ready-messages','DELETE','All ready pipeline jobs were purged.')}>Purge all ready jobs</button></details>
    </section>:null}

    {view === "activity" ? <article className="panel"><div className="panel-head"><div><h3>Observed agent activity</h3><p>What each service consumed and published in the selected workflow.</p></div></div><div className="table-wrap"><table><thead><tr><th>Agent service</th><th>Input</th><th>Output</th><th>Transport</th><th>Observation</th></tr></thead><tbody>{knowledge.actual.rows.map((row,index)=><tr key={`${row.service}-${index}`}><td><strong>{row.service}</strong></td><td>{row.consumed}</td><td>{row.published}</td><td>{row.provider}</td><td><span className={`workflow-pill ${String(row.status).toLowerCase()==='observed'?'workflow-pill-active':'workflow-pill-idle'}`}>{row.status}</span></td></tr>)}{!knowledge.actual.rows.length?<tr><td colSpan={5}>Run or select an incident workflow to observe agent activity.</td></tr>:null}</tbody></table></div></article> : null}

    {view === "topology" ? <article className="panel"><div className="panel-head"><div><h3>Advanced message topology</h3><p>Engineering diagnostics for event routing. Most operators do not need to change this.</p></div></div><MessageBusTopology actual={knowledge.actual} configuredRows={knowledge.configuredRows} routing={knowledge.routing} primaryTopic={knowledge.primaryTopic}/><details className="technical-settings"><summary>Configured service routes</summary><div className="table-wrap"><table><thead><tr><th>Service</th><th>Consumes</th><th>Publishes</th></tr></thead><tbody>{knowledge.configuredRows.map((row,index)=><tr key={`${row.service}-${index}`}><td>{row.service}</td><td>{row.consumes}</td><td>{row.publishes}</td></tr>)}</tbody></table></div><p>Dynamic routing uses Kafka above the configured stream threshold and RabbitMQ otherwise. Observed workflow: {knowledge.routing?.workflow || "not available"}.</p></details></article> : null}
  </section>;
}
