from __future__ import annotations

import aiomysql
import csv
import hashlib
import json
import logging
import os
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import httpx
from common.config import get_settings
from common.service import create_app
from pydantic import BaseModel, Field

logger = logging.getLogger("kaiops.discovery_mcp")

settings = get_settings()
settings.service_name = "discovery-mcp"
app = create_app(title="KaiOps Discovery MCP", settings=settings)

CODE_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".cs",
    ".rs", ".php", ".kt", ".kts", ".ex", ".exs", ".cpp", ".cc", ".h",
    ".proto", ".yml", ".yaml", ".json", ".toml", ".xml", ".md",
}
LOG_SUFFIXES = {".log", ".out", ".txt", ".json", ".jsonl"}
TICKET_SUFFIXES = {".csv", ".eml", ".md", ".txt"}
SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|authorization|token)\s*[:=]\s*([^\s,;]+)"
)
LOG_SIGNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("connection_refused", re.compile(r"(?i)\b(connection refused|econnrefused)\b")),
    ("timeout", re.compile(r"(?i)\b(timed? out|timeout|deadline exceeded)\b")),
    ("authentication", re.compile(r"(?i)\b(unauthorized|forbidden|authentication failed|invalid credential)\b")),
    ("resource_exhaustion", re.compile(r"(?i)\b(out of memory|oomkilled|resource exhausted|no space left)\b")),
    ("dependency_unavailable", re.compile(r"(?i)\b(unavailable|connection reset|no route to host|name resolution)\b")),
    ("exception", re.compile(r"(?i)\b(exception|traceback|panic|fatal)\b")),
    ("http_5xx", re.compile(r"\b5\d\d\b")),
    ("error", re.compile(r"(?i)\b(error|failed|failure|critical)\b")),
)


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


def _roots(name: str, default: str) -> list[Path]:
    return [Path(item.strip()) for item in os.getenv(name, default).split(",") if item.strip()]


def _project_catalog() -> dict[str, dict[str, Any]]:
    path = Path(os.getenv("DISCOVERY_MCP_PROJECTS_FILE", "/workspace/backend/config/discovery-projects.json"))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    projects = payload.get("projects") if isinstance(payload, dict) else {}
    return projects if isinstance(projects, dict) else {}


def _project_for(arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    hints = [
        arguments.get("project"),
        arguments.get("application"),
        *(_terms(arguments)),
    ]
    normalized_hints = {str(value or "").strip().lower() for value in hints if str(value or "").strip()}
    for project_id, project in _project_catalog().items():
        aliases = {
            str(project_id).lower(),
            str(project.get("name") or "").lower(),
            str(project.get("display_name") or "").lower(),
            *(str(alias).lower() for alias in project.get("aliases", []) if alias),
        }
        if normalized_hints & aliases or any(alias and alias in " ".join(normalized_hints) for alias in aliases):
            return str(project_id), project
    return "", {}


def _code_roots(arguments: dict[str, Any]) -> list[Path]:
    _, project = _project_for(arguments)
    configured = project.get("code_roots") if isinstance(project.get("code_roots"), list) else []
    if configured:
        roots = [Path(str(root)) for root in configured if str(root).strip()]
        service = re.sub(r"[^a-zA-Z0-9_-]", "", str(arguments.get("service") or "").strip())
        catalog_root = str(project.get("service_catalog_root") or "").strip()
        if service and catalog_root:
            service_root = Path(catalog_root) / service
            if service_root.is_dir():
                roots.insert(0, service_root)
        return list(dict.fromkeys(roots))
    return _roots(
        "DISCOVERY_MCP_CODE_ROOTS",
        "/workspace/backend/src,/workspace/ai-workbench/src,/workspace/frontend/react/src,/workspace/scripts,/workspace/config,/workspace/observability,/workspace/fault-lab,/workspace/docs",
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "discovery-mcp"}


def _redact(text: str) -> str:
    return SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)


def _terms(arguments: dict[str, Any]) -> list[str]:
    values = arguments.get("terms", [])
    if not isinstance(values, list):
        values = [values]
    tokens: list[str] = []
    for value in values:
        tokens.extend(re.findall(r"[a-zA-Z0-9_.-]{3,}", str(value).lower()))
    return list(dict.fromkeys(tokens))[:24]


