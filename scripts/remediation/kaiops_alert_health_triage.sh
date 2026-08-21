#!/usr/bin/env sh
set -eu

SERVICE=""
ENVIRONMENT="prod"
API_GATEWAY_URL="${API_GATEWAY_URL:-http://api-gateway:8000}"
PROMETHEUS_URL="${PROMETHEUS_URL:-http://prometheus:9090}"
MYSQL_HOST="${MYSQL_HOST:-mysql}"
MYSQL_PORT="${MYSQL_PORT:-3306}"
MYSQL_DATABASE="${MYSQL_DATABASE:-kaiops}"
MYSQL_USER="${MYSQL_USER:-kaiops}"
MYSQL_PASSWORD="${MYSQL_PASSWORD:-${DB_PASSWORD:-}}"
ALERTS_TABLE="${ALERTS_TABLE:-alerts}"
DRY_RUN="${DRY_RUN:-true}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --service) SERVICE="${2:-}"; shift 2 ;;
    --environment) ENVIRONMENT="${2:-prod}"; shift 2 ;;
    --api-gateway-url) API_GATEWAY_URL="${2:-}"; shift 2 ;;
    --prometheus-url) PROMETHEUS_URL="${2:-}"; shift 2 ;;
    --mysql-host) MYSQL_HOST="${2:-}"; shift 2 ;;
    --mysql-port) MYSQL_PORT="${2:-3306}"; shift 2 ;;
    --mysql-database) MYSQL_DATABASE="${2:-kaiops}"; shift 2 ;;
    --mysql-user) MYSQL_USER="${2:-kaiops}"; shift 2 ;;
    --alerts-table) ALERTS_TABLE="${2:-alerts}"; shift 2 ;;
    --dry-run) DRY_RUN="${2:-true}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$SERVICE" ]; then
  echo "Missing --service" >&2
  exit 2
fi

echo "KaiOps alert triage started"
echo "KAI_OPS_EXECUTION_CLASS=diagnostic"
echo "service=$SERVICE environment=$ENVIRONMENT dry_run=$DRY_RUN"
echo "api_gateway_url=$API_GATEWAY_URL prometheus_url=$PROMETHEUS_URL mysql=${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}"

curl -fsS "${API_GATEWAY_URL%/}/healthz" >/tmp/kaiops-api-health.json || curl -fsS "${API_GATEWAY_URL%/}/health" >/tmp/kaiops-api-health.json
curl -fsS "${PROMETHEUS_URL%/}/api/v1/alerts" >/tmp/kaiops-prometheus-alerts.json

if command -v mysql >/dev/null 2>&1; then
  if [ -n "${MYSQL_PASSWORD:-}" ]; then
    MYSQL_ERROR_FILE="${TMPDIR:-/tmp}/kaiops-mysql-error.$$"
    mysql_query() {
      MYSQL_PWD="$MYSQL_PASSWORD" mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" "$MYSQL_DATABASE" -e "$1"
    }
    if ! mysql_query "SELECT COUNT(*) AS alert_rows, MIN(created_at) AS oldest_row, MAX(created_at) AS newest_row FROM ${ALERTS_TABLE};
SELECT table_name, table_rows, ROUND((data_length + index_length) / 1024 / 1024, 2) AS total_mb FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = '${ALERTS_TABLE}';
SELECT variable_name, variable_value FROM performance_schema.global_status WHERE variable_name IN ('Threads_connected','Threads_running','Slow_queries','Aborted_connects');" 2>"$MYSQL_ERROR_FILE"; then
      cat "$MYSQL_ERROR_FILE" >&2
      rm -f "$MYSQL_ERROR_FILE"
      exit 1
    fi
    if ! mysql_query "SELECT COUNT(*) AS active_transactions FROM information_schema.innodb_trx; SELECT COUNT(*) AS lock_waits FROM performance_schema.data_lock_waits;" 2>"$MYSQL_ERROR_FILE"; then
      echo "Optional lock/transaction evidence unavailable to the least-privilege account." >&2
      cat "$MYSQL_ERROR_FILE" >&2
    fi
    rm -f "$MYSQL_ERROR_FILE"
  else
    if [ "$SERVICE" = "mysql" ]; then
      echo "MYSQL_PASSWORD is required for MySQL diagnostic evidence." >&2
      exit 1
    fi
    echo "MYSQL_PASSWORD is not set; skipping optional MySQL diagnostics."
  fi
else
  echo "mysql client is not installed; skipping MySQL row-count validation."
fi

echo "Diagnostic collection complete. No remediation mutation was executed."
