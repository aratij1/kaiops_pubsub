from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request_json(url: str, *, method: str = "GET", payload: object | None = None, token: str = "", timeout: int = 30):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        return exc.code, detail


def unwrap(payload):
    return payload.get("data", payload) if isinstance(payload, dict) else payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe alert arrival through incident RCA without relying on host port forwarding"
    )
    parser.add_argument("--gateway", default="http://api-gateway:8000")
    parser.add_argument("--monitoring", default="http://monitoring-adapter:8000")
    parser.add_argument("--alertmanager", default="http://alertmanager:9093")
    parser.add_argument("--resolution", default="http://resolution-agent:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="Admin@123456")
    parser.add_argument("--wait-seconds", type=int, default=240)
    parser.add_argument(
        "--include-live-remediation",
        action="store_true",
        help="Approve the recommendation and allow configured remediation side effects.",
    )
    args = parser.parse_args()

    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    name = f"ServiceDown-E2E-{suffix}"
    service = "kaiops-discovery-mcp"
    environment = f"e2e-{suffix}"
    now = datetime.now(UTC)
    stages: dict[str, object] = {"name": name}

    status, login = request_json(
        f"{args.gateway}/auth/login",
        method="POST",
        payload={"username": args.username, "password": args.password, "device": "e2e-lifecycle-probe"},
    )
    token = str(login.get("access_token") or "") if isinstance(login, dict) else ""
    stages["login"] = {"ok": status == 200 and bool(token), "status": status}
    if not token:
        print(json.dumps(stages, indent=2))
        return 2

    alert = [{
        "labels": {
            "alertname": name,
            "service": service,
            "severity": "critical",
            "application": "KaiOps",
            "project_name": "KaiOps",
            "environment": environment,
        },
        "annotations": {"summary": name, "description": f"{service} is unreachable; endpoint down"},
        "startsAt": now.isoformat(),
        "endsAt": (now + timedelta(minutes=10)).isoformat(),
        "generatorURL": "http://prometheus:9090/graph?g0.expr=vector(1)",
    }]
    status, response = request_json(f"{args.alertmanager}/api/v2/alerts", method="POST", payload=alert)
    stages["alertmanager"] = {"ok": 200 <= status < 300, "status": status}
    if not 200 <= status < 300:
        stages["alertmanager"]["response"] = response
        print(json.dumps(stages, indent=2))
        return 3

    deadline = time.time() + args.wait_seconds
    row = None
    while time.time() < deadline and row is None:
        status, payload = request_json(f"{args.gateway}/alerts/all?limit=5000", token=token, timeout=45)
        rows = unwrap(payload).get("rows", []) if status == 200 else []
        row = next((item for item in rows if item.get("name") == name), None)
        if row is None:
            time.sleep(2)
    stages["live_stream"] = {"ok": row is not None, "alert_id": row.get("id") if row else None}
    if row is None:
        print(json.dumps(stages, indent=2))
        return 4

    alert_id = row["id"]
    processed = None
    while time.time() < deadline:
        status, payload = request_json(f"{args.monitoring}/alerts/{alert_id}/processed-result", timeout=45)
        if status == 200:
            processed = payload
            if processed.get("context"):
                break
        time.sleep(2)

    incident = (processed or {}).get("incident") or {}
    context = (processed or {}).get("context") or {}
    recommendation = (processed or {}).get("recommendation") or {}
    stages["incident"] = {"ok": bool(incident.get("id")), "incident_id": incident.get("id")}
    stages["context"] = {
        "ok": bool(context),
        "evidence_present": bool((context.get("metadata") or {}).get("discovery_evidence")),
    }
    if context and not recommendation.get("id"):
        status, recommendation_payload = request_json(
            f"{args.resolution.rstrip('/')}/resolve?publish_events=true",
            method="POST",
            payload=context,
            timeout=180,
        )
        stages["rca_regeneration"] = {"ok": status == 200, "status": status}
        if status == 200 and isinstance(recommendation_payload, dict):
            recommendation = recommendation_payload
        else:
            stages["rca_regeneration"]["response"] = recommendation_payload
    stages["rca"] = {"ok": bool(recommendation.get("id")), "recommendation_id": recommendation.get("id")}
    execution_plan = (recommendation.get("metadata") or {}).get("execution_plan") or {}
    stages["execution_plan"] = {
        "ok": execution_plan.get("execution_ready") is True and bool(execution_plan.get("commands")),
        "playbook_id": ((execution_plan.get("playbook") or {}).get("id")),
        "execution_ready": execution_plan.get("execution_ready"),
        "readiness_blocks": execution_plan.get("readiness_blocks") or [],
    }
    if stages["rca"]["ok"] and args.include_live_remediation:
        status, approval = request_json(
            f"{args.gateway}/approval/approve",
            method="POST",
            token=token,
            payload={
                "incident_id": incident.get("id"),
                "recommendation_id": recommendation.get("id"),
                "approver": "admin",
                "channel": "web",
                "comment": "approved by end-to-end lifecycle probe",
            },
            timeout=60,
        )
        stages["approval"] = {"ok": status == 200, "status": status}
        if status != 200:
            stages["approval"]["response"] = approval

        approved = unwrap(approval) if isinstance(approval, dict) else {}
        if stages["approval"]["ok"] and stages["execution_plan"]["ok"]:
            commands = [str(item) for item in execution_plan.get("commands", []) if str(item).strip()]
            scripts = [str(item) for item in execution_plan.get("scripts", []) if str(item).strip()]
            connector = ((execution_plan.get("connection") or {}).get("connector") or {})
            execution_payload = {
                "id": approved.get("id"),
                "incident_id": incident.get("id"),
                "recommendation_id": recommendation.get("id"),
                "decision": "approved",
                "approver": "admin",
                "channel": "web",
                "comment": "execute exact plan approved by end-to-end lifecycle probe",
                "modified_action": "\n".join(commands + scripts),
                "metadata": {
                    "recommended_action": recommendation.get("recommended_action"),
                    "recommended_commands": commands + [f"script: {item}" for item in scripts],
                    "execution_plan": execution_plan,
                    "rollback_plan": execution_plan.get("rollback_commands") or [],
                    "service": service,
                    "environment": environment,
                    "remediation_target": service,
                    "connection_profile": {
                        "application": "KaiOps",
                        "service": service,
                        "environment": environment,
                        "namespace": "default",
                        "endpoint_url": "http://jenkins:8080",
                        "connection_type": "jenkins",
                        "executor_type": "jenkins",
                        "job_name": "kaiops-auto-remediation",
                        "timeout_seconds": 1200,
                        "credential_ref": connector.get("secret_ref") or "vault://kaiops/local/jenkins#api-token",
                        "allowed_operations": connector.get("allowed_operations") or [],
                    },
                },
            }
            status, execution = request_json(
                f"{args.gateway}/remediation/execute",
                method="POST",
                token=token,
                payload=execution_payload,
                timeout=180,
            )
            submitted = unwrap(execution) if isinstance(execution, dict) else {}
            stages["execution_submission"] = {
                "ok": status in {200, 202} and bool(submitted.get("id")),
                "status": status,
                "action_id": submitted.get("id"),
                "action_status": submitted.get("status"),
            }
            if not stages["execution_submission"]["ok"]:
                stages["execution_submission"]["response"] = execution
        elif stages["approval"]["ok"]:
            stages["execution_submission"] = {
                "ok": False,
                "status": 409,
                "response": "approved recommendation did not contain an execution-ready catalog plan",
            }

    if stages.get("execution_submission", {}).get("ok"):
        completion = 0
        final_status = ""
        action_status = ""
        closure_complete = False
        incident_status = ""
        closure_deadline = time.time() + args.wait_seconds
        while time.time() < closure_deadline:
            status, payload = request_json(
                f"{args.gateway}/incidents/{incident.get('id')}/stage-completeness", token=token, timeout=45
            )
            if status == 200:
                stage_data = unwrap(payload)
                completion = int(((stage_data.get("stage_completion") or {}).get("percentage")) or 0)
                incident_status = str(stage_data.get("status") or "").lower()
                closure_stage = next(
                    (item for item in stage_data.get("stages", []) if item.get("stage") == "closure_completed"),
                    {},
                )
                closure_complete = closure_stage.get("state") == "complete"
            status, payload = request_json(f"{args.gateway}/alerts/all?limit=5000", token=token, timeout=45)
            rows = unwrap(payload).get("rows", []) if status == 200 else []
            final_row = next((item for item in rows if item.get("id") == alert_id), None)
            final_status = str((final_row or {}).get("status") or "")
            status, payload = request_json(
                f"{args.gateway}/remediation/actions/by-incident/{incident.get('id')}/latest",
                token=token,
                timeout=45,
            )
            if status == 200:
                action_status = str((unwrap(payload) or {}).get("status") or "").lower()
            if completion == 100 and closure_complete and action_status == "succeeded" and incident_status in {"closed", "resolved"}:
                break
            time.sleep(2)
        stages["remediation_and_closure"] = {
            "ok": (
                completion == 100
                and closure_complete
                and action_status == "succeeded"
                and incident_status in {"closed", "resolved"}
            ),
            "completion": completion,
            "alert_status": final_status,
            "incident_status": incident_status,
            "closure_stage_complete": closure_complete,
            "action_status": action_status,
        }

    required = ("live_stream", "incident", "context", "rca", "execution_plan")
    if args.include_live_remediation:
        required += ("approval", "execution_submission", "remediation_and_closure")
    stages["result"] = "pass" if all(stages.get(key, {}).get("ok") for key in required) else "fail"
    print(json.dumps(stages, indent=2, default=str))
    return 0 if stages["result"] == "pass" else 5


if __name__ == "__main__":
    raise SystemExit(main())
