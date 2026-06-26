from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Any

import aiomysql
import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "")
MYSQL_POLL_SECONDS = max(5, int(os.getenv("MYSQL_POLL_SECONDS", "15")))
MYSQL_CONNECT_TIMEOUT = float(os.getenv("MYSQL_CONNECT_TIMEOUT", "5"))
MYSQL_ALERTS_ENABLED = os.getenv("MYSQL_ALERTS_ENABLED", "true").strip().lower() == "true"
MYSQL_ALERT_COOLDOWN_SECONDS = max(30, int(os.getenv("MYSQL_ALERT_COOLDOWN_SECONDS", "300")))
MYSQL_THREADS_RUNNING_THRESHOLD = max(1, int(os.getenv("MYSQL_THREADS_RUNNING_THRESHOLD", "40")))
MYSQL_SLOW_QUERIES_DELTA_THRESHOLD = max(1, int(os.getenv("MYSQL_SLOW_QUERIES_DELTA_THRESHOLD", "5")))
MYSQL_ABORTED_CONNECTS_DELTA_THRESHOLD = max(1, int(os.getenv("MYSQL_ABORTED_CONNECTS_DELTA_THRESHOLD", "3")))
KAIOPS_ALERT_ENDPOINT = os.getenv("KAIOPS_ALERT_ENDPOINT", "http://localhost:8010/alerts")
KAIOPS_ALERT_TIMEOUT_SECONDS = float(os.getenv("KAIOPS_ALERT_TIMEOUT_SECONDS", "8"))

REQUEST_COUNT = Counter(
    "mysql_monitor_requests_total",
    "HTTP request count by endpoint",
    ["endpoint"],
)
REQUEST_LATENCY = Histogram(
    "mysql_monitor_request_latency_seconds",
    "Latency by endpoint",
    ["endpoint"],
)
DB_UP = Gauge("mysql_monitor_db_up", "MySQL availability: 1 up, 0 down")
DB_THREADS_CONNECTED = Gauge("mysql_monitor_threads_connected", "MySQL Threads_connected")
DB_THREADS_RUNNING = Gauge("mysql_monitor_threads_running", "MySQL Threads_running")
DB_UPTIME_SECONDS = Gauge("mysql_monitor_uptime_seconds", "MySQL server uptime in seconds")
DB_QUERIES_TOTAL = Gauge("mysql_monitor_queries_total", "MySQL Queries status counter")
DB_SLOW_QUERIES_TOTAL = Gauge("mysql_monitor_slow_queries_total", "MySQL Slow_queries status counter")
DB_ABORTED_CONNECTS_TOTAL = Gauge("mysql_monitor_aborted_connects_total", "MySQL Aborted_connects status counter")


class MySQLMonitorState:
    def __init__(self) -> None:
        self.pool: aiomysql.Pool | None = None
        self.poller_task: asyncio.Task[Any] | None = None
        self.last_sample_ts: float | None = None
        self.last_sample: dict[str, Any] = {}
        self.last_error: str | None = None
        self.last_alert_sent_at: dict[str, float] = {}
        self.last_alert_error: str | None = None
        self.alert_config: dict[str, Any] = {
            "alerts_enabled": MYSQL_ALERTS_ENABLED,
            "alert_cooldown_seconds": MYSQL_ALERT_COOLDOWN_SECONDS,
            "threads_running_threshold": MYSQL_THREADS_RUNNING_THRESHOLD,
            "slow_queries_delta_threshold": MYSQL_SLOW_QUERIES_DELTA_THRESHOLD,
            "aborted_connects_delta_threshold": MYSQL_ABORTED_CONNECTS_DELTA_THRESHOLD,
            "kaiops_alert_endpoint": KAIOPS_ALERT_ENDPOINT,
            "kaiops_alert_timeout_seconds": KAIOPS_ALERT_TIMEOUT_SECONDS,
        }


state = MySQLMonitorState()


async def create_pool() -> aiomysql.Pool:
    return await aiomysql.create_pool(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        db=MYSQL_DATABASE or None,
        connect_timeout=MYSQL_CONNECT_TIMEOUT,
        minsize=1,
        maxsize=8,
        autocommit=True,
    )


async def query_dict(cursor: aiomysql.DictCursor, sql: str) -> list[dict[str, Any]]:
    await cursor.execute(sql)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


def to_int(values: dict[str, str], key: str) -> int:
    raw = values.get(key, "0")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


