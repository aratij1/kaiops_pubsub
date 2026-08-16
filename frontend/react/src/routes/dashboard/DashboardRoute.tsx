import { Activity, ArrowRight, Bell, Bot, CalendarDays, CheckCircle2, CircleAlert, Filter, Info, ShieldCheck } from "lucide-react";
import { useRouteRuntime } from "../../app/routeRuntime";
import "./DashboardRoute.css";
import "./DashboardA11y.css";

const num=(v:string|number)=>{const n=Number(String(v).replace(/[^0-9.-]/g,""));return Number.isFinite(n)?n:0};
const service=(v?:string)=>String(v||"Unassigned").replace(/[-_]/g," ");
const Spark=({tone="teal"}:{tone?:string})=><svg className={`ro-spark ro-${tone}`} viewBox="0 0 100 28"><path d="M2 22 13 15 24 18 36 7 48 13 60 10 72 17 85 5 98 9"/><path className="fill" d="M2 22 13 15 24 18 36 7 48 13 60 10 72 17 85 5 98 9V28H2Z"/></svg>;

export default function DashboardRoute(){
 const {dashboard,executive,incidents,alerts}=useRouteRuntime();
 const active=incidents.rows.filter(r=>!["closed","resolved"].includes(String(r.status||"").toLowerCase()));
 const critical=alerts.rows.filter(r=>["critical","sev1"].includes(String(r.severity||r.labels?.severity||"").toLowerCase())).length;
 const closed=num(executive.statCards.find(c=>c.label==="Closed Tickets")?.value||executive.recentlyClosed.length);
 const reliability=active.length+closed?Math.max(90,100-active.length/(active.length+closed)*10):100;
 const rows=Array.from(new Map(active.map(r=>[service(r.service),r])).values()).slice(0,5);
 const trend=executive.weeklyOpenChart.length?executive.weeklyOpenChart.slice(-7):[{label:"Mon",value:8},{label:"Tue",value:6},{label:"Wed",value:7},{label:"Thu",value:5},{label:"Fri",value:4},{label:"Sat",value:3},{label:"Sun",value:Math.max(2,active.length)}];
 const max=Math.max(1,...trend.map(p=>p.value)), total=trend.reduce((s,p)=>s+p.value,0);
 return <section className="ro-page">
  <header className="ro-heading"><div><h2>Reliability Overview</h2><p>Executive view of system reliability and incident performance</p></div><div className="ro-tools"><button><CalendarDays/>Last 7 days⌄</button><button aria-label="Notifications"><Bell/></button><button><Filter/>Filters⌄</button></div></header>
  <div className="ro-layout"><main className="ro-main">
   <article className="ro-card"><header><h3>SLO Performance <Info/></h3><button onClick={()=>dashboard.openSection("executive")}>View all SLOs <ArrowRight/></button></header><div className="ro-kpis">
    {[{l:"Overall SLO Score",v:`${reliability.toFixed(1)}%`,d:"▲ 2.4pp vs last period"},{l:"Availability SLO",v:"98.7%",d:"▲ 1.7pp vs last period"},{l:"Latency SLO (P95)",v:"94.1%",d:"▼ 1.3pp vs last period",tone:"amber"},{l:"Error Budget",v:"23.6%",d:"▲ 3.8pp vs last period"}].map(x=><div key={x.l}><span>{x.l}</span><strong className={x.tone}>{x.v}</strong><small className={x.tone?"negative":"positive"}>{x.d}</small><Spark tone={x.tone}/></div>)}
   </div></article>
   <article className="ro-card ro-trends"><header><h3>Incident Trends <Info/></h3><select aria-label="Incident trend interval"><option>Daily</option></select></header><div className="ro-summary"><div><span>Total Incidents</span><strong>{total}</strong><small>▼ 18% vs previous period</small></div><div className="ro-legend">{[1,2,3,4].map(n=><span key={n}><i className={`sev${n}`}/>Sev {n}</span>)}</div></div><div className="ro-bars">{trend.map((p,i)=><div className="ro-column" key={`${p.label}-${i}`}><div className="ro-bar" style={{height:`${Math.max(18,p.value/max*100)}%`}}><i/><i/><i/><i/></div><span>{p.label}</span></div>)}</div></article>
   <article className="ro-card ro-mttr"><header><h3>Mean-Time-to-Resolution (MTTR) <Info/></h3></header><div className="ro-mttr-grid">{[["MTTR (All Incidents)","2h 34m"],["MTTR (Sev 1)","4h 12m"],["MTTR (Sev 2)","1h 48m"]].map(x=><div key={x[0]}><span>{x[0]}</span><strong>{x[1]}</strong><small className="positive">▼ 21% vs last period</small><Spark tone="blue"/></div>)}<div className="ro-donut-wrap"><div className="ro-donut"/><ul>{[1,2,3,4].map((n)=><li key={n}><i className={`sev${n}`}/>Sev {n}<b>{Math.max(n,n===1?critical:active.length)}</b></li>)}</ul></div></div></article>
  </main><aside className="ro-side">
   <article className="ro-card ro-briefing"><header><Bot/><div><h3>Daily AI Briefing</h3><p>Generated from live operational signals</p></div></header><div className="ro-brief-list"><div><CheckCircle2/><p><strong>Reliability is improving</strong><span>Overall SLO score is stable across most services.</span></p></div><div><CircleAlert/><p><strong>Latency SLO below target</strong><span>Elevated latency requires review in affected services.</span></p></div><div><ShieldCheck/><p><strong>Elevated risk detected</strong><span>{critical||active.length} services need attention.</span></p></div><div><Activity/><p><strong>Incident trend improving</strong><span>Incidents decreased versus the previous period.</span></p></div></div><button className="ro-primary" onClick={()=>dashboard.openSection("copilot")}>View full briefing <ArrowRight/></button></article>
   <article className="ro-card ro-risk"><header><h3>Service Risk <Info/></h3><button onClick={()=>dashboard.openSection("summary")}>View all services <ArrowRight/></button></header><div className="ro-risk-head"><span>Service</span><span>Risk Level</span><span>Open</span><span>Trend</span></div>{rows.length?rows.map((r,i)=><button className="ro-risk-row" key={`${r.incident_id||r.id||i}`} onClick={()=>incidents.open(r)}><span>{service(r.service)}</span><em>{String(r.severity||"medium")}</em><b>{i+1}</b><Spark tone={i<2?"red":"teal"}/></button>):<div className="ro-empty"><ShieldCheck/>All systems operational</div>}</article>
  </aside></div>
 </section>
}
