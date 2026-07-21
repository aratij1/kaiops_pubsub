from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "e2e" / "etl_orders_input.csv"
DEFAULT_RUNBOOK = ROOT / "docs" / "e2e" / "etl-order-quality-runbook.md"


def now_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def http_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 20.0) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url=url, method=method, data=body, headers=headers)
    with urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def unwrap_gateway(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def run_command(args: list[str], *, input_text: str | None = None, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        text=True,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def docker_compose_container(service: str) -> str:
    result = run_command(
        [
            "docker",
            "compose",
            "--profile",
            "application-layer",
            "--profile",
            "ai-layer",
            "--env-file",
            ".env",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.layered.yml",
            "ps",
            "-q",
            service,
        ],
        timeout=30.0,
    )
    if result.returncode != 0:
        raise RuntimeError(f"docker compose ps failed: {result.stderr.strip()}")
    container = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not container:
        raise RuntimeError(f"No running container found for service {service}")
    return container


def load_etl_rows(input_path: Path) -> tuple[list[dict[str, str]], dict[str, Any]]:
    rows: list[dict[str, str]] = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            customer_id = str(row.get("customer_id") or "").strip()
            amount_raw = str(row.get("amount") or "").strip()
            dq_reasons: list[str] = []
            try:
                amount = float(amount_raw)
            except ValueError:
                amount = 0.0
                dq_reasons.append("invalid_amount")
            if not customer_id:
                dq_reasons.append("missing_customer_id")
            if amount < 0:
                dq_reasons.append("negative_amount")
            row["dq_status"] = "rejected" if dq_reasons else "accepted"
            row["dq_reason"] = "|".join(dq_reasons) if dq_reasons else ""
            rows.append(row)

    total = len(rows)
    rejected = sum(1 for row in rows if row["dq_status"] == "rejected")
    null_customer = sum(1 for row in rows if not str(row.get("customer_id") or "").strip())
    return rows, {
        "total_rows": total,
        "rejected_rows": rejected,
        "null_customer_rows": null_customer,
        "null_customer_ratio": round(null_customer / total, 4) if total else 0,
    }


def sql_quote(value: Any) -> str:
    return "'" + str(value or "").replace("\\", "\\\\").replace("'", "''") + "'"


def load_mysql_table(project_name: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    table = "etl_order_quality_events"
    statements = [
        f"CREATE TABLE IF NOT EXISTS {table} ("
        "id BIGINT AUTO_INCREMENT PRIMARY KEY,"
        "project_name VARCHAR(128) NOT NULL,"
        "order_id VARCHAR(64) NOT NULL,"
        "customer_id VARCHAR(128) NULL,"
        "amount DECIMAL(12,2) NOT NULL,"
        "status VARCHAR(32) NOT NULL,"
        "region VARCHAR(64) NOT NULL,"
        "event_ts VARCHAR(64) NOT NULL,"
        "dq_status VARCHAR(32) NOT NULL,"
        "dq_reason VARCHAR(255) NULL,"
        "loaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ");",
        f"DELETE FROM {table} WHERE project_name = {sql_quote(project_name)};",
    ]
    for row in rows:
        statements.append(
            f"INSERT INTO {table} "
            "(project_name, order_id, customer_id, amount, status, region, event_ts, dq_status, dq_reason) VALUES "
            f"({sql_quote(project_name)}, {sql_quote(row['order_id'])}, {sql_quote(row.get('customer_id'))}, "
            f"{float(row.get('amount') or 0)}, {sql_quote(row['status'])}, {sql_quote(row['region'])}, "
            f"{sql_quote(row['event_ts'])}, {sql_quote(row['dq_status'])}, {sql_quote(row['dq_reason'])});"
        )
    statements.append(
        f"SELECT COUNT(*) AS total_rows, "
        f"SUM(CASE WHEN dq_status='rejected' THEN 1 ELSE 0 END) AS rejected_rows, "
        f"SUM(CASE WHEN customer_id='' OR customer_id IS NULL THEN 1 ELSE 0 END) AS null_customer_rows "
        f"FROM {table} WHERE project_name = {sql_quote(project_name)};"
    )
    mysql_container = docker_compose_container("mysql")
    result = run_command(
        ["docker", "exec", "-i", mysql_container, "mysql", "-ukaiops", "-pkaiops", "kaiops"],
        input_text="\n".join(statements),
        timeout=60.0,
    )
    if result.returncode != 0:
        raise RuntimeError(f"MySQL ETL load failed: {result.stderr.strip()}")
    return {"table": table, "mysql_output": result.stdout.strip()}


def build_knowledge_doc(project_name: str, runbook_text: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": f"{project_name}-etl-data-quality-runbook.md",
        "kind": "runbook",
        "category": "knowledge_pack",
        "text": (
            runbook_text.replace("etl-orders-dq", project_name)
            + "\n\n## Current E2E Batch Evidence\n"
            + f"- total_rows: {metrics['total_rows']}\n"
            + f"- rejected_rows: {metrics['rejected_rows']}\n"
            + f"- null_customer_ratio: {metrics['null_customer_ratio']}\n"
        ),
        "excerpt": "Order ETL data quality runbook with null customer, rejected row, rollback, and validation checks.",
    }


def onboard_project(gateway_url: str, project_name: str, doc: dict[str, Any]) -> dict[str, Any]:
    requirements = [
        f"Create a critical Prometheus alert named {project_name}_null_customer_ratio_high when null customer ID ratio is above 20 percent for 5 minutes.",
        f"Create a high Prometheus alert named {project_name}_rejected_rows_detected when rejected ETL rows are greater than zero.",
        f"Create a warning Prometheus alert named {project_name}_etl_load_latency_high when ETL load latency is above 120 seconds.",
    ]
    payload = {
        "project_mode": "new",
        "onboarding_path": "setup_monitoring",
        "start_rules_onboarding": True,
        "selected_monitoring_tool": "prometheus",
        "plain_language_requirements": requirements,
        "source_documents": [doc],
        "generate_documents": True,
        "include_smoke_test_alert": True,
        "connectivity": {
            "project": {
                "name": project_name,
                "owner_team": "data-platform",
                "environment": "prod",
                "region": "us-east-1",
            },
            "deployment_mode": "on_prem",
            "prometheus_url": "http://prometheus:9090",
            "new_relic_url": "",
            "datadog_url": "",
            "active_provider": "prometheus",
            "provider_statuses": {
                "prometheus": {"ok": True, "message": "Local Prometheus configured for ETL E2E"},
            },
            "user_assignments": {
                "l2.operator": [project_name],
                "l3.engineer": [project_name],
                "administrator": [project_name],
            },
        },
    }
    return unwrap_gateway(http_json(f"{gateway_url}/onboarding/complete", method="POST", payload=payload, timeout=90.0))


def approve_knowledge_pack(gateway_url: str, project_name: str, doc: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "service": project_name,
        "environment": "prod",
        "owner_team": "data-platform",
        "approved_by": "e2e-admin",
        "documents": [
            {
                "name": doc["name"],
                "category": "knowledge_pack",
                "text": doc["text"],
                "excerpt": doc["excerpt"],
            }
        ],
    }
    return unwrap_gateway(http_json(f"{gateway_url}/knowledge-pack/approve", method="POST", payload=payload, timeout=60.0))


def ingest_generated_rag_docs(gateway_url: str, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        try:
            result = unwrap_gateway(http_json(f"{gateway_url}/rag/documents", method="POST", payload=doc, timeout=30.0))
            results.append(result if isinstance(result, dict) else {"result": result})
        except Exception as exc:
            results.append({"status": "failed", "error": str(exc), "title": doc.get("title")})
    return results


def send_etl_alert(gateway_url: str, project_name: str, metrics: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "source": "prometheus",
        "name": f"{project_name}_RejectedRowsDetected",
        "service": project_name,
        "environment": "prod",
        "severity": "critical",
        "description": (
            f"ETL rejected_rows={metrics['rejected_rows']} and null_customer_ratio={metrics['null_customer_ratio']} "
            "after landing the order input file."
        ),
        "labels": {
            "alertname": f"{project_name}_RejectedRowsDetected",
            "service": project_name,
            "project": project_name,
            "environment": "prod",
            "severity": "critical",
            "pipeline": "orders-etl",
            "table": "etl_order_quality_events",
        },
        "annotations": {
            "summary": "Order ETL data quality violation",
            "description": "Rejected ETL rows were loaded to MySQL and should be triaged with the service knowledge pack.",
            "runbook": f"{project_name} ETL data quality runbook",
        },
    }
    return unwrap_gateway(http_json(f"{gateway_url}/api/v1/alerts/prometheus", method="POST", payload=payload, timeout=30.0))


def wait_for_recent_alert(gateway_url: str, project_name: str, timeout_seconds: float = 90.0) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        payload = unwrap_gateway(http_json(f"{gateway_url}/alerts/recent?limit=200", timeout=20.0))
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and str(row.get("service") or "") == project_name:
                return row
        last = payload if isinstance(payload, dict) else {"payload": payload}
        time.sleep(5)
    raise RuntimeError(f"Timed out waiting for recent alert for {project_name}. Last response: {json.dumps(last)[:500]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and verify an ETL admin monitoring/RAG/rules E2E project.")
    parser.add_argument("--project-name", default=f"etl-orders-dq-{now_slug()}")
    parser.add_argument("--gateway-url", default="http://localhost:8010")
    parser.add_argument("--input-file", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--runbook-file", type=Path, default=DEFAULT_RUNBOOK)
    args = parser.parse_args()

    rows, metrics = load_etl_rows(args.input_file)
    mysql_result = load_mysql_table(args.project_name, rows)
    doc = build_knowledge_doc(args.project_name, args.runbook_file.read_text(encoding="utf-8"), metrics)
    onboarding = onboard_project(args.gateway_url.rstrip("/"), args.project_name, doc)
    knowledge = approve_knowledge_pack(args.gateway_url.rstrip("/"), args.project_name, doc)
    generated_docs = onboarding.get("rag_documents", []) if isinstance(onboarding, dict) else []
    rag_ingest = ingest_generated_rag_docs(args.gateway_url.rstrip("/"), generated_docs if isinstance(generated_docs, list) else [])
    sync = unwrap_gateway(http_json(f"{args.gateway_url.rstrip('/')}/rag/index/sync", method="POST", payload={}, timeout=60.0))
    search = unwrap_gateway(
        http_json(
            f"{args.gateway_url.rstrip('/')}/rag/search?query={quote(args.project_name + ' rejected rows null customer ETL')}&limit=8",
            timeout=30.0,
        )
    )
    alert_ingest = send_etl_alert(args.gateway_url.rstrip("/"), args.project_name, metrics)
    recent_alert = wait_for_recent_alert(args.gateway_url.rstrip("/"), args.project_name)
    state = unwrap_gateway(http_json(f"{args.gateway_url.rstrip('/')}/onboarding/state", timeout=30.0))
    state_rows = [row for row in state.get("rows", []) if isinstance(row, dict) and row.get("project_name") == args.project_name] if isinstance(state, dict) else []

    search_matches = search.get("matches", search.get("rows", [])) if isinstance(search, dict) else []
    if not search_matches and isinstance(search, dict):
        search_matches = search.get("data", {}).get("matches", []) if isinstance(search.get("data"), dict) else []

    result = {
        "ok": bool(state_rows) and bool(recent_alert) and bool(search_matches),
        "project_name": args.project_name,
        "etl": {
            "input_file": str(args.input_file),
            "rows_loaded": len(rows),
            "quality_metrics": metrics,
            "mysql": mysql_result,
        },
        "admin_monitoring": {
            "onboarding_status": onboarding.get("rules_onboarding", {}).get("status") if isinstance(onboarding, dict) else None,
            "workflow_id": onboarding.get("rules_onboarding", {}).get("workflow_id") if isinstance(onboarding, dict) else None,
            "generated_rule_count": len(onboarding.get("rules_onboarding", {}).get("result", {}).get("generated_rules", [])) if isinstance(onboarding, dict) else 0,
            "generated_document_count": len(generated_docs) if isinstance(generated_docs, list) else 0,
            "state_rows": len(state_rows),
        },
        "knowledge": {
            "approval_status": knowledge.get("status") if isinstance(knowledge, dict) else None,
            "rag_ingest_results": rag_ingest,
            "rag_sync": sync,
            "search_match_count": len(search_matches) if isinstance(search_matches, list) else 0,
            "top_match": search_matches[0] if isinstance(search_matches, list) and search_matches else None,
        },
        "alert_flow": {
            "ingest": alert_ingest,
            "recent_alert": recent_alert,
        },
    }
    print(json.dumps(result, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HTTPError, URLError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(2)
