from common.message_processing import ProcessedMessageCache, extract_message_identity


def test_extract_message_identity_prefers_event_envelope_and_idempotency() -> None:
    payload = {
        "event_envelope": {
            "event_id": "evt-123",
            "idempotency": {"idempotency_key": "idem-123"},
        },
        "event_contract": {"event_id": "contract-123"},
    }

    assert extract_message_identity(payload) == "evt-123"


def test_extract_message_identity_falls_back_to_contract_and_payload_fields() -> None:
    assert extract_message_identity({"event_contract": {"event_id": "contract-123"}}) == "contract-123"
    assert extract_message_identity({"event_id": "evt-456"}) == "evt-456"
    assert extract_message_identity({"idempotency": {"idempotency_key": "idem-456"}}) == "idem-456"


def test_processed_message_cache_marks_and_detects_duplicates() -> None:
    cache = ProcessedMessageCache(ttl_seconds=3600, max_entries=4)

    assert cache.contains("evt-1") is False
    cache.mark("evt-1")
    assert cache.contains("evt-1") is True