def _evidence(kind: str, path: Path, line: int, snippet: str, matched: list[str]) -> dict[str, Any]:
    safe_snippet = _redact(re.sub(r"\s+", " ", snippet).strip())[:700]
    digest = hashlib.sha256(f"{kind}|{path}|{line}|{safe_snippet}".encode()).hexdigest()[:16]
    evidence = {
        "evidence_id": f"{kind.upper()}-{digest}",
        "source": kind,
        "uri": f"{kind}://{path.as_posix()}#L{line}",
        "path": str(path),
        "line": line,
        "snippet": safe_snippet,
        "matched_terms": matched,
        "sha256": hashlib.sha256(safe_snippet.encode()).hexdigest(),
    }
    if kind == "log":
        evidence["diagnostic_signals"] = [
            signal for signal, pattern in LOG_SIGNAL_PATTERNS if pattern.search(safe_snippet)
        ]
    return evidence


def _log_diagnosis(evidence: list[dict[str, Any]], service: str = "") -> dict[str, Any] | None:
    counts: dict[str, int] = {}
    supporting_ids: list[str] = []
    for row in evidence:
        if str(row.get("source") or "").lower() not in {"log", "opensearch"}:
            continue
        signals = row.get("diagnostic_signals") if isinstance(row.get("diagnostic_signals"), list) else []
        for signal in signals:
            token = str(signal)
            counts[token] = counts.get(token, 0) + 1
        if signals and row.get("evidence_id"):
            supporting_ids.append(str(row["evidence_id"]))
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    target = service or "selected service"
    summary = ", ".join(f"{name.replace('_', ' ')} ({count})" for name, count in ranked[:5])
    item = _evidence(
        "log",
        Path(f"diagnosis/{target}"),
        1,
        f"Structured log diagnosis for {target}: {summary}. Correlate these signals before assigning root cause.",
        [name for name, _ in ranked[:5]],
    )
    item.update(
        {
            "signal_type": "log_diagnosis",
            "diagnostic_signals": [name for name, _ in ranked],
            "signal_counts": dict(ranked),
            "supporting_evidence": supporting_ids[:12],
            "service": target,
        }
    )
    return item


def _decode_docker_log_stream(payload: bytes) -> str:
    """Decode Docker's multiplexed stdout/stderr stream, with plain-text fallback."""
    chunks: list[bytes] = []
    offset = 0
    while offset + 8 <= len(payload):
        frame_size = int.from_bytes(payload[offset + 4 : offset + 8], "big")
        frame_end = offset + 8 + frame_size
        if payload[offset] not in {0, 1, 2} or frame_end > len(payload):
            break
        chunks.append(payload[offset + 8 : frame_end])
        offset = frame_end
    if chunks:
        # Keep whatever frames parsed cleanly even if a trailing frame was cut short (e.g.
        # by a streaming read boundary) instead of discarding good data for one bad frame.
        return b"".join(chunks).decode("utf-8", errors="replace")
    return payload.decode("utf-8", errors="replace")