async def collect_mysql_sample() -> dict[str, Any]:
    if state.pool is None:
        raise RuntimeError("MySQL pool is not initialized")

    async with state.pool.acquire() as connection:
        async with connection.cursor(aiomysql.DictCursor) as cursor:
            status_rows = await query_dict(cursor, "SHOW GLOBAL STATUS")
            variables_rows = await query_dict(cursor, "SHOW GLOBAL VARIABLES")

            status_map = {
                str(row.get("Variable_name", "")): str(row.get("Value", ""))
                for row in status_rows
            }
            variables_map = {
                str(row.get("Variable_name", "")): str(row.get("Value", ""))
                for row in variables_rows
            }

            sample = {
                "server": {
                    "version": variables_map.get("version", "unknown"),
                    "hostname": variables_map.get("hostname", "unknown"),
                    "port": variables_map.get("port", "unknown"),
                },
                "status": {
                    "threads_connected": to_int(status_map, "Threads_connected"),
                    "threads_running": to_int(status_map, "Threads_running"),
                    "uptime_seconds": to_int(status_map, "Uptime"),
                    "queries_total": to_int(status_map, "Queries"),
                    "slow_queries_total": to_int(status_map, "Slow_queries"),
                    "aborted_connects_total": to_int(status_map, "Aborted_connects"),
                },
                "captured_at": int(time.time()),
            }
            return sample


def update_prometheus_metrics(sample: dict[str, Any], db_up: bool) -> None:
    DB_UP.set(1 if db_up else 0)
    status = sample.get("status", {}) if db_up else {}
    DB_THREADS_CONNECTED.set(float(status.get("threads_connected", 0)))
    DB_THREADS_RUNNING.set(float(status.get("threads_running", 0)))
    DB_UPTIME_SECONDS.set(float(status.get("uptime_seconds", 0)))
    DB_QUERIES_TOTAL.set(float(status.get("queries_total", 0)))
    DB_SLOW_QUERIES_TOTAL.set(float(status.get("slow_queries_total", 0)))
    DB_ABORTED_CONNECTS_TOTAL.set(float(status.get("aborted_connects_total", 0)))


def _alert_allowed(alert_key: str) -> bool:
    now = time.time()
    last_sent = state.last_alert_sent_at.get(alert_key, 0.0)
    cooldown_seconds = int(state.alert_config.get("alert_cooldown_seconds", MYSQL_ALERT_COOLDOWN_SECONDS))
    if now - last_sent < cooldown_seconds:
        return False
    state.last_alert_sent_at[alert_key] = now
    return True


def _build_alert_payload(*, name: str, severity: str, description: str, labels: dict[str, str]) -> dict[str, Any]:
    return {
        "source": "mysql-monitor",
        "name": name,
        "service": "mysql",
        "environment": "prod",
        "severity": severity,
        "description": description,
        "labels": labels,
        "annotations": {"summary": description},
    }


async def _post_alert(payload: dict[str, Any]) -> None:
    if not bool(state.alert_config.get("alerts_enabled", MYSQL_ALERTS_ENABLED)):
        return
    try:
        timeout = httpx.Timeout(float(state.alert_config.get("kaiops_alert_timeout_seconds", KAIOPS_ALERT_TIMEOUT_SECONDS)))
        endpoint = str(state.alert_config.get("kaiops_alert_endpoint", KAIOPS_ALERT_ENDPOINT)).strip() or KAIOPS_ALERT_ENDPOINT
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
        state.last_alert_error = None
    except Exception as exc:  # pragma: no cover
        state.last_alert_error = str(exc)


