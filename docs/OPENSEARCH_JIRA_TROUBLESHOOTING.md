# OpenSearch error-to-Jira troubleshooting

The monitoring adapter can poll recent `error`, `exception`, `critical`,
`fatal`, `failed`, and `failure` records from the Telemetry OpenSearch index.
Each new document is converted to a KaiOps alert with its OpenSearch evidence
URI and trace ID.

Recurring messages are normalized by removing timestamps, IDs, and counters.
The normalized fingerprint creates one Jira issue for the first occurrence and
adds comments for later occurrences.

After Jira accepts the create/update, the alert is published to the normal
KaiOps workflow. Alert Intelligence opens the incident; Context Agent calls
Discovery MCP, which searches current OpenSearch logs, telemetry, code,
tickets, database evidence, and RAG documents. Resolution then consumes that
enriched context.

## Configuration

Set these values in the root `.env` before recreating `monitoring-adapter`:

```dotenv
# Keep legacy Prometheus/email routing independent unless explicitly wanted.
CENTRALIZED_JIRA_ROUTING_ENABLED=false
JIRA_API_BASE_URL=https://your-domain.atlassian.net
JIRA_API_EMAIL=automation@example.com
JIRA_API_TOKEN=replace-with-secret
JIRA_PROJECT_KEY=OPS

OPENSEARCH_LOG_INGESTION_ENABLED=true
OPENSEARCH_LOG_URL=http://host.docker.internal:9200
OPENSEARCH_LOG_INDEX=otel-*
OPENSEARCH_LOG_POLL_INTERVAL_SECONDS=30
OPENSEARCH_LOG_LOOKBACK_SECONDS=300
OPENSEARCH_LOG_BATCH_SIZE=100
OPENSEARCH_LOG_TRIGGER_TROUBLESHOOTING=true
OPENSEARCH_LOG_JIRA_ROUTING_ENABLED=true
PROMETHEUS_JIRA_ROUTING_ENABLED=true
EMAIL_JIRA_ROUTING_ENABLED=true

# Production guardrails
JIRA_RECURRENCE_WINDOW_SECONDS=300
JIRA_COMMENT_COOLDOWN_SECONDS=900
JIRA_MAX_NEW_ISSUES_PER_HOUR=2
JIRA_LOG_MIN_OCCURRENCES=3
JIRA_PROMETHEUS_MIN_OCCURRENCES=2
JIRA_EMAIL_MIN_OCCURRENCES=1
JIRA_ALLOWED_SEVERITIES=warning,high,critical
JIRA_TRIGGER_TROUBLESHOOTING=true
JIRA_TRIGGER_ON_COMMENT=false
NONACTIONABLE_ALERT_PUBLISH_ENABLED=false
```

Activate it with:

```sh
docker compose build monitoring-adapter
docker compose up -d monitoring-adapter
```

The worker uses an overlapping lookback window and a bounded persistent
document-ID checkpoint at the shared landing pad. It therefore tolerates brief
OpenSearch or adapter outages without creating repeated tickets.

## Jira issue format

Machine-formatted log prefixes are not copied into the Jira summary. The
adapter extracts the service, severity, human message, and recognizable
failure reason to produce:

`[SEVERITY] service: concise failure`

The description contains incident summary, classification, original error
details, evidence identifiers, and automated troubleshooting status.
Recurring events retain the stable fingerprint and append structured evidence
to the existing issue as a comment.

Keep `OPENSEARCH_LOG_JIRA_ROUTING_ENABLED=false` while onboarding or tuning a
new telemetry source. Review its error cardinality and checkpoint before
explicitly enabling Jira routing. This prevents an unseen high-cardinality
stream from creating a burst of issues.

## End-to-end pipeline

All sources use the same controlled path:

1. OpenSearch polling, Alertmanager webhook, or IMAP polling receives evidence.
2. The adapter normalizes the payload and computes a stable fingerprint.
3. The admission layer checks severity, recurrence, hourly creation budget,
   and comment cooldown.
4. Jira receives either a structured new issue or a recurring-evidence comment.
5. A newly created Jira issue is published to the dedicated
   `jira-investigations` priority channel with its ticket key. Alert
   Intelligence consumes this separately from the general `raw-alerts`
   backlog.
6. Alert Intelligence, Context Agent, and Discovery MCP perform investigation.
7. Every decision emits a `jira_pipeline` log with stage, outcome, source,
   fingerprint, and Jira key where applicable.

Critical alerts bypass the recurrence threshold but still respect the global
hourly Jira creation budget. Existing issues receive at most one automated
comment per cooldown period. Investigation is triggered for new issues by
default; repeated comments do not repeatedly launch expensive discovery.

Non-actionable and suppressed records are not published to `raw-alerts`.
Their original documents remain in OpenSearch for the live-stream Logs view,
and the adapter emits a `jira_pipeline` classification record explaining
whether the event was deferred, severity-suppressed, cooldown-suppressed, or
rate-limited. Set `NONACTIONABLE_ALERT_PUBLISH_ENABLED=true` only for a
deliberate bulk-analysis workflow; it is disabled for operations.
