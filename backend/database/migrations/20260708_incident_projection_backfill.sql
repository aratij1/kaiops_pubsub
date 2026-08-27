-- Backfill incident_projections from existing incidents rows.
-- Idempotent: safe to re-run.
-- NOTE: incident_projections has no created_at column; the historical comment
-- below explains an older ORM assumption and is superseded by this schema fact.

-- created_at is set explicitly even though it's not otherwise used by this
-- projection (first_seen_at/updated_at carry the meaningful timestamps):
-- IncidentProjectionRecord(Base, TimestampMixin) in common/database.py
-- inherits a `created_at` column from TimestampMixin whose `default=utc_now`
-- is a Python-side (ORM-only) default, not a database-level DEFAULT — so the
-- live table's created_at is NOT NULL with no DB default, and a raw INSERT
-- that omits it fails with "doesn't have a default value".
INSERT INTO incident_projections (
    incident_id,
    alert_id,
    trace_id,
    tenant_id,
    service,
    environment,
    severity,
    status,
    owner,
    risk_tier,
    execution_mode,
    requires_approval,
    policy_version,
    policy_reason,
    transport_provider,
    latest_event_id,
    latest_event_type,
    latest_event_at,
    first_seen_at,
    updated_at,
    projection_payload
)
SELECT
    i.id AS incident_id,
    NULL AS alert_id,
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.trace_id')), '') AS trace_id,
    COALESCE(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.tenant_id')), ''), 'default') AS tenant_id,
    i.service,
    i.environment,
    i.severity,
    i.status,
    NULLIF(JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.owner_team')), '') AS owner,
    NULLIF(
        LOWER(
            COALESCE(
                JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.decision.risk_tier')),
                JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.risk_tier')),
                JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.risk'))
            )
        ),
        ''
    ) AS risk_tier,
    NULLIF(
        LOWER(
            COALESCE(
                JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.decision.execution_mode')),
                JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.execution_mode'))
            )
        ),
        ''
    ) AS execution_mode,
    CASE
        WHEN LOWER(
            COALESCE(
                JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.decision.requires_approval')),
                JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.requires_approval')),
                'false'
            )
        ) IN ('1', 'true', 'yes', 'on') THEN TRUE
        ELSE FALSE
    END AS requires_approval,
    NULLIF(
        COALESCE(
            JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.decision.policy_version')),
            JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.policy_version'))
        ),
        ''
    ) AS policy_version,
    NULLIF(
        COALESCE(
            JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.decision.policy_reason')),
            JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.policy_reason'))
        ),
        ''
    ) AS policy_reason,
    NULLIF(
        LOWER(
            COALESCE(
                JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.decision.message_bus_provider')),
                JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.transport_provider'))
            )
        ),
        ''
    ) AS transport_provider,
    NULL AS latest_event_id,
    'incident.backfill' AS latest_event_type,
    i.updated_at AS latest_event_at,
    i.created_at AS first_seen_at,
    i.updated_at AS updated_at,
    i.payload AS projection_payload
FROM incidents i
ON DUPLICATE KEY UPDATE
    alert_id = VALUES(alert_id),
    trace_id = VALUES(trace_id),
    tenant_id = VALUES(tenant_id),
    service = VALUES(service),
    environment = VALUES(environment),
    severity = VALUES(severity),
    status = VALUES(status),
    owner = VALUES(owner),
    risk_tier = VALUES(risk_tier),
    execution_mode = VALUES(execution_mode),
    requires_approval = VALUES(requires_approval),
    policy_version = VALUES(policy_version),
    policy_reason = VALUES(policy_reason),
    transport_provider = VALUES(transport_provider),
    latest_event_id = VALUES(latest_event_id),
    latest_event_type = VALUES(latest_event_type),
    latest_event_at = VALUES(latest_event_at),
    updated_at = VALUES(updated_at),
    projection_payload = VALUES(projection_payload);
