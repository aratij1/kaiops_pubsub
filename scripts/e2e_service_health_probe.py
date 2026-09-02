from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


HTTP_SERVICES = {
    "api-gateway": "http://api-gateway:8000/healthz",
    "monitoring-adapter": "http://monitoring-adapter:8000/healthz",
    "monitoring-ingestion-worker": "http://monitoring-ingestion-worker:8000/healthz",
    "alert-intelligence": "http://alert-intelligence:8000/healthz",
    "orchestrator": "http://orchestrator:8000/healthz",
    "context-agent": "http://context-agent:8000/healthz",
    "resolution-agent": "http://resolution-agent:8000/healthz",
    "approval-service": "http://approval-service:8000/healthz",
    "remediation-engine": "http://remediation-engine:8000/healthz",
    "closure-service": "http://closure-service:8000/healthz",
    "notification-service": "http://notification-service:8000/healthz",
    "model-router": "http://model-router:8000/healthz",
    "evaluation-service": "http://evaluation-service:8000/healthz",
    "application-onboarding": "http://application-onboarding:8000/healthz",
    "discovery-service": "http://discovery-service:8000/healthz",
    "discovery-mcp": "http://discovery-mcp:8000/healthz",
    "knowledge-development-worker": "http://knowledge-development-worker:8000/healthz",
    "metrics-validation-agent": "http://metrics-validation-agent:8000/healthz",
    "rule-generation-agent": "http://rule-generation-agent:8000/healthz",
    "prometheus-config-service": "http://prometheus-config-service:8000/healthz",
    "validation-agent": "http://validation-agent:8000/healthz",
    "dashboard-generator": "http://dashboard-generator:8000/healthz",
    "audit-service": "http://audit-service:8000/healthz",
    "alertmanager": "http://alertmanager:9093/-/ready",
    "prometheus": "http://prometheus:9090/-/ready",
    "jaeger": "http://jaeger:16686/",
    "jenkins": "http://jenkins:8080/login",
    "ui": "http://ui/",
}

OPTIONAL_HTTP_SERVICES = {
    "grafana": "http://grafana:3000/api/health",
}


def main() -> int:
    services = dict(HTTP_SERVICES)
    if os.getenv("E2E_INCLUDE_OPTIONAL_SERVICES", "").strip().lower() in {"1", "true", "yes"}:
        services.update(OPTIONAL_HTTP_SERVICES)
    results = []
    for service, url in services.items():
        last_error = None
        for attempt in range(3):
            try:
                with urlopen(url, timeout=15) as response:
                    response.read(4096)
                    status = response.status
                results.append({"service": service, "ok": 200 <= status < 400, "status": status, "attempts": attempt + 1})
                break
            except HTTPError as exc:
                last_error = {"service": service, "ok": False, "status": exc.code, "error": str(exc)}
            except (URLError, TimeoutError, OSError) as exc:
                last_error = {"service": service, "ok": False, "status": None, "error": str(exc)}
            time.sleep(1)
        else:
            results.append(last_error)

    failed = [row for row in results if not row["ok"]]
    print(json.dumps({"passed": len(results) - len(failed), "total": len(results), "failed": failed, "results": results}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
