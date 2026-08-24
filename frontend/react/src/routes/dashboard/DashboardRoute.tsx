import { Activity, ArrowRight, Bell, Bot, CalendarDays, CheckCircle2, CircleAlert, Filter, Info, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useRouteRuntime } from "../../app/routeRuntime";
import { operationsCockpit, type CockpitSummary } from "../cloud-ops/cloudOpsApi";
import "./DashboardRoute.css";
import "./DashboardA11y.css";
import "./DashboardTruth.css";
import "./DashboardChart.css";

const service=(v?:string)=>String(v||"Unassigned").replace(/[-_]/g," ");
const parseDate=(value:unknown)=>{const date=new Date(String(value||""));return Number.isFinite(date.getTime())?date:null};
const severityNumber=(value:unknown)=>{const severity=String(value||"").toLowerCase();if(["critical","sev1","p1"].includes(severity))return 1;if(["high","sev2","p2"].includes(severity))return 2;if(["medium","warning","sev3","p3"].includes(severity))return 3;return 4};
const numeric=(value:unknown)=>{const number=Number(String(value??"").replace(/[^0-9.-]/g,""));return Number.isFinite(number)?number:null};
const formatDuration=(milliseconds:number|null)=>{if(milliseconds===null)return"Unavailable";const minutes=Math.max(0,Math.round(milliseconds/60000)),days=Math.floor(minutes/1440),hours=Math.floor((minutes%1440)/60),mins=minutes%60;return days?`${days}d ${hours}h`:hours?`${hours}h ${mins}m`:`${mins}m`};
const availabilitySloTarget=99.9;

