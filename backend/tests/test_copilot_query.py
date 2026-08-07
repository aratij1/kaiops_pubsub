"""Phase 0 Copilot: deterministic intent matching and answer composition.

These test the pure functions in api_gateway.copilot directly -- no app, no
DB, no network -- since that module intentionally has zero I/O so intent
matching and answer text can be verified in isolation.
"""

from api_gateway.copilot import (
    classify_intent,
    compose_assignment_answer,
    compose_capacity_answer,
    compose_forbidden_onboarding_answer,
    compose_onboarding_answer,
    compose_unsupported_answer,
    extract_incident_id,
)


def test_classify_intent_recognizes_capacity_question() -> None:
    assert classify_intent("Who has capacity this week?") == "capacity"
    assert classify_intent("who has availability right now") == "capacity"


def test_classify_intent_recognizes_assignment_question() -> None:
    assert classify_intent("Why wasn't INC-123 assigned?") == "assignment"


def test_classify_intent_recognizes_onboarding_question() -> None:
    assert classify_intent("What's pending in onboarding?") == "onboarding"


def test_classify_intent_returns_none_for_unsupported_question() -> None:
    assert classify_intent("What's the weather like today?") is None
    assert classify_intent("") is None
    assert classify_intent("   ") is None


def test_extract_incident_id_finds_ticket_key_and_uuid() -> None:
    assert extract_incident_id("why wasn't INC-123 assigned") == "INC-123"
    assert extract_incident_id("status of 11111111-1111-4111-8111-111111111111 please") == "11111111-1111-4111-8111-111111111111"
    assert extract_incident_id("why wasn't this assigned") is None


def test_compose_capacity_answer_ranks_by_remaining_hours() -> None:
    rows = [
        {"username": "alice", "active": True, "remaining_hours": 2},
        {"username": "bob", "active": True, "remaining_hours": 10},
        {"username": "carol", "active": False, "remaining_hours": 20},
        {"username": "dave", "active": True, "remaining_hours": 0},
    ]
    result = compose_capacity_answer(rows)
    assert result["intent"] == "capacity"
    assert "bob (10h remaining)" in result["answer"]
    assert "alice (2h remaining)" in result["answer"]
    assert "carol" not in result["answer"]  # inactive, excluded
    assert "dave" not in result["answer"]  # zero remaining, excluded
    assert result["links"][0]["path"] == "/approvals"


def test_compose_capacity_answer_handles_nobody_available() -> None:
    result = compose_capacity_answer([{"username": "alice", "active": True, "remaining_hours": 0}])
    assert "No responder currently has remaining capacity" in result["answer"]


def test_compose_assignment_answer_without_incident_id_asks_for_one() -> None:
    result = compose_assignment_answer([], None)
    assert "couldn't find an incident or ticket ID" in result["answer"]


def test_compose_assignment_answer_reports_no_record_found() -> None:
    result = compose_assignment_answer([{"incident_id": "INC-999", "status": "assigned"}], "INC-123")
    assert "No assignment record exists for INC-123" in result["answer"]


def test_compose_assignment_answer_reports_unassigned_reason() -> None:
    rows = [{"incident_id": "INC-123", "status": "unassigned", "assignment_reason": "No on-duty responder had matching resources."}]
    result = compose_assignment_answer(rows, "INC-123")
    assert "unassigned" in result["answer"]
    assert "No on-duty responder had matching resources." in result["answer"]


def test_compose_assignment_answer_reports_assignee() -> None:
    rows = [{"incident_id": "INC-123", "status": "assigned", "assignee": "alice", "assignment_reason": "Matched checkout resources."}]
    result = compose_assignment_answer(rows, "INC-123")
    assert "assigned to alice" in result["answer"]


def test_compose_onboarding_answer_lists_pending_projects() -> None:
    rows = [
        {"project_name": "checkout", "test_status": "connected"},
        {"project_name": "payments", "test_status": "failed"},
        {"project_name": "inventory", "test_status": None},
    ]
    result = compose_onboarding_answer(rows)
    assert "2 onboarding item(s) pending" in result["answer"]
    assert "payments (failed)" in result["answer"]
    assert "inventory (not tested)" in result["answer"]
    assert "checkout" not in result["answer"]


def test_compose_onboarding_answer_handles_all_connected() -> None:
    result = compose_onboarding_answer([{"project_name": "checkout", "test_status": "connected"}])
    assert "Nothing is pending" in result["answer"]


def test_compose_unsupported_answer_explains_supported_intents() -> None:
    result = compose_unsupported_answer("what's the weather")
    assert result["intent"] is None
    assert "capacity" in result["answer"].lower()
    assert "onboarding" in result["answer"].lower()


def test_compose_forbidden_onboarding_answer_does_not_leak_data() -> None:
    result = compose_forbidden_onboarding_answer()
    assert result["data"] == {}
    assert "Administrators" in result["answer"]