async def _search_docker_logs(arguments: dict[str, Any], terms: list[str], limit: int) -> list[dict[str, Any]]:
    if str(os.getenv("DOCKER_LOG_DISCOVERY_ENABLED", "true")).strip().lower() not in {"1", "true", "yes", "on"}:
        return []
    # Talk to a scoped docker-socket-proxy (read-only GET on /containers*) rather than mounting
    # /var/run/docker.sock into this container directly. A raw socket mount is root-on-host even
    # when the bind mount itself is ":ro" -- that flag only stops the container from replacing
    # the socket *file*, it does not restrict which Docker API calls (create/exec/mount) are
    # reachable through it. The proxy (see docker-compose.yml) only allows GET on containers.
    docker_host = str(os.getenv("DOCKER_LOG_DISCOVERY_HOST", "docker-socket-proxy:2375")).strip()
    if not docker_host:
        return []
    service = str(arguments.get("service") or "").strip().lower()
    project = str(arguments.get("project") or arguments.get("application") or "").strip().lower()
    max_containers = max(1, min(int(os.getenv("DOCKER_LOG_DISCOVERY_MAX_CONTAINERS", "40")), 100))
    tail = max(20, min(int(os.getenv("DOCKER_LOG_DISCOVERY_TAIL", "250")), 2000))
    timeout = httpx.Timeout(max(2.0, min(float(os.getenv("DOCKER_LOG_DISCOVERY_TIMEOUT_SECONDS", "10")), 30.0)))
    evidence: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(base_url=f"http://{docker_host}", timeout=timeout) as client:
            response = await client.get("/containers/json", params={"all": "true", "limit": str(max_containers)})
            response.raise_for_status()
            containers = response.json()
            for container in containers[:max_containers]:
                if not isinstance(container, dict):
                    continue
                names = [str(name).lstrip("/") for name in container.get("Names", []) if name]
                labels = container.get("Labels") if isinstance(container.get("Labels"), dict) else {}
                compose_service = str(labels.get("com.docker.compose.service") or "")
                identity = " ".join([*names, compose_service, str(container.get("Image") or "")]).lower()
                # A filter that wasn't provided must not count as "matched" -- otherwise, e.g.
                # a service-only query (project == "") would trivially satisfy `not project`
                # and every container would pass regardless of whether service_ok is true.
                has_project_filter = bool(project)
                has_service_filter = bool(service)
                project_ok = has_project_filter and (
                    (project.startswith("telemetry") and "telemetry-" in identity)
                    or (project.startswith("kaiops") and "kaiops" in identity)
                    or project in identity
                )
                service_ok = has_service_filter and (
                    service in identity or service.replace("_", "-") in identity
                )
                if (has_project_filter or has_service_filter) and not project_ok and not service_ok:
                    continue
                container_id = str(container.get("Id") or "")
                if not container_id:
                    continue
                logs = await client.get(
                    f"/containers/{container_id}/logs",
                    params={"stdout": "true", "stderr": "true", "timestamps": "true", "tail": str(tail)},
                )
                logs.raise_for_status()
                container_name = names[0] if names else container_id[:12]
                for line_number, line in enumerate(_decode_docker_log_stream(logs.content).splitlines(), 1):
                    lowered = line.lower()
                    matched = [term for term in terms if term in lowered or term in identity]
                    signals = [signal for signal, pattern in LOG_SIGNAL_PATTERNS if pattern.search(line)]
                    if not matched and not signals:
                        continue
                    item = _evidence("log", Path(f"docker/{container_name}"), line_number, line, matched)
                    item.update(
                        {
                            "uri": f"docker://{container_name}#L{line_number}",
                            "container": container_name,
                            "container_id": container_id[:12],
                            "service": compose_service or service or container_name,
                            "diagnostic_signals": signals,
                            "log_channel": "docker",
                        }
                    )
                    evidence.append(item)
    except Exception as exc:
        logger.warning(
            "docker_log_discovery_unavailable",
            extra={"error": str(exc)[:240], "docker_host": docker_host},
        )
        return []
    evidence.sort(key=lambda row: (not bool(row.get("diagnostic_signals")), str(row.get("container") or "")))
    return evidence[:limit]


def _search_text_files(
    roots: list[Path], suffixes: set[str], terms: list[str], kind: str, limit: int
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    max_files = max(10, min(int(os.getenv("DISCOVERY_MCP_MAX_FILES", "60")), 400))
    excluded_dirs = {".git", ".claiming", "node_modules", "dist", "build", "__pycache__", "ingested_alerts", ".venv", "kaiops.egg-info"}
    for root_index, root in enumerate(roots):
        if not root.is_dir():
            continue
        scanned = 0
        # A project-specific service root is intentionally searched more deeply.
        # The broader repository fallback keeps the normal global crawl bound.
        root_budget = 400 if root_index == 0 and len(roots) > 1 else max_files
        for current, directories, files in os.walk(root):
            directories[:] = [name for name in directories if name not in excluded_dirs]
            for filename in files:
                if scanned >= root_budget:
                    break
                path = Path(current) / filename
                if path.suffix.lower() not in suffixes:
                    continue
                scanned += 1
                try:
                    if path.stat().st_size > 750_000:
                        continue
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:5000]
                except OSError:
                    continue
                path_lowered = path.as_posix().lower()
                path_matches = [term for term in terms if term in path_lowered]
                for line_no, line in enumerate(lines, 1):
                    lowered = line.lower()
                    matched = list(dict.fromkeys([*path_matches, *(term for term in terms if term in lowered)]))
                    if matched:
                        ranked.append((len(matched), -root_index, _evidence(kind, path, line_no, line, matched)))
            if scanned >= root_budget:
                break
        if root_index == 0 and len(ranked) >= limit:
            break
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2]["uri"]))
    return [row[2] for row in ranked[:limit]]


