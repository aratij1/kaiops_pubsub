import { Activity, ArrowRight, Bell, Bot, CalendarDays, CheckCircle2, CircleAlert, Filter, Info, ShieldCheck } from "lucide-react";
import { useRouteRuntime } from "../../app/routeRuntime";
import "./DashboardRoute.css";
import "./DashboardA11y.css";
import "./DashboardTruth.css";

const service=(v?:string)=>String(v||"Unassigned").replace(/[-_]/g," ");
const parseDate=(value:unknown)=>{const date=new Date(String(value||""));return Number.isFinite(date.getTime())?date:null};
const severityNumber=(value:unknown)=>{const severity=String(value||"").toLowerCase();if(["critical","sev1","p1"].includes(severity))return 1;if(["high","sev2","p2"].includes(severity))return 2;if(["medium","warning","sev3","p3"].includes(severity))return 3;return 4};
const numeric=(value:unknown)=>{const number=Number(String(value??"").replace(/[^0-9.-]/g,""));return Number.isFinite(number)?number:null};
const formatDuration=(milliseconds:number|null)=>{if(milliseconds===null)return"Unavailable";const minutes=Math.max(0,Math.round(milliseconds/60000)),days=Math.floor(minutes/1440),hours=Math.floor((minutes%1440)/60),mins=minutes%60;return days?`${days}d ${hours}h`:hours?`${hours}h ${mins}m`:`${mins}m`};

