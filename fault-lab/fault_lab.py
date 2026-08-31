#!/usr/bin/env python3
"""KaiOps Fault Lab.

A dependency-free, bounded fault-injection application that reproduces the
observable symptoms behind the 50 KaiOps Jira incident scenarios. Monitoring
tools scrape /metrics and ingest runtime/application.log; they—not this app—
create alerts and tickets.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
import threading
import time
import uuid
from collections import Counter, deque
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "data" / "kaiops_jira_1000_tickets.csv"
RUNTIME = ROOT / "runtime"
RUNTIME.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(RUNTIME / "application.log", encoding="utf-8"),
    ],
)
LOGGER = logging.getLogger("kaiops-fault-lab")

TELEMETRY_DEMO_SCENARIOS = (
    "kaiops-scenario-42",  # Prometheus scrape targets partially unavailable.
    "kaiops-scenario-43",  # Telemetry agent export gap.
    "kaiops-scenario-22",  # Queue backlog while requests remain accepted.
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def prom_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def signal_profile(alert_name: str) -> dict[str, Any]:
    """Map a ticket alert to an observable application signal."""
    name = alert_name.lower()
    mappings = [
        ("latency", "kaiops_application_latency_ms", 2500.0, 3400.0, 240.0, "latency"),
        ("cpu", "kaiops_process_cpu_percent", 90.0, 95.0, 38.0, "saturation"),
        ("memory", "kaiops_process_memory_percent", 90.0, 94.0, 56.0, "saturation"),
        ("connection pool", "kaiops_connection_pool_percent", 95.0, 99.0, 42.0, "dependency"),
        ("connection saturation", "kaiops_connection_pool_percent", 95.0, 99.0, 42.0, "dependency"),
        ("replication lag", "kaiops_replication_lag_seconds", 300.0, 430.0, 3.0, "dependency"),
        ("consumer lag", "kaiops_consumer_lag_messages", 250000.0, 315000.0, 800.0, "backlog"),
        ("queue depth", "kaiops_queue_depth_messages", 100000.0, 128000.0, 280.0, "backlog"),
        ("dead-letter", "kaiops_dead_letter_messages", 1000.0, 5400.0, 0.0, "backlog"),
        ("disk", "kaiops_storage_percent", 90.0, 94.0, 61.0, "capacity"),
        ("tablespace", "kaiops_storage_percent", 90.0, 94.0, 61.0, "capacity"),
        ("packet loss", "kaiops_packet_loss_percent", 8.0, 9.4, 0.02, "network"),
        ("certificate", "kaiops_certificate_days_remaining", 7.0, 4.0, 90.0, "certificate"),
        ("pending pods", "kaiops_pending_pods", 20.0, 28.0, 0.0, "capacity"),
        ("node not ready", "kaiops_unready_nodes", 1.0, 2.0, 0.0, "availability"),
        ("cluster health red", "kaiops_unassigned_primary_shards", 1.0, 7.0, 0.0, "dependency"),
        ("scrape targets down", "kaiops_scrape_targets_down_percent", 15.0, 21.0, 0.0, "telemetry"),
        ("telemetry gap", "kaiops_telemetry_gap_seconds", 600.0, 1200.0, 0.0, "telemetry"),
        ("expiring", "kaiops_certificate_days_remaining", 7.0, 4.0, 90.0, "certificate"),
        ("duration", "kaiops_job_duration_minutes", 480.0, 620.0, 180.0, "pipeline"),
        ("missing", "kaiops_missing_expected_files", 1.0, 1.0, 0.0, "pipeline"),
        ("authentication", "kaiops_authentication_error_percent", 15.0, 22.0, 0.2, "auth"),
        ("access denied", "kaiops_access_denied_total", 10.0, 48.0, 0.0, "auth"),
        ("webhook", "kaiops_webhook_failure_percent", 10.0, 18.0, 0.1, "error"),
        ("pipeline failed", "kaiops_pipeline_failures", 1.0, 1.0, 0.0, "pipeline"),
    ]
    for keyword, metric, threshold, fault, healthy, behavior in mappings:
        if keyword in name:
            return dict(metric=metric, threshold=threshold, fault=fault, healthy=healthy, behavior=behavior)
    return dict(
        metric="kaiops_application_error_percent",
        threshold=8.0,
        fault=14.0,
        healthy=0.2,
        behavior="error",
    )


def scenario_id(labels: str) -> str:
    return next((x for x in labels.split(",") if x.startswith("kaiops-scenario-")), "kaiops-scenario-unknown")


class FaultLab:
    def __init__(self, dataset: Path, tick_seconds: float = 1.0) -> None:
        self.tick_seconds = tick_seconds
        self.scenarios = self._load_scenarios(dataset)
        self.active: dict[str, dict[str, Any]] = {}
        self.last_values: dict[str, float] = {
            sid: scenario["profile"]["healthy"] for sid, scenario in self.scenarios.items()
        }
        self.events: deque[dict[str, Any]] = deque(maxlen=3000)
        self.counters = Counter()
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.service_outage_expires_at = 0.0
        self.worker = threading.Thread(target=self._tick, daemon=True, name="fault-emitter")
        self.worker.start()

    @staticmethod
    def _load_scenarios(dataset: Path) -> dict[str, dict[str, Any]]:
        with dataset.open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
        scenarios: dict[str, dict[str, Any]] = {}
        for ticket in records:
            sid = scenario_id(ticket["Labels"])
            if sid in scenarios:
                continue
            scenarios[sid] = {
                "scenario_id": sid,
                "ticket_example": ticket["Issue ID"],
                "alert_name": ticket["Alert Name"],
                "service": ticket["Service"],
                "component": ticket["Component/s"],
                "severity": ticket["Severity"],
                "threshold_description": ticket["Threshold"],
                "root_cause": ticket["Root Cause"],
                "resolution_steps": ticket["Resolution Steps"].splitlines(),
                "validation": ticket["Validation / Closure Criteria"],
                "runbook_id": ticket["Runbook ID"],
                "profile": signal_profile(ticket["Alert Name"]),
            }
        if len(scenarios) != 50:
            raise RuntimeError(f"Expected 50 scenarios, found {len(scenarios)}")
        return scenarios

    def start_fault(self, sid: str, duration: int = 90) -> tuple[bool, dict[str, Any]]:
        scenario = self.scenarios.get(sid)
        if not scenario:
            return False, {"error": "Scenario not found"}
        duration = min(max(duration, 10), 900)
        with self.lock:
            if sid in self.active:
                return False, {"error": "Fault already active", "fault": self.active[sid]}
            fault = {
                "fault_id": f"fault-{uuid.uuid4().hex[:12]}",
                "scenario_id": sid,
                "started_at": time.time(),
                "expires_at": time.time() + duration,
                "duration_seconds": duration,
                "state": "ACTIVE",
            }
            self.active[sid] = fault
            self.counters["faults_started"] += 1
        self.emit(scenario, "WARN", "fault_activated", f"Activated bounded fault: {scenario['root_cause']}", fault)
        return True, fault

    def stop_fault(self, sid: str, reason: str = "manual") -> tuple[bool, dict[str, Any]]:
        with self.lock:
            fault = self.active.pop(sid, None)
        if not fault:
            return False, {"error": "Fault not active"}
        scenario = self.scenarios[sid]
        self.last_values[sid] = scenario["profile"]["healthy"]
        fault.update(state="RECOVERED", stopped_at=time.time(), stop_reason=reason)
        self.counters["faults_recovered"] += 1
        self.emit(scenario, "INFO", "fault_recovered", f"Fault recovered; validation: {scenario['validation']}", fault)
        return True, fault

    def set_service_outage(self, duration: int = 180) -> dict[str, Any]:
        duration = min(max(duration, 75), 900)
        with self.lock:
            self.service_outage_expires_at = time.time() + duration
        return {"service": "kaiops-fault-lab-service", "state": "DOWN", "duration_seconds": duration}

    def recover_service(self) -> dict[str, Any]:
        with self.lock:
            self.service_outage_expires_at = 0.0
        return {"service": "kaiops-fault-lab-service", "state": "UP"}

    def service_is_down(self) -> bool:
        with self.lock:
            if self.service_outage_expires_at and time.time() >= self.service_outage_expires_at:
                self.service_outage_expires_at = 0.0
            return self.service_outage_expires_at > 0

    def emit(
        self, scenario: dict[str, Any], level: str, event: str, message: str, fault: dict[str, Any]
    ) -> None:
        exception = ""
        if level == "ERROR":
            exception = (
                f"Simulated{scenario['component'].replace(' ', '')}Exception: {scenario['alert_name']}\n"
                f"\tat com.kaiops.faultlab.{scenario['service'].replace('-', '.')}.execute(FaultHandler.java:117)\n"
                "\tat com.kaiops.runtime.ResilientExecutor.invoke(ResilientExecutor.java:68)"
            )
        record = {
            "@timestamp": now(),
            "level": level,
            "service": scenario["service"],
            "component": scenario["component"],
            "logger": f"com.kaiops.faultlab.{scenario['service'].replace('-', '.')}",
            "event": event,
            "message": message,
            "exception": exception,
            "trace_id": uuid.uuid4().hex,
            "span_id": uuid.uuid4().hex[:16],
            "scenario_id": scenario["scenario_id"],
            "ticket_example": scenario["ticket_example"],
            "alert_name": scenario["alert_name"],
            "fault_id": fault["fault_id"],
            "root_cause": scenario["root_cause"],
            "resolution_steps": scenario["resolution_steps"],
            "validation": scenario["validation"],
            "runbook_id": scenario["runbook_id"],
            "synthetic": True,
        }
        with self.lock:
            self.events.append(record)
        LOGGER.log(getattr(logging, level, logging.INFO), json.dumps(record, separators=(",", ":")))

    def _tick(self) -> None:
        while not self.stop_event.wait(self.tick_seconds):
            current = time.time()
            with self.lock:
                active_items = list(self.active.items())
            for sid, fault in active_items:
                if current >= fault["expires_at"]:
                    self.stop_fault(sid, "duration_elapsed")
                    continue
                scenario = self.scenarios[sid]
                profile = scenario["profile"]
                jitter = 1 + random.uniform(-0.035, 0.035)
                value = profile["fault"] * jitter
                self.last_values[sid] = round(value, 3)
                self.counters[f"error:{sid}"] += 1
                self.emit(
                    scenario,
                    "ERROR",
                    "application_fault",
                    f"{scenario['alert_name']}; {profile['metric']}={value:.3f}, "
                    f"threshold={profile['threshold']}; {scenario['root_cause']}",
                    fault,
                )

    def exercise(self, service: str) -> tuple[int, dict[str, Any], float]:
        scenarios = [s for s in self.scenarios.values() if s["service"] == service]
        if not scenarios:
            return 404, {"error": "Unknown service"}, 0
        active = next((s for s in scenarios if s["scenario_id"] in self.active), None)
        self.counters[f"requests:{service}"] += 1
        if not active:
            return 200, {"service": service, "status": "ok", "timestamp": now()}, 0.02
        behavior = active["profile"]["behavior"]
        sid = active["scenario_id"]
        fault = self.active[sid]
        if behavior == "latency":
            delay = 2.8
            time.sleep(delay)
            return 504, {"error": "simulated upstream timeout", "scenario_id": sid}, delay
        if behavior == "auth":
            return 401, {"error": "simulated authorization failure", "scenario_id": sid}, 0.01
        if behavior in {"backlog", "pipeline"}:
            return 202, {"status": "accepted", "warning": "processing delayed", "scenario_id": sid}, 0.04
        if behavior == "telemetry":
            # An observability fault must never become an application outage.
            # The workload remains successful while logs and metrics expose the
            # degraded monitoring signal for the KaiOps investigation pipeline.
            return 200, {
                "service": service,
                "status": "ok",
                "warning": "telemetry degraded",
                "scenario_id": sid,
            }, 0.03
        if behavior in {"capacity", "saturation"}:
            return 503, {"error": "simulated resource saturation", "scenario_id": sid}, 0.12
        if behavior == "certificate":
            return 503, {"error": "simulated certificate validation failure", "scenario_id": sid}, 0.03
        self.emit(active, "ERROR", "request_failed", "Application request failed due to active fault.", fault)
        return 500, {"error": "simulated application failure", "scenario_id": sid}, 0.08

    def prometheus(self) -> str:
        lines = [
            "# HELP kaiops_fault_lab_info Fault Lab information.",
            "# TYPE kaiops_fault_lab_info gauge",
            f'kaiops_fault_lab_info{{scenarios="{len(self.scenarios)}"}} 1',
            "# HELP kaiops_active_faults Number of active bounded faults.",
            "# TYPE kaiops_active_faults gauge",
            f"kaiops_active_faults {len(self.active)}",
            "# HELP kaiops_fault_ratio Current signal divided by its alert threshold.",
            "# TYPE kaiops_fault_ratio gauge",
            "# HELP kaiops_fault_active Whether a bounded scenario fault is currently active (1 active, 0 healthy).",
            "# TYPE kaiops_fault_active gauge",
        ]
        for sid, scenario in self.scenarios.items():
            profile = scenario["profile"]
            value = self.last_values[sid]
            # Certificate expiry is breached when below threshold.
            ratio = profile["threshold"] / max(value, 0.001) if "days_remaining" in profile["metric"] else value / profile["threshold"]
            labels = (
                f'scenario_id="{prom_escape(sid)}",'
                f'service="{prom_escape(scenario["service"])}",'
                f'component="{prom_escape(scenario["component"])}",'
                f'severity="{prom_escape(scenario["severity"])}",'
                f'alert_name="{prom_escape(scenario["alert_name"])}",'
                f'ticket_example="{prom_escape(scenario["ticket_example"])}"'
            )
            lines.append(f"kaiops_fault_active{{{labels}}} {1 if sid in self.active else 0}")
            lines.append(f"kaiops_fault_ratio{{{labels}}} {ratio:.6f}")
            metric = profile["metric"]
            lines.extend(
                [
                    f"# HELP {metric} Simulated application signal." if f"# HELP {metric} Simulated application signal." not in lines else "",
                    f"# TYPE {metric} gauge" if f"# TYPE {metric} gauge" not in lines else "",
                    f"{metric}{{{labels}}} {value}",
                ]
            )
        lines.extend(
            [
                "# HELP kaiops_faults_started_total Total bounded faults started.",
                "# TYPE kaiops_faults_started_total counter",
                f"kaiops_faults_started_total {self.counters['faults_started']}",
                "# HELP kaiops_faults_recovered_total Total bounded faults recovered.",
                "# TYPE kaiops_faults_recovered_total counter",
                f"kaiops_faults_recovered_total {self.counters['faults_recovered']}",
            ]
        )
        return "\n".join(line for line in lines if line) + "\n"


DASHBOARD = r"""<!doctype html><html><head><meta charset="utf-8"><title>KaiOps Fault Lab</title>
<style>body{font-family:Segoe UI,Arial;background:#f4f7fb;color:#142033;margin:0}header{background:#17365d;color:#fff;padding:18px 28px}
main{padding:22px;max-width:1300px;margin:auto}.notice{background:#fff7ed;border-left:5px solid #ea580c;padding:12px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px}.card{background:#fff;border:1px solid #d8e1eb;border-radius:10px;padding:15px}
.Critical{border-left:6px solid #b91c1c}.High{border-left:6px solid #ea580c}.Medium{border-left:6px solid #d97706}
button{border:0;border-radius:6px;padding:8px 12px;color:white;cursor:pointer;margin-right:6px}.start{background:#b91c1c}.stop{background:#0f766e}
.active{box-shadow:0 0 0 3px #22c55e}.state{font-weight:700;color:#15803d}.status{min-height:22px;margin:8px 0;color:#334155}
button:disabled{cursor:not-allowed;opacity:.5}.muted{color:#64748b;font-size:13px}pre{background:#111827;color:#d1fae5;padding:12px;max-height:330px;overflow:auto;border-radius:8px}</style>
</head><body><header><h2>KaiOps Fault-Producing Application</h2></header><main>
<div class="notice"><b>Safe lab only:</b> faults are bounded to this process. Monitoring detects the breached metrics and logs and can create the Jira incidents.</div>
<p><button class="stop" id="refresh-button">Refresh</button><button class="start" id="service-down-button">Test KaiOps service down</button><button class="stop" id="service-up-button">Restore test service</button> <span id="summary"></span></p><div id="status" class="status" role="status"></div><div id="grid" class="grid"></div>
<h3>Live application errors</h3><pre id="events">Activate a fault to produce errors.</pre>
<script>
async function request(url,options){let r=await fetch(url,options);let d=await r.json();if(!r.ok)throw new Error(d.error||`Request failed (${r.status})`);return d}
async function refresh(){let d=await request('/api/scenarios'),active=await request('/api/faults'),activeIds=new Set(active.items.map(x=>x.scenario_id));document.getElementById('summary').textContent=`${d.items.length} failure scenarios · ${d.active_count} active`;
document.getElementById('grid').innerHTML=d.items.map(x=>{let isActive=activeIds.has(x.scenario_id);return `<div class="card ${x.severity} ${isActive?'active':''}"><b>${x.scenario_id}: ${x.alert_name}</b><p>${x.service} · ${x.component}</p>
<p class="muted">${x.root_cause}</p><p>Metric: ${x.profile.metric}<br>Threshold: ${x.profile.threshold}</p>
${isActive?'<p class="state">ACTIVE — emitting breached metrics and logs</p>':''}<button class="start" data-action="start" data-id="${x.scenario_id}" ${isActive?'disabled':''}>Start fault</button><button class="stop" data-action="stop" data-id="${x.scenario_id}" ${isActive?'':'disabled'}>Recover</button></div>`}).join('')}
async function changeFault(action,id){let status=document.getElementById('status');status.textContent=`${action==='start'?'Starting':'Recovering'} ${id}…`;try{let d=await request(`/api/faults/${id}/${action}${action==='start'?'?duration=90':''}`,{method:'POST'});status.textContent=action==='start'?`✓ ${id} started. Prometheus alert evaluation takes about 15–30 seconds.`:`✓ ${id} recovered.`;await refresh()}catch(e){status.textContent=`Could not ${action} ${id}: ${e.message}`}}
async function events(){let r=await fetch('/api/events?limit=30'),d=await r.json();document.getElementById('events').textContent=d.items.map(x=>JSON.stringify(x)).join('\n')}
document.getElementById('refresh-button').addEventListener('click',refresh);document.getElementById('grid').addEventListener('click',e=>{let b=e.target.closest('button[data-action]');if(b&&!b.disabled)changeFault(b.dataset.action,b.dataset.id)});
document.getElementById('service-down-button').addEventListener('click',async()=>{let s=document.getElementById('status');try{await request('/api/demos/service-down/start?duration=180',{method:'POST'});s.textContent='✓ Test service is DOWN. KaiOpsServiceDown will fire after one minute.'}catch(e){s.textContent=`Could not stop test service: ${e.message}`}});
document.getElementById('service-up-button').addEventListener('click',async()=>{let s=document.getElementById('status');try{await request('/api/demos/service-down/stop',{method:'POST'});s.textContent='✓ Test service restored. Prometheus will send a resolved event.'}catch(e){s.textContent=`Could not restore test service: ${e.message}`}});
refresh().catch(e=>document.getElementById('status').textContent=`Dashboard refresh failed: ${e.message}`);events();setInterval(events,1000);setInterval(refresh,4000)</script></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    lab: FaultLab

    def send_body(self, status: int, body: Any, content_type: str = "application/json") -> None:
        payload = body.encode() if isinstance(body, str) else json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            return self.send_body(200, DASHBOARD, "text/html")
        if parsed.path == "/health":
            return self.send_body(200, {"status": "UP", "active_faults": len(self.lab.active), "timestamp": now()})
        if parsed.path == "/api/scenarios":
            return self.send_body(200, {"items": list(self.lab.scenarios.values()), "active_count": len(self.lab.active)})
        if parsed.path == "/api/faults":
            return self.send_body(200, {"items": list(self.lab.active.values())})
        if parsed.path == "/api/events":
            limit = min(int(query.get("limit", ["100"])[0]), 500)
            with self.lab.lock:
                return self.send_body(200, {"items": list(self.lab.events)[-limit:]})
        if parsed.path == "/metrics":
            return self.send_body(200, self.lab.prometheus(), "text/plain; version=0.0.4")
        if parsed.path == "/service-health/metrics":
            if self.lab.service_is_down():
                return self.send_body(503, "bounded test service outage\n", "text/plain")
            return self.send_body(200, "# TYPE kaiops_test_service_info gauge\nkaiops_test_service_info 1\n", "text/plain; version=0.0.4")
        match = re.fullmatch(r"/workload/([a-zA-Z0-9_-]+)", parsed.path)
        if match:
            status, body, latency = self.lab.exercise(match.group(1))
            body["latency_seconds"] = latency
            return self.send_body(status, body)
        return self.send_body(404, {"error": "Endpoint not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        service_match = re.fullmatch(r"/api/demos/service-down/(start|stop)", parsed.path)
        if service_match:
            action = service_match.group(1)
            body = self.lab.set_service_outage(int(query.get("duration", ["180"])[0])) if action == "start" else self.lab.recover_service()
            return self.send_body(HTTPStatus.ACCEPTED if action == "start" else HTTPStatus.OK, body)
        demo_match = re.fullmatch(r"/api/demos/telemetry/(start|stop)", parsed.path)
        if demo_match:
            action = demo_match.group(1)
            duration = int(query.get("duration", ["120"])[0])
            results = []
            for sid in TELEMETRY_DEMO_SCENARIOS:
                if action == "start":
                    ok, body = self.lab.start_fault(sid, duration)
                else:
                    ok, body = self.lab.stop_fault(sid, "telemetry_demo_stopped")
                results.append({"scenario_id": sid, "ok": ok, **body})
            return self.send_body(
                HTTPStatus.ACCEPTED if action == "start" else HTTPStatus.OK,
                {
                    "demo": "telemetry-agent-investigation",
                    "action": action,
                    "application_available": True,
                    "results": results,
                },
            )
        match = re.fullmatch(r"/api/faults/(kaiops-scenario-\d{2})/(start|stop)", parsed.path)
        if not match:
            return self.send_body(404, {"error": "Endpoint not found"})
        sid, action = match.groups()
        if action == "start":
            ok, body = self.lab.start_fault(sid, int(query.get("duration", ["90"])[0]))
            return self.send_body(HTTPStatus.ACCEPTED if ok else HTTPStatus.CONFLICT, body)
        ok, body = self.lab.stop_fault(sid)
        return self.send_body(200 if ok else 409, body)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--tick-seconds", type=float, default=1.0)
    parser.add_argument("--start", metavar="SCENARIO_ID")
    parser.add_argument("--duration", type=int, default=90)
    args = parser.parse_args()
    lab = FaultLab(args.dataset, args.tick_seconds)
    Handler.lab = lab
    if args.start:
        lab.start_fault(args.start, args.duration)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"KaiOps Fault Lab: http://localhost:{args.port}")
    print(f"Prometheus metrics: http://localhost:{args.port}/metrics")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        lab.stop_event.set()
        server.server_close()


if __name__ == "__main__":
    main()
