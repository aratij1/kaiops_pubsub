from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta, timezone
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
    parser = argparse.ArgumentParser(description="Probe alert arrival through incident RCA without relying on host port forwarding")
    parser.add_argument("--gateway", default="http://api-gateway:8000")
    parser.add_argument("--monitoring", default="http://monitoring-adapter:8000")
    parser.add_argument("--alertmanager", default="http://alertmanager:9093")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="Admin@123456")
    parser.add_argument("--wait-seconds", type=int, default=240)
    parser.add_argument(
        "--include-live-remediation",
        action="store_true",
        help="Approve the recommendation and allow configured remediation side effects.",
    )
    args = parser.parse_args()

    suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    name = f"KaiOpsE2ELifecycle-{suffix}"
    now = datetime.now(timezone.utc)
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
            "service": "e2e-lifecycle-service",
            "severity": "critical",
            "application": "KaiOps",
            "project_name": "KaiOps",
            "environment": "prod",
        },
        "annotations": {"summary": name, "description": "E2E lifecycle handoff verification"},
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
    stages["context"] = {"ok": bool(context), "evidence_present": bool((context.get("metadata") or {}).get("discovery_evidence"))}
    if context and not recommendation.get("id"):
        status, recommendation_payload = request_json(
            "http://resolution-agent:8000/resolve?publish_events=true",
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

    if stages.get("approval", {}).get("ok"):
        completion = 0
        final_status = ""
        closure_deadline = time.time() + args.wait_seconds
        while time.time() < closure_deadline:
            status, payload = request_json(
                f"{args.gateway}/incidents/{incident.get('id')}/stage-completeness", token=token, timeout=45
            )
            if status == 200:
                completion = int(((unwrap(payload).get("stage_completion") or {}).get("percentage")) or 0)
            status, payload = request_json(f"{args.gateway}/alerts/all?limit=5000", token=token, timeout=45)
            rows = unwrap(payload).get("rows", []) if status == 200 else []
            final_row = next((item for item in rows if item.get("id") == alert_id), None)
            final_status = str((final_row or {}).get("status") or "")
            if completion == 100 and final_status == "closed":
                break
            time.sleep(2)
        stages["remediation_and_closure"] = {
            "ok": completion == 100 and final_status == "closed",
            "completion": completion,
            "alert_status": final_status,
        }

    required = ("live_stream", "incident", "context", "rca")
    if args.include_live_remediation:
        required += ("approval", "remediation_and_closure")
    stages["result"] = "pass" if all(stages.get(key, {}).get("ok") for key in required) else "fail"
    print(json.dumps(stages, indent=2, default=str))
    return 0 if stages["result"] == "pass" else 5


if __name__ == "__main__":
    raise SystemExit(main())