async def evaluate_and_ingest_alerts(current: dict[str, Any], previous: dict[str, Any] | None) -> None:
    if not bool(state.alert_config.get("alerts_enabled", MYSQL_ALERTS_ENABLED)):
        return

    status = current.get("status", {})
    threads_running = int(status.get("threads_running", 0) or 0)
    slow_queries_total = int(status.get("slow_queries_total", 0) or 0)
    aborted_connects_total = int(status.get("aborted_connects_total", 0) or 0)

    prev_status = (previous or {}).get("status", {})
    prev_slow_queries_total = int(prev_status.get("slow_queries_total", 0) or 0)
    prev_aborted_connects_total = int(prev_status.get("aborted_connects_total", 0) or 0)

    slow_queries_delta = max(0, slow_queries_total - prev_slow_queries_total)
    aborted_connects_delta = max(0, aborted_connects_total - prev_aborted_connects_total)

    alerts: list[tuple[str, dict[str, Any]]] = []

    threads_running_threshold = int(state.alert_config.get("threads_running_threshold", MYSQL_THREADS_RUNNING_THRESHOLD))
    slow_queries_delta_threshold = int(
        state.alert_config.get("slow_queries_delta_threshold", MYSQL_SLOW_QUERIES_DELTA_THRESHOLD)
    )
    aborted_connects_delta_threshold = int(
        state.alert_config.get("aborted_connects_delta_threshold", MYSQL_ABORTED_CONNECTS_DELTA_THRESHOLD)
    )

    if threads_running >= threads_running_threshold:
        key = "threads_running_high"
        payload = _build_alert_payload(
            name="MySQLThreadsRunningHigh",
            severity="high",
            description=(
                f"MySQL threads running is {threads_running}, above threshold {threads_running_threshold}."
            ),
            labels={
                "component": "mysql",
                "signal": "threads_running",
                "threshold": str(threads_running_threshold),
                "current": str(threads_running),
            },
        )
        alerts.append((key, payload))

    if slow_queries_delta >= slow_queries_delta_threshold:
        key = "slow_queries_delta_high"
        payload = _build_alert_payload(
            name="MySQLSlowQueriesSpike",
            severity="warning",
            description=(
                f"MySQL slow queries increased by {slow_queries_delta} in the latest sampling window."
            ),
            labels={
                "component": "mysql",
                "signal": "slow_queries_delta",
                "threshold": str(slow_queries_delta_threshold),
                "current": str(slow_queries_delta),
            },
        )
        alerts.append((key, payload))

    if aborted_connects_delta >= aborted_connects_delta_threshold:
        key = "aborted_connects_delta_high"
        payload = _build_alert_payload(
            name="MySQLAbortedConnectsSpike",
            severity="critical",
            description=(
                f"MySQL aborted connects increased by {aborted_connects_delta} in the latest sampling window."
            ),
            labels={
                "component": "mysql",
                "signal": "aborted_connects_delta",
                "threshold": str(aborted_connects_delta_threshold),
                "current": str(aborted_connects_delta),
            },
        )
        alerts.append((key, payload))

    for alert_key, payload in alerts:
        if _alert_allowed(alert_key):
            await _post_alert(payload)


async def poll_mysql_forever() -> None:
    while True:
        try:
            if state.pool is None:
                state.pool = await create_pool()
            previous = dict(state.last_sample) if state.last_sample else None
            sample = await collect_mysql_sample()
            state.last_sample = sample
            state.last_sample_ts = time.time()
            state.last_error = None
            update_prometheus_metrics(sample, db_up=True)
            await evaluate_and_ingest_alerts(sample, previous)
        except Exception as exc:  # pragma: no cover
            message = str(exc)
            state.last_error = message
            if state.pool is not None:
                state.pool.close()
                await state.pool.wait_closed()
                state.pool = None
            update_prometheus_metrics({}, db_up=False)
            if bool(state.alert_config.get("alerts_enabled", MYSQL_ALERTS_ENABLED)) and _alert_allowed("mysql_down"):
                await _post_alert(
                    _build_alert_payload(
                        name="MySQLUnavailable",
                        severity="critical",
                        description=f"MySQL monitor cannot reach database: {message}",
                        labels={"component": "mysql", "signal": "availability", "status": "down"},
                    )
                )
        await asyncio.sleep(MYSQL_POLL_SECONDS)


async def mysql_ping() -> bool:
    if state.pool is None:
        return False
    try:
        async with state.pool.acquire() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                row = await cursor.fetchone()
                return bool(row and row[0] == 1)
    except Exception:
        return False


@asynccontextmanager
async def lifespan(_: FastAPI):
    state.poller_task = asyncio.create_task(poll_mysql_forever())
    try:
        yield
    finally:
        if state.poller_task is not None:
            state.poller_task.cancel()
            try:
                await state.poller_task
            except asyncio.CancelledError:
                pass
        if state.pool is not None:
            state.pool.close()
            await state.pool.wait_closed()


app = FastAPI(title="MySQL Monitor", version="1.0.0", lifespan=lifespan)


class AlertConfigUpdate(BaseModel):
    alerts_enabled: bool = True
    alert_cooldown_seconds: int = Field(default=300, ge=30, le=3600)
    threads_running_threshold: int = Field(default=40, ge=1, le=100000)
    slow_queries_delta_threshold: int = Field(default=5, ge=1, le=100000)
    aborted_connects_delta_threshold: int = Field(default=3, ge=1, le=100000)
    kaiops_alert_endpoint: str = Field(default=KAIOPS_ALERT_ENDPOINT, min_length=8, max_length=512)
    kaiops_alert_timeout_seconds: float = Field(default=KAIOPS_ALERT_TIMEOUT_SECONDS, ge=1.0, le=120.0)