def _ticket_text(path: Path) -> list[tuple[int, str]]:
    try:
        if path.suffix.lower() == ".eml":
            message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            chunks = [f"Subject: {message.get('Subject', '')}"]
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    chunks.append(str(part.get_content()))
            return list(enumerate("\n".join(chunks).splitlines(), 1))
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                return [
                    (index, json.dumps(row, ensure_ascii=False, default=str))
                    for index, row in enumerate(csv.DictReader(handle), 1)
                ]
        return list(enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1))
    except (OSError, ValueError):
        return []


def _search_tickets(terms: list[str], limit: int) -> list[dict[str, Any]]:
    ranked: list[tuple[int, dict[str, Any]]] = []
    scanned = 0
    max_files = max(10, min(int(os.getenv("DISCOVERY_MCP_MAX_TICKET_FILES", "80")), 400))
    for root in _roots("DISCOVERY_MCP_TICKET_ROOTS", "/workspace/backend/rag,/data/tickets,/data/landing/documents"):
        if not root.is_dir():
            continue
        for current, directories, files in os.walk(root):
            directories[:] = [name for name in directories if name not in {".claiming", "node_modules", ".git"}]
            for filename in files:
                if scanned >= max_files:
                    break
                path = Path(current) / filename
                if path.suffix.lower() not in TICKET_SUFFIXES:
                    continue
                scanned += 1
                for line_no, text in _ticket_text(path):
                    lowered = text.lower()
                    matched = [term for term in terms if term in lowered]
                    if matched:
                        ranked.append((len(matched), _evidence("ticket", path, line_no, text, matched)))
            if scanned >= max_files:
                break
    ranked.sort(key=lambda row: (-row[0], row[1]["uri"]))
    return [row[1] for row in ranked[:limit]]


