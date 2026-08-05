#!/usr/bin/env bash
# Sends the generated e2e test data to the real ingestion endpoints.
# Run from the repo root: bash scripts/test-data/send_all.sh [prometheus|email|jira|logs|invalid|all]
# Point DATA_DIR at a tagged run (see gen_test_data.py <tag>) to resend a
# fresh, non-deduplicated copy of the same 100 alerts, e.g.:
#   DATA_DIR=scripts/test-data/run-w5 bash scripts/test-data/send_all.sh all
#
# Requires: monitoring-adapter reachable at localhost:8001, curl, python.
# JIRA_WEBHOOK_SECRET is read from .env for the Jira webhook calls.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

MONITORING_URL="http://localhost:8001"
JIRA_SECRET="$(grep -E '^JIRA_WEBHOOK_SECRET=' .env 2>/dev/null | cut -d= -f2 | cut -d' ' -f1)"
DATA_DIR="${DATA_DIR:-scripts/test-data}"
MODE="${1:-all}"

send_prometheus() {
  echo "=== Prometheus/Alertmanager: sending prometheus_alerts.json as one webhook call (25 alerts) ==="
  curl -s -X POST "$MONITORING_URL/alerts/alertmanager" -H "Content-Type: application/json" \
    --data-binary @"$DATA_DIR/prometheus_alerts.json"
  echo
}

send_email() {
  echo "=== Email: writing 25 landing-pad .json files, then triggering processing ==="
  # Email has no HTTP ingestion endpoint -- it's IMAP polling (live) or this
  # file-drop path (bulk/test), read by load_landing_pad_file(). A .json file
  # with "subject"+"from" keys (or source:"email") is routed through
  # email_to_alert() automatically.
  INPUT_DIR="${INGESTED_ALERTS_HOST_PATH:-backend/ingested_alerts}/input"
  mkdir -p "$INPUT_DIR"
  python -c "
import json
with open('$DATA_DIR/email_alerts.json') as f:
    items = json.load(f)
for i, item in enumerate(items, 1):
    with open('$INPUT_DIR/e2e-email-%02d.json' % i, 'w') as out:
        json.dump(item, out)
print('wrote', len(items), 'files to $INPUT_DIR')
"
  curl -s -X POST "$MONITORING_URL/landing-pad/input/process" > /dev/null
  echo "triggered /landing-pad/input/process (or wait for the file watcher if LANDING_PAD_FILE_WATCHER_ENABLED=true)"
}

send_jira() {
  echo "=== Jira: posting each issue to the webhook endpoint ==="
  if [ -z "$JIRA_SECRET" ]; then
    echo "WARNING: JIRA_WEBHOOK_SECRET not found in .env -- calls will 401/403"
  fi
  python -c "
import json
with open('$DATA_DIR/jira_alerts.json') as f:
    items = json.load(f)
for item in items:
    print(json.dumps(item))
" | while IFS= read -r line; do
    curl -s -X POST "$MONITORING_URL/api/v1/alerts/jira?token=$JIRA_SECRET" -H "Content-Type: application/json" \
      -d "$line" > /dev/null
  done
  echo "sent 25 Jira webhook payloads"
}

send_logs() {
  echo "=== Logs: appending log_alerts.jsonl to a watched log path ==="
  echo "This channel is background-polled (LOG_WATCH_PATHS), not an HTTP endpoint."
  echo "Copy scripts/test-data/log_alerts.jsonl into whatever directory LOG_WATCH_PATHS points at,"
  echo "or append its lines to an existing watched file, e.g.:"
  echo "  cat $DATA_DIR/log_alerts.jsonl >> /path/in/LOG_WATCH_PATHS/e2e-test.log"
}

send_invalid() {
  echo "=== Invalid/malformed cases: sending each with its documented expected outcome ==="
  python -c "
import json
with open('$DATA_DIR/invalid_alerts.json') as f:
    cases = json.load(f)
for c in cases:
    print(c['case'] + '|' + c['endpoint'] + '|' + c['expect'])
" | while IFS='|' read -r case endpoint expect; do
    echo "--- $case ---"
    echo "endpoint: $endpoint"
    echo "expect:   $expect"
  done
  echo
  echo "Each case's exact body is in invalid_alerts.json (per-case 'body' or 'raw_body' key)."
  echo "Send them individually and compare the real response against 'expect' -- deliberately"
  echo "not auto-sent in a loop here, since several intentionally hit different endpoints/methods."
}