export default function DashboardRoute(){
 const {dashboard,executive,incidents,alerts}=useRouteRuntime();
 const [estateSummary,setEstateSummary]=useState<CockpitSummary|null>(null);
 useEffect(()=>{let mounted=true;operationsCockpit().then(value=>{if(mounted)setEstateSummary(value)}).catch(()=>{if(mounted)setEstateSummary(null)});return()=>{mounted=false}},[]);
 const buckets=Array.from({length:7},(_,index)=>{const date=new Date();date.setHours(0,0,0,0);date.setDate(date.getDate()-(6-index));return{key:date.toISOString().slice(0,10),label:date.toLocaleDateString(undefined,{month:"short",day:"numeric"}),severity:[0,0,0,0]}});
 const bucketMap=new Map(buckets.map(row=>[row.key,row])),seen=new Set<string>();
 incidents.rows.forEach((row,index)=>{const id=String(row.incident_id||row.id||`${row.service}-${row.created_at}-${index}`);if(seen.has(id))return;seen.add(id);const date=parseDate(row.created_at||row.latest_event_at||row.updated_at);const bucket=date?bucketMap.get(date.toISOString().slice(0,10)):null;if(bucket)bucket.severity[severityNumber(row.severity)-1]+=1});
 const trend=buckets.map(row=>({...row,value:row.severity.reduce((sum,value)=>sum+value,0)})),total=trend.reduce((sum,row)=>sum+row.value,0),max=Math.max(1,...trend.map(row=>row.value));
 const active=incidents.rows.filter(row=>!["closed","resolved","cancelled"].includes(String(row.status||"").toLowerCase()));
 const critical=alerts.rows.filter(row=>severityNumber(row.severity||row.labels?.severity)===1).length;
 const incidentSeverityById=new Map(incidents.rows.flatMap(row=>{
  const severity=String(row.severity||row.source_alert?.severity||"").trim();
  return [row.incident_id,row.id,row.alert_id].filter(Boolean).map(id=>[String(id),severity] as const);
 }));
 const closedRows=executive.recentlyClosed.map(row=>{
  const payload=row.projection_payload||{};
  const eventPayload=typeof payload.event_payload==="object"&&payload.event_payload?payload.event_payload as Record<string,any>:{};
  const alertPayload=typeof eventPayload.alert==="object"&&eventPayload.alert?eventPayload.alert as Record<string,any>:{};
  const severity=String(row.severity||alertPayload.severity||alertPayload.labels?.severity||row.source_alert?.severity||incidentSeverityById.get(String(row.incident_id||row.id||row.alert_id||""))||"").trim();
  return {...row,severity};
 });
 const durationsFor=(level?:number)=>closedRows.filter(row=>!level||severityNumber(row.severity)===level).map(row=>{const start=parseDate(row.created_at),end=parseDate(row.closed_at||row.updated_at);return start&&end&&end>=start?end.getTime()-start.getTime():null}).filter((value):value is number=>value!==null);
 const averageDuration=(level?:number)=>{const values=durationsFor(level);return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null};
 const p95=executive.latencyChart.length?numeric(executive.statCards.find(card=>card.label==="P95 Latency")?.value):null,requests=numeric(executive.statCards.find(card=>card.label==="Total Requests")?.value)||0,failed=numeric(executive.statCards.find(card=>card.label==="Failures")?.value)||0;
 const successRate=requests>0?Math.max(0,(requests-failed)/requests*100):null;
 const allowedErrorRate=100-availabilitySloTarget;
 const observedErrorRate=successRate===null?null:100-successRate;
 const errorBudgetRemaining=observedErrorRate===null?null:Math.max(0,100-(observedErrorRate/allowedErrorRate*100));
 const groups=new Map<string,{row:(typeof active)[number];count:number}>();active.forEach(row=>{const key=service(row.service),current=groups.get(key);groups.set(key,{row:current?.row||row,count:(current?.count||0)+1})});
 const serviceRows=[...groups.entries()].slice(0,5),severityTotals=[1,2,3,4].map(level=>incidents.rows.filter(row=>severityNumber(row.severity)===level).length);
 const awaitingApproval=active.filter(row=>String(row.status||"").toLowerCase().includes("approval")).length;
 const automatedResolved=closedRows.filter(row=>{const attribution=row as Record<string,unknown>;return [attribution.resolution_mode,attribution.closed_by,attribution.actor_type,attribution.remediation_status].some(value=>/auto|agent|kai/i.test(String(value||"")))}).length;
 const readinessValues=estateSummary?.readiness.map(row=>row.overall_score).filter(value=>Number.isFinite(value))||[];
 const readiness=readinessValues.length?Math.round(readinessValues.reduce((sum,value)=>sum+value,0)/readinessValues.length*100):null;
 const kpis=[
  {label:"Overall SLO Score",value:successRate===null?"Unavailable":`${successRate.toFixed(2)}%`,detail:successRate===null?`Target ${availabilitySloTarget}% · awaiting gateway samples`:`Target ${availabilitySloTarget}% · ${successRate>=availabilitySloTarget?"meeting objective":"objective breached"}`,tone:successRate!==null&&successRate<availabilitySloTarget?"amber":""},
  {label:"API Success Rate",value:successRate===null?"Unavailable":`${successRate.toFixed(2)}%`,detail:requests?`${requests} measured gateway requests`:"No gateway request samples",tone:""},
  {label:"API Latency (P95)",value:p95===null?"Unavailable":`${p95.toFixed(1)} ms`,detail:p95===null?"No measured latency samples":"Measured from gateway audit events",tone:p95!==null&&p95>1000?"amber":""},
  {label:"Error Budget",value:errorBudgetRemaining===null?"Unavailable":`${errorBudgetRemaining.toFixed(1)}% remaining`,detail:errorBudgetRemaining===null?`Target ${availabilitySloTarget}% · awaiting gateway samples`:`${observedErrorRate?.toFixed(3)}% observed errors · ${allowedErrorRate.toFixed(3)}% allowed`,tone:errorBudgetRemaining!==null&&errorBudgetRemaining<25?"amber":""},
 ];
 return <section className="ro-page">
  <header className="ro-heading"><div><span className="ro-eyebrow"><i/>Operations Command Center</span><h2>{active.length||critical?"Production needs attention.":"Production is stable in the observed scope."}</h2><p>One operational picture from signal detection through verified recovery. Unavailable values are never estimated.</p></div><div className="ro-tools"><button><CalendarDays/>Last 7 days</button><button aria-label="Notifications"><Bell/></button><button><Filter/>Live scope</button></div></header>
  <section className="ro-command-truth" aria-label="Operations command center summary">
   <article><span>Estate health</span><strong>{estateSummary?`${Object.values(estateSummary.health).reduce((sum,value)=>sum+value,0)} observed`:"Unavailable"}</strong><small>{estateSummary?`${estateSummary.resource_count} discovered resources`:"Estate telemetry did not respond"}</small></article>
   <article><span>Active incidents</span><strong>{active.length}</strong><small>{critical} critical alerts</small></article>
   <article><span>Kai auto-resolved</span><strong>{automatedResolved}</strong><small>Explicitly attributed closures only</small></article>
   <article><span>Human approvals</span><strong>{awaitingApproval}</strong><small>Awaiting a decision</small></article>
   <article><span>Recent changes</span><strong>Unavailable</strong><small>No change feed is loaded in this view</small></article>
   <article><span>Autonomy readiness</span><strong>{readiness===null?"Unavailable":`${readiness}%`}</strong><small>{readinessValues.length?`${readinessValues.length} assessed services`:"No readiness assessments"}</small></article>
  </section>
  <section className="ro-mission-strip" aria-label="Current operational priorities">
   <button className="is-critical" onClick={()=>dashboard.openSection("summary")}><span>Needs attention</span><strong>{active.length}</strong><small>active incidents</small><ArrowRight/></button>
   <button onClick={()=>dashboard.openSection("approval")}><span>Awaiting decision</span><strong>{active.filter(row=>String(row.status||"").toLowerCase().includes("approval")).length}</strong><small>human gates</small><ArrowRight/></button>
   <button onClick={()=>dashboard.openSection("closed")}><span>Recovered</span><strong>{closedRows.length}</strong><small>recent closures</small><ArrowRight/></button>
   <button className="is-ai" onClick={()=>dashboard.openSection("copilot")}><Bot/><span>Ask KAI</span><small>Investigate this environment</small><ArrowRight/></button>
  </section>
  <div className="ro-layout"><main className="ro-main">
   <article className="ro-card"><header><h3>Observed Reliability Signals <Info/></h3><button onClick={()=>dashboard.openSection("executive")}>View source metrics <ArrowRight/></button></header><div className="ro-kpis">{kpis.map(item=><div key={item.label}><span>{item.label}</span><strong className={item.tone}>{item.value}</strong><small>{item.detail}</small></div>)}</div></article>
   <article className="ro-card ro-trends"><header><h3>Incident Trends <Info/></h3><select aria-label="Incident trend interval"><option>Daily</option></select></header><div className="ro-summary"><div><span>Created incidents</span><strong>{total}</strong><small className="ro-source-label">Incident store · last 7 days</small></div><div className="ro-legend">{[1,2,3,4].map(level=><span key={level}><i className={`sev${level}`}/>Sev {level}</span>)}</div></div><div className="ro-bars">{trend.map(row=><div className="ro-column" key={row.key}><div className="ro-bar" role="img" style={{height:row.value?`${Math.max(8,row.value/max*100)}%`:"0"}} aria-label={`${row.label}: ${row.value} incidents`}>{row.severity.map((count,index)=>count?<i key={index} style={{flexGrow:count}} title={`Sev ${index+1}: ${count}`}/>:null)}</div><span>{row.label}</span></div>)}</div></article>
   <article className="ro-card ro-mttr"><header><h3>Mean-Time-to-Resolution (MTTR) <Info/></h3></header><div className="ro-mttr-grid">{[["MTTR (All Incidents)",averageDuration(),durationsFor().length],["MTTR (Sev 1 · Critical)",averageDuration(1),durationsFor(1).length],["MTTR (Sev 2 · High)",averageDuration(2),durationsFor(2).length]].map(([label,value,count])=><div key={String(label)}><span>{String(label)}</span><strong>{formatDuration(value as number|null)}</strong><small>{Number(count)?`Calculated from ${count} timestamped closure(s)`:"No closed incidents with complete lifecycle timestamps"}</small></div>)}<div className="ro-donut-wrap"><ul>{severityTotals.map((count,index)=><li key={index}><i className={`sev${index+1}`}/><span>{["Sev 1 · Critical","Sev 2 · High","Sev 3 · Medium","Sev 4 · Low"][index]}</span><b>{count}</b></li>)}</ul></div></div></article>
  </main><aside className="ro-side">
   <article className="ro-card ro-briefing"><header><Bot/><div><h3>Operational Briefing</h3><p>Derived from the currently loaded API records</p></div></header><div className="ro-brief-list"><div><CheckCircle2/><p><strong>{requests} gateway requests observed</strong><span>{successRate===null?"Success rate unavailable until request samples arrive.":`${successRate.toFixed(2)}% completed without recorded failure.`}</span></p></div><div><CircleAlert/><p><strong>{active.length} open incidents</strong><span>Counted from incident records not in a terminal state.</span></p></div><div><ShieldCheck/><p><strong>{critical} critical alerts in scope</strong><span>Counted from the current alert API response.</span></p></div><div><Activity/><p><strong>{closedRows.length} recent closures available</strong><span>{durationsFor().length?`${durationsFor().length} contain timestamps usable for MTTR.`:"No closures contain a complete start/end timestamp pair."}</span></p></div></div><button className="ro-primary" onClick={()=>dashboard.openSection("copilot")}>Open AI Hub <ArrowRight/></button></article>
   <article className="ro-card ro-risk"><header><h3>Service Risk <Info/></h3><button onClick={()=>dashboard.openSection("summary")}>View all services <ArrowRight/></button></header><div className="ro-risk-head"><span>Service</span><span>Risk Level</span><span>Open</span><span>Source</span></div>{serviceRows.length?serviceRows.map(([name,item])=><button className="ro-risk-row" key={name} onClick={()=>incidents.open(item.row)}><span>{name}</span><em>{String(item.row.severity||"unknown")}</em><b>{item.count}</b><small>Incidents</small></button>):<div className="ro-empty"><ShieldCheck/>No open incidents returned by the API</div>}</article>
  </aside></div>
 </section>;
}
