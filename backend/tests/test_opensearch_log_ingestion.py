from monitoring_adapter.log_ingestion import log_line_to_alert_payload, readable_error_title, stable_error_signature


def test_stable_error_signature_groups_volatile_values() -> None:
    first = "2026-07-26T09:25:50Z ERROR request 123 failed trace abcdef1234567890"
    second = "2026-07-26T09:26:51Z ERROR request 456 failed trace fedcba0987654321"

    assert stable_error_signature(first) == stable_error_signature(second)


def test_opensearch_record_preserves_evidence_and_service() -> None:
    payload = log_line_to_alert_payload(
        {
            "document_id": "doc-123",
            "source_path": "opensearch://otel-*/doc-123",
            "service": "checkout",
            "project_name": "Telemetry",
            "container_name": "telemetry-checkout",
            "trace_id": "trace-123",
            "line": "ERROR checkout database request 42 failed",
        },
        default_service="log-ingestion",
    )

    assert payload is not None
    assert payload["source"] == "logs"
    assert payload["service"] == "checkout"
    assert payload["labels"]["project_name"] == "Telemetry"
    assert payload["labels"]["container_name"] == "telemetry-checkout"
    assert payload["labels"]["opensearch_document_id"] == "doc-123"
    assert payload["labels"]["trace_id"] == "trace-123"
    assert payload["labels"]["error_signature"]


def test_non_error_log_is_ignored() -> None:
    assert (
        log_line_to_alert_payload(
            {"line": "INFO checkout request completed", "source_path": "opensearch://otel-*/ok"},
            default_service="checkout",
        )
        is None
    )


def test_machine_formatted_log_gets_readable_title() -> None:
    line = (
        'ts=2026-07-26T10:19:26Z caller=notify.go:848 level=warn '
        'component=dispatcher receiver=kaiops integration=webhook[0] '
        'msg="Notify attempt failed, will retry later" '
        'err="Post http://example: dial tcp 172.18.0.21:8000: connect: connection refused"'
    )

    title = readable_error_title(line, "alertmanager", "warning")

    assert title == "[WARNING] alertmanager: Notify attempt failed, will retry later: connection refused"
    assert "ts=" not in title
