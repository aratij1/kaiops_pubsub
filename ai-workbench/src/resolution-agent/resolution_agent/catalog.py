from __future__ import annotations

from typing import Any


RESOLUTION_CATALOG: tuple[dict[str, Any], ...] = (
    {"id":"restart-workload","title":"Restart unhealthy workload","patterns":["down","unavailable","crash","health"],"risk":"medium","applicability":"Use when health checks fail and the current deployment is known good.","prerequisites":["Confirm the affected workload and namespace","Capture current logs and replica state"],"diagnostics":["Check readiness, liveness, restarts, and recent events","Confirm dependencies are reachable"],"steps":["Restart only the unhealthy workload using the approved deployment target","Watch rollout status and error rate"],"validation":["Health checks pass","Error rate and saturation return to baseline"],"rollback":["Stop the rollout and restore the last healthy replica set"]},
    {"id":"rollback-deployment","title":"Roll back recent deployment","patterns":["deployment","release","regression","latency","error"],"risk":"high","applicability":"Use when degradation began after a verified code or configuration change.","prerequisites":["Identify the last healthy revision","Confirm rollback compatibility and approval"],"diagnostics":["Compare incident start time with deployment history","Review changed code, configuration, and dependency versions"],"steps":["Roll back to the last healthy approved revision","Monitor rollout and retain the failed revision for analysis"],"validation":["Latency and errors recover","Key business transactions succeed"],"rollback":["Re-deploy the newer revision only after its defect is corrected and validated"]},
    {"id":"scale-capacity","title":"Increase service capacity","patterns":["saturation","cpu","memory","queue","backlog","throughput","latency"],"risk":"medium","applicability":"Use when demand or backlog exceeds healthy service capacity.","prerequisites":["Confirm quota and downstream capacity","Establish the current utilization baseline"],"diagnostics":["Inspect CPU, memory, queue depth, and throttling","Confirm the bottleneck is the selected service"],"steps":["Increase replicas or worker capacity within approved limits","Drain backlog while watching downstream saturation"],"validation":["Backlog decreases","Latency, CPU, and memory remain within SLO"],"rollback":["Return capacity to the prior level after demand stabilizes"]},
    {"id":"dependency-recovery","title":"Recover failing dependency","patterns":["database","mysql","redis","rabbitmq","dependency","connection","timeout"],"risk":"high","applicability":"Use when evidence identifies an unhealthy database, cache, broker, or upstream API.","prerequisites":["Confirm dependency ownership and maintenance state","Preserve connection and error evidence"],"diagnostics":["Check dependency health, connections, capacity, and recent changes","Test connectivity from the affected workload"],"steps":["Apply the dependency-specific approved recovery procedure","Restore clients gradually and watch retry pressure"],"validation":["Dependency health checks pass","Client errors and retries return to baseline"],"rollback":["Isolate the dependency and restore the previous healthy configuration"]},
    {"id":"investigate-first","title":"Collect targeted diagnostics","patterns":[],"risk":"low","applicability":"Use when evidence is insufficient for a safe corrective change.","prerequisites":["Keep the incident open and preserve timestamps"],"diagnostics":["Collect logs, metrics, traces, deployment changes, and dependency health","Compare against a healthy baseline"],"steps":["Do not change production until the failing component is confirmed","Return the new evidence to the resolution agent"],"validation":["A testable root-cause hypothesis is established"],"rollback":["No rollback required because this option makes no production change"]},
)


def relevant_resolutions(*, issue: str, service: str, recommended_action: str = "") -> list[dict[str, Any]]:
    corpus = f"{issue} {service} {recommended_action}".lower()
    ranked = []
    for option in RESOLUTION_CATALOG:
        matches = [pattern for pattern in option["patterns"] if pattern in corpus]
        score = len(matches) * 0.18 + (0.2 if option["id"] == "investigate-first" else 0.0)
        ranked.append({**option, "match_reasons": matches, "relevance": round(min(0.98, score), 2)})
    ranked.sort(key=lambda item: item["relevance"], reverse=True)
    return ranked[:4]


def prepare_resolution_plan(*, option_id: str, issue: str, service: str) -> dict[str, Any]:
    option = next((row for row in RESOLUTION_CATALOG if row["id"] == option_id), None)
    if option is None:
        raise ValueError(f"Unknown resolution option: {option_id}")
    return {
        **option,
        "issue": issue,
        "service": service,
        "plan": [
            *[{"phase": "diagnose", "instruction": step} for step in option["diagnostics"]],
            *[{"phase": "remediate", "instruction": step} for step in option["steps"]],
            *[{"phase": "validate", "instruction": step} for step in option["validation"]],
        ],
        "agent_status": "prepared_for_operator_review",
    }