async def _search_jira_tickets(arguments: dict[str, Any], terms: list[str], limit: int) -> list[dict[str, Any]]:
    _, project = _project_for(arguments)
    ticket_sources = project.get("ticket_sources") if isinstance(project.get("ticket_sources"), dict) else {}
    jira_url = str(os.getenv("JIRA_URL") or ticket_sources.get("jira_url") or "").strip().rstrip("/")
    user_email = str(os.getenv("JIRA_USER_EMAIL") or "").strip()
    api_token = str(os.getenv("JIRA_API_TOKEN") or "").strip()
    project_key = str(os.getenv("JIRA_PROJECT_KEY") or ticket_sources.get("jira_project_key") or "").strip()
    if not jira_url or not user_email or not api_token or not terms:
        return []

    search_text = " ".join(terms[:8]).replace('"', '\\"')
    clauses = [f'text ~ "{search_text}"']
    if project_key:
        safe_project = re.sub(r"[^A-Za-z0-9_-]", "", project_key)
        if safe_project:
            clauses.insert(0, f'project = "{safe_project}"')
    jql = " AND ".join(clauses) + " ORDER BY updated DESC"
    timeout = httpx.Timeout(max(2.0, min(float(os.getenv("JIRA_TIMEOUT_SECONDS", "8")), 30.0)))
    async with httpx.AsyncClient(timeout=timeout, auth=(user_email, api_token)) as client:
        response = await client.get(
            f"{jira_url}/rest/api/3/search",
            params={
                "jql": jql,
                "maxResults": limit,
                "fields": "summary,description,status,priority,issuetype,created,updated,labels,components",
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        issues = response.json().get("issues", [])

    evidence: list[dict[str, Any]] = []
    for index, issue in enumerate(issues[:limit], 1):
        if not isinstance(issue, dict):
            continue
        fields = issue.get("fields") if isinstance(issue.get("fields"), dict) else {}
        key = str(issue.get("key") or "").strip()
        summary = str(fields.get("summary") or "").strip()
        status = fields.get("status") if isinstance(fields.get("status"), dict) else {}
        priority = fields.get("priority") if isinstance(fields.get("priority"), dict) else {}
        snippet = (
            f"{key} {summary}; status={status.get('name', 'unknown')}; "
            f"priority={priority.get('name', 'unknown')}; updated={fields.get('updated', '')}"
        )
        matched = [term for term in terms if term in snippet.lower()] or terms[:1]
        item = _evidence("ticket", Path(f"jira/{key or index}"), 1, snippet, matched)
        item.update(
            {
                "uri": f"{jira_url}/browse/{key}" if key else jira_url,
                "ticket_id": key,
                "ticket_system": "jira",
                "title": summary,
                "status": status.get("name"),
                "priority": priority.get("name"),
            }
        )
        evidence.append(item)
    return evidence


def _mysql_connection_settings() -> dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST", "mysql"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "kaiops"),
        "password": os.getenv("DB_PASSWORD", "kaiops"),
        "db": os.getenv("DB_DATABASE", "kaiops"),
    }


async def _search_mysql(terms: list[str], limit: int) -> list[dict[str, Any]]:
    if not terms:
        return []
    settings = _mysql_connection_settings()
    max_rows = max(20, min(int(os.getenv("DISCOVERY_MCP_MYSQL_MAX_ROWS", "120")), 500))
    configured_tables = [
        token.strip()
        for token in os.getenv(
            "DISCOVERY_MCP_MYSQL_TABLES",
            "alerts,incident_projections,incidents,closed_incidents,onboarding_state",
        ).split(",")
        if token.strip()
    ]
    ranked: list[tuple[int, dict[str, Any]]] = []
    pool = await aiomysql.create_pool(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        db=settings["db"],
        minsize=1,
        maxsize=2,
        autocommit=True,
        connect_timeout=4,
    )
    try:
        async with pool.acquire() as connection:
            async with connection.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SHOW TABLES")
                rows = await cursor.fetchall()
                available = {str(next(iter(row.values()), "")).strip().lower() for row in rows if isinstance(row, dict)}
                table_names = [table for table in configured_tables if table.lower() in available]
                for table in table_names:
                    try:
                        await cursor.execute(f"SELECT * FROM `{table}` ORDER BY 1 DESC LIMIT %s", (max_rows,))
                        table_rows = await cursor.fetchall()
                    except Exception:
                        continue
                    for table_row in table_rows:
                        if not isinstance(table_row, dict):
                            continue
                        normalized = {
                            str(key): value
                            for key, value in table_row.items()
                            if str(key).strip().lower()
                            not in {"password", "passwd", "secret", "token", "api_key", "authorization"}
                        }
                        serialized = json.dumps(normalized, ensure_ascii=False, default=str)
                        lowered = serialized.lower()
                        matched = [term for term in terms if term in lowered]
                        if not matched:
                            continue
                        row_id = ""
                        for key in ("id", "alert_id", "incident_id", "flow_id", "ticket_id"):
                            if key in normalized and str(normalized.get(key) or "").strip():
                                row_id = str(normalized.get(key)).strip()
                                break
                        snippet = f"table={table} {serialized[:620]}"
                        uri_path = Path(f"{settings['db']}/{table}")
                        evidence = _evidence("mysql", uri_path, 1, snippet, matched)
                        evidence["uri"] = f"mysql://{settings['db']}/{table}#row={row_id or evidence['evidence_id']}"
                        evidence["table"] = table
                        if row_id:
                            evidence["row_id"] = row_id
                        ranked.append((len(matched), evidence))
    finally:
        pool.close()
        await pool.wait_closed()

    ranked.sort(key=lambda row: (-row[0], row[1]["uri"]))
    return [row[1] for row in ranked[:limit]]


async def _call_mysql_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    terms = _terms(arguments)
    limit = max(1, min(int(arguments.get("limit", 8)), 20))
    rows = await _search_mysql(terms, limit)
    return {"tool": "mysql.search", "query_terms": terms, "result_count": len(rows), "evidence": rows}


async def _search_telemetry(arguments: dict[str, Any]) -> dict[str, Any]:
    project_id, project = _project_for(arguments)
    telemetry = project.get("telemetry") if isinstance(project.get("telemetry"), dict) else {}
    terms = _terms(arguments)
    service = str(arguments.get("service") or next(iter(terms), "")).strip()
    trace_id = str(arguments.get("trace_id") or "").strip()
    limit = max(1, min(int(arguments.get("limit", 8)), 20))
    evidence: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    timeout = httpx.Timeout(max(2.0, min(float(os.getenv("DISCOVERY_MCP_TELEMETRY_TIMEOUT_SECONDS", "6")), 20.0)))

    async with httpx.AsyncClient(timeout=timeout) as client:
        prometheus_url = str(telemetry.get("prometheus_url") or "").rstrip("/")
        if prometheus_url:
            query = f'{{service_name="{service}"}}' if service else "up"
            try:
                response = await client.get(f"{prometheus_url}/api/v1/query", params={"query": query})
                response.raise_for_status()
                results = response.json().get("data", {}).get("result", [])
                for index, row in enumerate(results[:limit], 1):
                    snippet = json.dumps(row, ensure_ascii=False, default=str)[:700]
                    item = _evidence("metric", Path(f"{project_id or 'telemetry'}/prometheus"), index, snippet, terms)
                    item["uri"] = f"prometheus://{project_id or 'telemetry'}?query={query}"
                    evidence.append(item)
                sources.append({"source": "prometheus", "status": "completed", "result_count": len(results)})
            except Exception as exc:
                sources.append({"source": "prometheus", "status": "unavailable", "error": str(exc)[:240]})

        jaeger_url = str(telemetry.get("jaeger_url") or "").rstrip("/")
        if jaeger_url:
            try:
                if trace_id:
                    response = await client.get(f"{jaeger_url}/api/traces/{trace_id}")
                else:
                    response = await client.get(
                        f"{jaeger_url}/api/traces",
                        params={"service": service, "limit": str(limit), "lookback": "1h"},
                    )
                response.raise_for_status()
                traces = response.json().get("data", [])
                for index, trace in enumerate(traces[:limit], 1):
                    discovered_trace_id = str(trace.get("traceID") or trace_id or "")
                    processes = trace.get("processes") if isinstance(trace.get("processes"), dict) else {}
                    process_services = sorted(
                        {
                            str(process.get("serviceName"))
                            for process in processes.values()
                            if isinstance(process, dict) and process.get("serviceName")
                        }
                    )
                    snippet = json.dumps(
                        {
                            "trace_id": discovered_trace_id,
                            "services": process_services,
                            "span_count": len(trace.get("spans", [])) if isinstance(trace.get("spans"), list) else 0,
                        },
                        ensure_ascii=False,
                    )
                    item = _evidence("trace", Path(f"{project_id or 'telemetry'}/jaeger"), index, snippet, terms)
                    item["uri"] = f"jaeger://trace/{discovered_trace_id or index}"
                    evidence.append(item)
                sources.append({"source": "jaeger", "status": "completed", "result_count": len(traces)})
            except Exception as exc:
                sources.append({"source": "jaeger", "status": "unavailable", "error": str(exc)[:240]})

        opensearch_url = str(telemetry.get("opensearch_url") or "").rstrip("/")
        opensearch_index = str(telemetry.get("opensearch_index") or "otel-*").strip()
        if opensearch_url:
            must: list[dict[str, Any]] = []
            if service:
                must.append(
                    {
                        "query_string": {
                            "query": f'"{service}"',
                            "fields": ["service.name", "resource.attributes.service.name", "body", "message"],
                        }
                    }
                )
            if trace_id:
                must.append(
                    {
                        "query_string": {
                            "query": f'"{trace_id}"',
                            "fields": ["trace_id", "traceId", "trace.id"],
                        }
                    }
                )
            body = {
                "size": limit,
                "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
                "query": {"bool": {"must": must or [{"match_all": {}}]}},
            }
            try:
                response = await client.post(f"{opensearch_url}/{opensearch_index}/_search", json=body)
                response.raise_for_status()
                hits = response.json().get("hits", {}).get("hits", [])
                for index, hit in enumerate(hits[:limit], 1):
                    source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
                    snippet = json.dumps(source, ensure_ascii=False, default=str)[:700]
                    item = _evidence("log", Path(f"{project_id or 'telemetry'}/opensearch"), index, snippet, terms)
                    item["uri"] = f"opensearch://{opensearch_index}/{hit.get('_id', index)}"
                    evidence.append(item)
                sources.append({"source": "opensearch", "status": "completed", "result_count": len(hits)})
            except Exception as exc:
                sources.append({"source": "opensearch", "status": "unavailable", "error": str(exc)[:240]})

    diagnosis = _log_diagnosis(evidence, service)
    if diagnosis:
        evidence.insert(0, diagnosis)
    return {
        "tool": "telemetry.search",
        "project": project_id,
        "query_terms": terms,
        "service": service,
        "trace_id": trace_id,
        "result_count": len(evidence),
        "evidence": evidence[:limit],
        "sources": sources,
        "correlation_keys": project.get("correlation_keys", []),
    }


TOOLS = [
    {
        "name": "logs.search",
        "description": "Read-only bounded search of runtime and archived logs.",
        "inputSchema": {"type": "object", "properties": {"terms": {"type": "array"}, "limit": {"type": "integer"}}},
    },
    {
        "name": "tickets.search",
        "description": "Read-only search of Jira CSV, email tickets, and incident documents.",
        "inputSchema": {"type": "object", "properties": {"terms": {"type": "array"}, "limit": {"type": "integer"}}},
    },
    {
        "name": "code.search",
        "description": "Read-only bounded search of source, configuration, and deployment files.",
        "inputSchema": {"type": "object", "properties": {"terms": {"type": "array"}, "limit": {"type": "integer"}}},
    },
    {
        "name": "mysql.search",
        "description": "Read-only bounded evidence search over KaiOps MySQL tables.",
        "inputSchema": {"type": "object", "properties": {"terms": {"type": "array"}, "limit": {"type": "integer"}}},
    },
    {
        "name": "telemetry.search",
        "description": "Correlated read-only search of project Prometheus metrics, Jaeger traces, and OpenSearch logs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "application": {"type": "string"},
                "service": {"type": "string"},
                "trace_id": {"type": "string"},
                "terms": {"type": "array"},
                "limit": {"type": "integer"}
            }
        },
    },
]


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    terms = _terms(arguments)
    limit = max(1, min(int(arguments.get("limit", 8)), 20))
    if name == "code.search":
        rows = _search_text_files(
            _code_roots(arguments),
            CODE_SUFFIXES,
            terms,
            "code",
            limit,
        )
    elif name == "tickets.search":
        rows = _search_tickets(terms, limit)
    else:
        raise ValueError(f"unknown MCP tool: {name}")
    return {"tool": name, "query_terms": terms, "result_count": len(rows), "evidence": rows}


