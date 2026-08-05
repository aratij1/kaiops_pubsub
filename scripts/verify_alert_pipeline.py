from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass
class PipelineSnapshot:
    metric_found: bool
    metric_value: float | None
    prometheus_alert_found: bool
    prometheus_states: list[str]
    alertmanager_found: bool
    gateway_found: bool
    gateway_rows_count: int
    gateway_match: dict[str, Any] | None


def _http_json(url: str, *, timeout_seconds: float) -> Any:
    req = Request(url=url, method="GET")
    with urlopen(req, timeout=timeout_seconds) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _query_metric(prometheus_url: str, metric_query: str, timeout_seconds: float) -> tuple[bool, float | None]:
    encoded_query = quote(metric_query, safe="")
    payload = _http_json(f"{prometheus_url.rstrip('/')}/api/v1/query?query={encoded_query}", timeout_seconds=timeout_seconds)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    result = data.get("result", []) if isinstance(data, dict) else []
    if not isinstance(result, list) or not result:
        return False, None
    first = result[0] if isinstance(result[0], dict) else {}
    value = first.get("value") if isinstance(first, dict) else None
    if isinstance(value, list) and len(value) >= 2:
        return True, _to_float(value[1])
    return True, None


def _query_prometheus_alert(prometheus_url: str, alert_name: str, timeout_seconds: float) -> tuple[bool, list[str]]:
    payload = _http_json(f"{prometheus_url.rstrip('/')}/api/v1/alerts", timeout_seconds=timeout_seconds)
    alerts = (((payload or {}).get("data") or {}).get("alerts") or []) if isinstance(payload, dict) else []
    if not isinstance(alerts, list):
        return False, []
    states: list[str] = []
    for item in alerts:
        if not isinstance(item, dict):
            continue
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        if str(labels.get("alertname") or "") != alert_name:
            continue
        states.append(str(item.get("state") or "unknown"))
    return (len(states) > 0), sorted(set(states))


def _query_alertmanager(alertmanager_url: str, alert_name: str, timeout_seconds: float) -> bool:
    payload = _http_json(f"{alertmanager_url.rstrip('/')}/api/v2/alerts", timeout_seconds=timeout_seconds)
    alerts = payload if isinstance(payload, list) else []
    for item in alerts:
        if not isinstance(item, dict):
            continue
        labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
        if str(labels.get("alertname") or "") == alert_name:
            return True
    return False


def _query_gateway_recent(gateway_url: str, alert_name: str, limit: int, timeout_seconds: float) -> tuple[bool, int, dict[str, Any] | None]:
    # The recent feed is deliberately bounded and can evict the target during a
    # load test. Fall back to the durable database-backed feed before declaring
    # an end-to-end delivery failure.
    largest_row_count = 0
    for path, query_limit in (("alerts/recent", limit), ("alerts/all", max(limit, 5000))):
        payload = _http_json(
            f"{gateway_url.rstrip('/')}/{path}?limit={query_limit}",
            timeout_seconds=timeout_seconds,
        )
        data = payload.get("data") if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            continue
        rows = data.get("rows")
        if not isinstance(rows, list):
            continue
        largest_row_count = max(largest_row_count, len(rows))
        for row in rows:
            if isinstance(row, dict) and str(row.get("name") or "") == alert_name:
                return True, len(rows), row
    return False, largest_row_count, None


def collect_snapshot(args: argparse.Namespace) -> PipelineSnapshot:
    metric_query = f"{args.metric_name}{{database=\"{args.database}\",table=\"{args.table}\"}}"
    metric_found, metric_value = _query_metric(args.prometheus_url, metric_query, args.request_timeout_seconds)
    prom_found, prom_states = _query_prometheus_alert(args.prometheus_url, args.alert_name, args.request_timeout_seconds)
    am_found = _query_alertmanager(args.alertmanager_url, args.alert_name, args.request_timeout_seconds)
    gw_found, gw_rows_count, gw_match = _query_gateway_recent(
        args.gateway_url,
        args.alert_name,
        args.gateway_limit,
        args.request_timeout_seconds,
    )
    return PipelineSnapshot(
        metric_found=metric_found,
        metric_value=metric_value,
        prometheus_alert_found=prom_found,
        prometheus_states=prom_states,
        alertmanager_found=am_found,
        gateway_found=gw_found,
        gateway_rows_count=gw_rows_count,
        gateway_match=gw_match,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate end-to-end alert flow: Prometheus -> Alertmanager -> KaiOps recent alerts")
    parser.add_argument("--alert-name", default="KaiOpsMySQLAlertsTableRowsHigh")
    parser.add_argument("--metric-name", default="kaiops_mysql_alerts_table_rows")
    parser.add_argument("--database", default="kaiops")
    parser.add_argument("--table", default="alerts")
    parser.add_argument("--prometheus-url", default="http://localhost:9090")
    parser.add_argument("--alertmanager-url", default="http://localhost:9093")
    parser.add_argument("--gateway-url", default="http://localhost:8010")
    parser.add_argument("--gateway-limit", type=int, default=500)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--request-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--mode", choices=["strict", "sanity"], default="strict")
    parser.add_argument("--minimum-metric-value", type=float, default=1.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    deadline = time.time() + max(1.0, float(args.timeout_seconds))
    last_snapshot: PipelineSnapshot | None = None

    while time.time() <= deadline:
        try:
            snapshot = collect_snapshot(args)
            last_snapshot = snapshot
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            time.sleep(max(0.1, float(args.poll_interval_seconds)))
            continue
        except Exception as exc:  # pragma: no cover
            print(json.dumps({"ok": False, "error": f"unexpected: {exc}"}, indent=2))
            time.sleep(max(0.1, float(args.poll_interval_seconds)))
            continue

        strict_ok = snapshot.metric_found and snapshot.prometheus_alert_found and snapshot.alertmanager_found and snapshot.gateway_found
        metric_value_ok = snapshot.metric_value is not None and snapshot.metric_value >= args.minimum_metric_value
        sanity_ok = snapshot.metric_found and metric_value_ok and snapshot.gateway_rows_count > 0
        ok = strict_ok if args.mode == "strict" else sanity_ok
        print(
            json.dumps(
                {
                    "ok": ok,
                    "mode": args.mode,
                    "alert_name": args.alert_name,
                    "metric_found": snapshot.metric_found,
                    "metric_value": snapshot.metric_value,
                    "minimum_metric_value": args.minimum_metric_value,
                    "prometheus_alert_found": snapshot.prometheus_alert_found,
                    "prometheus_states": snapshot.prometheus_states,
                    "alertmanager_found": snapshot.alertmanager_found,
                    "gateway_found": snapshot.gateway_found,
                    "gateway_rows_count": snapshot.gateway_rows_count,
                    "gateway_match": snapshot.gateway_match,
                    "strict_ok": strict_ok,
                    "sanity_ok": sanity_ok,
                },
                indent=2,
            )
        )
        if ok:
            return 0
        time.sleep(max(0.1, float(args.poll_interval_seconds)))

    if last_snapshot is None:
        print(json.dumps({"ok": False, "error": "no successful snapshot collected"}, indent=2))
        return 2

    print("Timed out before full pipeline verification completed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