export default function DashboardRoute(){
 const {dashboard,executive,incidents,alerts}=useRouteRuntime();
 const canAccessExecutive = dashboard.allowedTabs.includes("executive");
 const canAccessRag = dashboard.allowedTabs.includes("rag");
 const buckets=Array.from({length:7},(_,index)=>{const date=new Date();date.setHours(0,0,0,0);date.setDate(date.getDate()-(6-index));return{key:date.toISOString().slice(0,10),label:date.toLocaleDateString(undefined,{month:"short",day:"numeric"}),severity:[0,0,0,0]}});
 const bucketMap=new Map(buckets.map(row=>[row.key,row])),seen=new Set<string>();
 incidents.rows.forEach((row,index)=>{const id=String(row.incident_id||row.id||`${row.service}-${row.created_at}-${index}`);if(seen.has(id))return;seen.add(id);const date=parseDate(row.created_at||row.latest_event_at||row.updated_at);const bucket=date?bucketMap.get(date.toISOString().slice(0,10)):null;if(bucket)bucket.severity[severityNumber(row.severity)-1]+=1});
 const trend=buckets.map(row=>({...row,value:row.severity.reduce((sum,value)=>sum+value,0)})),total=trend.reduce((sum,row)=>sum+row.value,0),max=Math.max(1,...trend.map(row=>row.value));
 const active=incidents.rows.filter(row=>!["closed","resolved","cancelled"].includes(String(row.status||"").toLowerCase()));
 const critical=alerts.rows.filter(row=>severityNumber(row.severity||row.labels?.severity)===1).length;
 const closedRows=executive.recentlyClosed;
 const durationsFor=(level?:number)=>closedRows.filter(row=>!level||severityNumber(row.severity)===level).map(row=>{const start=parseDate(row.created_at),end=parseDate(row.closed_at||row.updated_at);return start&&end&&end>=start?end.getTime()-start.getTime():null}).filter((value):value is number=>value!==null);
 const averageDuration=(level?:number)=>{const values=durationsFor(level);return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null};
 const p95=executive.latencyChart.length?numeric(executive.statCards.find(card=>card.label==="P95 Latency")?.value):null,requests=numeric(executive.statCards.find(card=>card.label==="Total Requests")?.value)||0,failed=numeric(executive.statCards.find(card=>card.label==="Failures")?.value)||0;
 const successRate=requests>0?Math.max(0,(requests-failed)/requests*100):null;
 const groups=new Map<string,{row:(typeof active)[number];count:number}>();active.forEach(row=>{const key=service(row.service),current=groups.get(key);groups.set(key,{row:current?.row||row,count:(current?.count||0)+1})});
 const serviceRows=[...groups.entries()].slice(0,5),severityTotals=[1,2,3,4].map(level=>incidents.rows.filter(row=>severityNumber(row.severity)===level).length);
 const kpis=[
  {label:"Overall SLO Score",value:"Not configured",detail:"No authoritative SLO objective/query is registered",tone:"muted"},
  {label:"API Success Rate",value:successRate===null?"Unavailable":`${successRate.toFixed(2)}%`,detail:requests?`${requests} measured gateway requests`:"No gateway request samples",tone:""},
  {label:"API Latency (P95)",value:p95===null?"Unavailable":`${p95.toFixed(1)} ms`,detail:p95===null?"No measured latency samples":"Measured from gateway audit events",tone:p95!==null&&p95>1000?"amber":""},
  {label:"Error Budget",value:"Not configured",detail:"Requires an SLO target and burn-rate query",tone:"muted"},
 ];
 return <section className="ro-page">
  <header className="ro-heading"><div><h2>Reliability Overview</h2><p>Observed operational data only · no synthetic fallback values</p></div><div className="ro-tools">
   <div style={{ display: "flex", alignItems: "center", position: "relative" }}>
    <CalendarDays style={{ position: "absolute", left: "10px", width: "14px", pointerEvents: "none", color: "#5c687d" }} />
    <select
      aria-label="Time range"
      disabled
      title="Data range is locked to 7 days based on telemetry retention limits"
      style={{
        height: "34px",
        paddingLeft: "28px",
        paddingRight: "10px",
        border: "1px solid #dbe2ea",
        borderRadius: "7px",
        background: "#f4f6f9",
        color: "#5c687d",
        fontSize: ".65rem",
        cursor: "not-allowed",
        appearance: "none",
        fontWeight: 500,
      }}
    >
      <option>Last 7 days</option>
    </select>
   </div>
   <button aria-label="Notifications" onClick={()=>dashboard.openSection("notifications")}><Bell/></button>
   <div style={{ display: "flex", alignItems: "center", position: "relative" }}>
    <Filter style={{ position: "absolute", left: "10px", width: "14px", pointerEvents: "none", color: "#27344b" }} />
    <select
      value={dashboard.selectedProject}
      onChange={(e)=>dashboard.selectProject(e.target.value)}
      aria-label="Filter live scope"
      style={{
        height: "34px",
        paddingLeft: "28px",
        paddingRight: "18px",
        border: "1px solid #dbe2ea",
        borderRadius: "7px",
        background: "#fff",
        color: "#27344b",
        fontSize: ".65rem",
        cursor: "pointer",
        appearance: "none",
        fontWeight: 500,
      }}
    >
      {dashboard.observedProjects.map((name)=><option key={name} value={name}>{name}</option>)}
    </select>
   </div>
  </div></header>
  <div className="ro-layout"><main className="ro-main">
   <article className="ro-card"><header><h3>Observed Reliability Signals <span title="KPIs derived from service health probes, MTTA, MTTR, and automation rate in the current window."><Info tabIndex={0} role="img" aria-label="KPIs derived from service health probes, MTTA, MTTR, and automation rate in the current window." style={{ cursor: "help", width: "13px", height: "13px", marginLeft: "4px", color: "#8c98aa" }} /></span></h3>
   {canAccessExecutive ? (
    <button onClick={()=>dashboard.openSection("executive")}>View source metrics <ArrowRight/></button>
   ) : (
    <button disabled title="This destination is not available to your role" style={{ display: "flex", alignItems: "center", gap: "4px", padding: "0", border: "0", background: "none", color: "#8c98aa", fontSize: ".61rem", fontWeight: 700, cursor: "not-allowed" }}>View source metrics <ArrowRight/></button>
   )}
   </header><div className="ro-kpis">{kpis.map(item=><div key={item.label}><span>{item.label}</span><strong className={item.tone}>{item.value}</strong><small>{item.detail}</small></div>)}</div></article>
   <article className="ro-card ro-trends"><header><h3>Incident Trends <span title="Count of newly created incidents bucketed by severity level over a 7-day rolling window."><Info tabIndex={0} role="img" aria-label="Count of newly created incidents bucketed by severity level over a 7-day rolling window." style={{ cursor: "help", width: "13px", height: "13px", marginLeft: "4px", color: "#8c98aa" }} /></span></h3><select aria-label="Incident trend interval" disabled title="Trends are calculated on a daily rolling basis" style={{ cursor: "not-allowed", opacity: 0.85 }}><option>Daily</option></select></header><div className="ro-summary"><div><span>Created incidents</span><strong>{total}</strong><small className="ro-source-label">Incident store · last 7 days</small></div><div className="ro-legend">{[1,2,3,4].map(level=><span key={level}><i className={`sev${level}`}/>Sev {level}</span>)}</div></div><div className="ro-bars">{trend.map(row=><div className="ro-column" key={row.key}><div className="ro-bar" style={{height:row.value?`${Math.max(8,row.value/max*100)}%`:"0"}} aria-label={`${row.label}: ${row.value} incidents`}>{row.severity.map((count,index)=>count?<i key={index} style={{flexGrow:count}} title={`Sev ${index+1}: ${count}`}/>:null)}</div><span>{row.label}</span></div>)}</div></article>
   <article className="ro-card ro-mttr"><header><h3>Mean-Time-to-Resolution (MTTR) <span title="Calculated from timestamped incident closure durations."><Info tabIndex={0} role="img" aria-label="Calculated from timestamped incident closure durations." style={{ cursor: "help", width: "13px", height: "13px", marginLeft: "4px", color: "#8c98aa" }} /></span></h3></header><div className="ro-mttr-grid">{[["MTTR (All Incidents)",averageDuration(),durationsFor().length],["MTTR (Sev 1)",averageDuration(1),durationsFor(1).length],["MTTR (Sev 2)",averageDuration(2),durationsFor(2).length]].map(([label,value,count])=><div key={String(label)}><span>{String(label)}</span><strong>{formatDuration(value as number|null)}</strong><small>{Number(count)?`Calculated from ${count} timestamped closure(s)`:"Insufficient lifecycle timestamps"}</small></div>)}<div className="ro-donut-wrap"><ul>{severityTotals.map((count,index)=><li key={index}><i className={`sev${index+1}`}/>Sev {index+1}<b>{count}</b></li>)}</ul></div></div></article>
  </main><aside className="ro-side">
   <article className="ro-card ro-briefing"><header><Bot/><div><h3>Operational Briefing</h3><p>Derived from the currently loaded API records</p></div></header><div className="ro-brief-list"><div><CheckCircle2/><p><strong>{requests} gateway requests observed</strong><span>{successRate===null?"Success rate unavailable until request samples arrive.":`${successRate.toFixed(2)}% completed without recorded failure.`}</span></p></div><div><CircleAlert/><p><strong>{active.length} open incidents</strong><span>Counted from incident records not in a terminal state.</span></p></div><div><ShieldCheck/><p><strong>{critical} critical alerts in scope</strong><span>Counted from the current alert API response.</span></p></div><div><Activity/><p><strong>{closedRows.length} recent closures available</strong><span>{durationsFor().length?`${durationsFor().length} contain timestamps usable for MTTR.`:"No closures contain a complete start/end timestamp pair."}</span></p></div></div>
   {canAccessRag ? (
    <button className="ro-primary" onClick={()=>dashboard.openSection("rag")}>Open AI Hub <ArrowRight/></button>
   ) : (
    <button className="ro-primary" disabled title="This destination is not available to your role" style={{ opacity: 0.5, cursor: "not-allowed" }}>Open AI Hub <ArrowRight/></button>
   )}
   </article>
   <article className="ro-card ro-risk"><header><h3>Service Risk <span title="Open incidents classified by severity level and impact per active managed application connector."><Info tabIndex={0} role="img" aria-label="Open incidents classified by severity level and impact per active managed application connector." style={{ cursor: "help", width: "13px", height: "13px", marginLeft: "4px", color: "#8c98aa" }} /></span></h3><button onClick={()=>dashboard.openSection("summary")}>View all services <ArrowRight/></button></header><div className="ro-risk-head"><span>Service</span><span>Risk Level</span><span>Open</span><span>Source</span></div>{serviceRows.length?serviceRows.map(([name,item])=><button className="ro-risk-row" key={name} onClick={()=>incidents.open(item.row)}><span>{name}</span><em>{String(item.row.severity||"unknown")}</em><b>{item.count}</b><small>Incidents</small></button>):<div className="ro-empty"><ShieldCheck/>No open incidents returned by the API</div>}</article>
  </aside></div>
 </section>;
}