async def _call_ticket_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    terms = _terms(arguments)
    limit = max(1, min(int(arguments.get("limit", 8)), 20))
    jira_rows = await _search_jira_tickets(arguments, terms, limit)
    local_rows = await asyncio.to_thread(_search_tickets, terms, limit)
    rows = (jira_rows + local_rows)[:limit]
    return {
        "tool": "tickets.search",
        "query_terms": terms,
        "result_count": len(rows),
        "evidence": rows,
        "sources": {
            "jira": len(jira_rows),
            "local_history": len(local_rows),
        },
    }


async def _call_logs_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    terms = _terms(arguments)
    limit = max(1, min(int(arguments.get("limit", 8)), 20))
    file_rows, docker_rows = await asyncio.gather(
        asyncio.to_thread(
            _search_text_files,
            _roots("DISCOVERY_MCP_LOG_ROOTS", "/data/fault-lab/runtime,/data/landing"),
            LOG_SUFFIXES,
            terms,
            "log",
            limit,
        ),
        _search_docker_logs(arguments, terms, limit),
    )
    merged: dict[str, dict[str, Any]] = {}
    for row in [*docker_rows, *file_rows]:
        merged[str(row.get("evidence_id") or row.get("uri"))] = row
    rows = list(merged.values())
    diagnosis = _log_diagnosis(rows, str(arguments.get("service") or ""))
    if diagnosis:
        rows.insert(0, diagnosis)
    rows = rows[:limit]
    return {
        "tool": "logs.search",
        "query_terms": terms,
        "result_count": len(rows),
        "evidence": rows,
        "sources": {"docker": len(docker_rows), "files": len(file_rows)},
    }


@app.post("/mcp")
async def mcp(request: MCPRequest) -> dict[str, Any]:
    try:
        if request.method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "kaiops-discovery-mcp", "version": "1.0.0"},
                "capabilities": {"tools": {"listChanged": False}},
            }
        elif request.method == "tools/list":
            result = {"tools": TOOLS}
        elif request.method == "tools/call":
            name = str(request.params.get("name") or "")
            arguments = request.params.get("arguments")
            safe_arguments = arguments if isinstance(arguments, dict) else {}
            if name == "mysql.search":
                result = await _call_mysql_tool(safe_arguments)
            elif name == "telemetry.search":
                result = await _search_telemetry(safe_arguments)
            elif name == "tickets.search":
                result = await _call_ticket_tool(safe_arguments)
            elif name == "logs.search":
                result = await _call_logs_tool(safe_arguments)
            else:
                result = await asyncio.to_thread(_call_tool, name, safe_arguments)
        else:
            raise ValueError(f"unsupported MCP method: {request.method}")
        return {"jsonrpc": "2.0", "id": request.id, "result": result}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request.id, "error": {"code": -32602, "message": str(exc)}}