@app.get("/")
async def index() -> dict[str, Any]:
    REQUEST_COUNT.labels(endpoint="/").inc()
    with REQUEST_LATENCY.labels(endpoint="/").time():
        return {
            "service": "mysql-monitor",
            "endpoints": [
                "/healthz",
                "/alerts/config",
                "/mysql/status",
                "/mysql/processlist",
                "/mysql/replication",
                "/metrics",
            ],
        }


@app.get("/healthz")
async def healthz() -> JSONResponse:
    REQUEST_COUNT.labels(endpoint="/healthz").inc()
    with REQUEST_LATENCY.labels(endpoint="/healthz").time():
        ok = await mysql_ping()
        payload = {
            "status": "ok" if ok else "degraded",
            "mysql_up": ok,
            "last_sample_at": state.last_sample_ts,
            "last_error": state.last_error,
            "alerts_enabled": state.alert_config.get("alerts_enabled", MYSQL_ALERTS_ENABLED),
            "last_alert_error": state.last_alert_error,
            "alert_endpoint": state.alert_config.get("kaiops_alert_endpoint", KAIOPS_ALERT_ENDPOINT),
        }
        status_code = 200 if ok else 503
        return JSONResponse(content=payload, status_code=status_code)


@app.get("/alerts/config")
async def get_alert_config() -> dict[str, Any]:
    return dict(state.alert_config)


@app.post("/alerts/config")
async def update_alert_config(payload: AlertConfigUpdate) -> dict[str, Any]:
    state.alert_config.update(payload.model_dump())
    state.last_alert_sent_at.clear()
    return {"config": dict(state.alert_config)}


@app.get("/mysql/status")
async def mysql_status() -> dict[str, Any]:
    REQUEST_COUNT.labels(endpoint="/mysql/status").inc()
    with REQUEST_LATENCY.labels(endpoint="/mysql/status").time():
        if not state.last_sample:
            raise HTTPException(status_code=503, detail="No MySQL sample available yet")
        return state.last_sample


@app.get("/mysql/processlist")
async def mysql_processlist(limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    REQUEST_COUNT.labels(endpoint="/mysql/processlist").inc()
    with REQUEST_LATENCY.labels(endpoint="/mysql/processlist").time():
        if state.pool is None:
            raise HTTPException(status_code=503, detail="MySQL pool is not initialized")

        async with state.pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                rows = await query_dict(cursor, "SHOW FULL PROCESSLIST")

        filtered = [
            {
                "id": row.get("Id"),
                "user": row.get("User"),
                "host": row.get("Host"),
                "db": row.get("db"),
                "command": row.get("Command"),
                "time": row.get("Time"),
                "state": row.get("State"),
                "info": (str(row.get("Info", ""))[:180] if row.get("Info") else ""),
            }
            for row in rows
        ]
        filtered.sort(key=lambda item: int(item.get("time") or 0), reverse=True)
        return {"total": len(filtered), "rows": filtered[:limit]}


@app.get("/mysql/replication")
async def mysql_replication() -> dict[str, Any]:
    REQUEST_COUNT.labels(endpoint="/mysql/replication").inc()
    with REQUEST_LATENCY.labels(endpoint="/mysql/replication").time():
        if state.pool is None:
            raise HTTPException(status_code=503, detail="MySQL pool is not initialized")

        async with state.pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                try:
                    rows = await query_dict(cursor, "SHOW REPLICA STATUS")
                except Exception:
                    rows = await query_dict(cursor, "SHOW SLAVE STATUS")

        if not rows:
            return {"replication_enabled": False, "details": {}}

        row = rows[0]
        details = {
            "replication_enabled": True,
            "source_host": row.get("Source_Host") or row.get("Master_Host"),
            "io_running": row.get("Replica_IO_Running") or row.get("Slave_IO_Running"),
            "sql_running": row.get("Replica_SQL_Running") or row.get("Slave_SQL_Running"),
            "seconds_behind_source": row.get("Seconds_Behind_Source") or row.get("Seconds_Behind_Master"),
            "last_sql_error": row.get("Last_SQL_Error"),
            "last_io_error": row.get("Last_IO_Error"),
        }
        return details


@app.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode("utf-8"), media_type=CONTENT_TYPE_LATEST)