send_duplicates() {
  echo "=== Duplicates: sending each channel's payload TWICE to test dedup ==="
  python -c "
import json
d = json.load(open('$DATA_DIR/duplicate_alerts.json'))
print(d['prometheus']['endpoint'])
print(json.dumps(d['prometheus']['payload']))
" | { read -r endpoint; read -r body;
    echo "--- prometheus (send #1, expect accepted) ---"
    curl -s -X POST "$MONITORING_URL/alerts/alertmanager" -H "Content-Type: application/json" -d "$body"; echo
    echo "--- prometheus (send #2, identical -- expect skipped) ---"
    curl -s -X POST "$MONITORING_URL/alerts/alertmanager" -H "Content-Type: application/json" -d "$body"; echo
  }
  python -c "
import json
d = json.load(open('$DATA_DIR/duplicate_alerts.json'))
print(json.dumps(d['dynatrace']['payload']))
" | { read -r body
    echo "--- dynatrace (send #1, expect status=accepted) ---"
    curl -s -X POST "$MONITORING_URL/api/v1/alerts/dynatrace" -H "Content-Type: application/json" -d "$body"; echo
    echo "--- dynatrace (send #2, identical -- expect status=deduplicated) ---"
    curl -s -X POST "$MONITORING_URL/api/v1/alerts/dynatrace" -H "Content-Type: application/json" -d "$body"; echo
  }
  echo
  echo "Email and Jira duplicate payloads are in duplicate_alerts.json ('email'/'jira' keys) --"
  echo "send those the same way as send_email/send_jira, twice, and compare behavior."
}

send_poison() {
  echo "=== Poison messages: publishing malformed bodies DIRECTLY to RabbitMQ ==="
  echo "These bypass monitoring-adapter entirely -- it would never itself produce a"
  echo "malformed envelope, so this tests common/rabbitmq.py's consume_forever() defenses directly."
  RABBIT_USER="${RABBIT_USER:-guest}"
  RABBIT_PASS="${RABBIT_PASS:-guest}"
  QUEUE="kaiops.context-agent.orchestration-events"
  EXCHANGE="kaiops.events"
  python -c "
import json
cases = json.load(open('$DATA_DIR/poison_messages.json'))
for c in cases:
    print(c['case'] + '\t' + c['raw_body'])
" | while IFS=$'\t' read -r case raw_body; do
    echo "--- $case ---"
    payload=$(python -c "
import json
print(json.dumps({'properties': {}, 'routing_key': '$QUEUE', 'payload': '''$raw_body'''.replace(chr(39)+chr(39)+chr(39), ''), 'payload_encoding': 'string'}))
")
    curl -s -u "$RABBIT_USER:$RABBIT_PASS" -X POST \
      "http://localhost:15672/api/exchanges/%2F/$EXCHANGE/publish" \
      -H "Content-Type: application/json" \
      -d "$payload"
    echo
  done
  echo
  echo "Check: docker logs kaiops_pubsub-context-agent-1 | grep -E 'failed to decode|context_agent_batch'"
  echo "and the DLQ depth: curl -s -u $RABBIT_USER:$RABBIT_PASS http://localhost:15672/api/queues/%2F/$QUEUE.dlq"
}

case "$MODE" in
  prometheus) send_prometheus ;;
  email) send_email ;;
  jira) send_jira ;;
  logs) send_logs ;;
  invalid) send_invalid ;;
  duplicates) send_duplicates ;;
  poison) send_poison ;;
  all)
    send_prometheus
    send_email
    send_jira
    send_logs
    send_invalid
    send_duplicates
    send_poison
    ;;
  *)
    echo "usage: $0 [prometheus|email|jira|logs|invalid|duplicates|poison|all]"
    exit 1
    ;;
esac
