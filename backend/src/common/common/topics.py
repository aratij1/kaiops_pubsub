RAW_ALERTS = "raw-alerts"
ENRICHED_ALERTS = "enriched-alerts"
ORCHESTRATION_EVENTS = "orchestration-events"
CONTEXT_EVENTS = "context-events"
RESOLUTION_EVENTS = "resolution-events"
APPROVAL_EVENTS = "approval-events"
REMEDIATION_EVENTS = "remediation-events"
CLOSURE_EVENTS = "closure-events"

# Versioned topic taxonomy for enterprise routing. Legacy topic names remain unchanged.
COMMANDS_TOPIC_V1 = "kaiops.commands.v1"
EVENTS_TOPIC_V1 = "kaiops.events.v1"
RESULTS_TOPIC_V1 = "kaiops.results.v1"
RETRY_TOPIC_V1 = "kaiops.retry.v1"
DEAD_LETTER_TOPIC_V1 = "kaiops.dlq.v1"
NOTIFICATIONS_TOPIC_V1 = "kaiops.notifications.v1"

ALL_TOPICS = [
    RAW_ALERTS,
    ENRICHED_ALERTS,
    ORCHESTRATION_EVENTS,
    CONTEXT_EVENTS,
    RESOLUTION_EVENTS,
    APPROVAL_EVENTS,
    REMEDIATION_EVENTS,
    CLOSURE_EVENTS,
    COMMANDS_TOPIC_V1,
    EVENTS_TOPIC_V1,
    RESULTS_TOPIC_V1,
    RETRY_TOPIC_V1,
    DEAD_LETTER_TOPIC_V1,
    NOTIFICATIONS_TOPIC_V1,
]
