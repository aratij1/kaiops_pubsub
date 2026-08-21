"""Phase 0 Copilot: deterministic intent matching and answer composition.

These test the pure functions in api_gateway.copilot directly -- no app, no
DB, no network -- since that module intentionally has zero I/O so intent
matching and answer text can be verified in isolation.
"""

from api_gateway.copilot import (
    classify_intent,
    compose_approval_status_answer,
    compose_assignment_answer,
    compose_capacity_answer,
    compose_forbidden_onboarding_answer,
    compose_incident_summary_answer,
    compose_onboarding_answer,
    compose_rca_answer,
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


def test_classify_intent_recognizes_rca_question() -> None:
    assert classify_intent("Explain the lowest-confidence RCA") == "rca"
    assert classify_intent("What's the root cause of INC-123?") == "rca"
    assert classify_intent("What is the confidence on this recommendation?") == "rca"


def test_classify_intent_recognizes_approval_status_question() -> None:
    assert classify_intent("Show work waiting for approval") == "approval_status"
    assert classify_intent("What's the approval status of INC-123?") == "approval_status"
    assert classify_intent("Was INC-123 approved?") == "approval_status"


def test_classify_intent_recognizes_incident_summary_question() -> None:
    assert classify_intent("Summarize what needs attention") == "incident_summary"
    assert classify_intent("What are the recent incidents?") == "incident_summary"
    assert classify_intent("Show me open incidents") == "incident_summary"


def test_classify_intent_recognizes_needs_setup_onboarding_phrasing() -> None:
    # "Which application needs setup?" is one of the Copilot suggested prompts;
    # it must resolve to the onboarding intent, not fall through unsupported.
    assert classify_intent("Which application needs setup?") == "onboarding"


def test_classify_intent_all_four_suggested_prompts_are_supported() -> None:
    suggested_prompts = [
        "Summarize what needs attention",
        "Explain the lowest-confidence RCA",
        "Show work waiting for approval",
        "Which application needs setup?",
    ]
    for prompt in suggested_prompts:
        assert classify_intent(prompt) is not None, f"suggested prompt {prompt!r} matched no intent"


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


def test_compose_rca_answer_without_incident_id_asks_for_one() -> None:
    result = compose_rca_answer(None, None)
    assert result["intent"] == "rca"
    assert "couldn't find an incident or ticket ID" in result["answer"]


def test_compose_rca_answer_reports_no_completed_rca() -> None:
    result = compose_rca_answer({"id": "inc-1", "status": "investigating"}, "INC-123")
    assert "No completed root-cause analysis exists yet for INC-123" in result["answer"]


def test_compose_rca_answer_reports_not_found() -> None:
    result = compose_rca_answer({"incident_id": "INC-123", "status": "unknown"}, "INC-123")
    assert "No completed root-cause analysis exists yet for INC-123" in result["answer"]


def test_compose_rca_answer_without_incident_id_or_candidate_says_none_available() -> None:
    result = compose_rca_answer(None, None)
    assert "no recommendation history is available to pick one automatically" in result["answer"]


def test_compose_rca_answer_auto_selected_names_the_incident_and_confidence() -> None:
    incident = {
        "id": "inc-1",
        "status": "investigating",
        "recommendation": {
            "root_cause": "Payment gateway connection timeouts after Deployment 2.5.",
            "confidence": 0.221,
            "recommended_action": "Rollback deployment",
        },
    }
    result = compose_rca_answer(incident, "INC-123", was_auto_selected=True)
    assert result["intent"] == "rca"
    assert "The lowest-confidence recommendation I could find is for INC-123 (22% confidence)." in result["answer"]
    assert "Payment gateway connection timeouts after Deployment 2.5." in result["answer"]
    assert "Rollback deployment" in result["answer"]
    # the auto-selection preamble already states confidence, so the redundant trailing
    # "(XX% confidence.)" suffix used on the manual-ID path must not also appear
    assert "confidence.)" not in result["answer"]


def test_compose_rca_answer_auto_selected_but_no_completed_rca() -> None:
    result = compose_rca_answer({"id": "inc-1", "status": "investigating"}, "INC-123", was_auto_selected=True)
    assert "No completed root-cause analysis exists yet for INC-123" in result["answer"]


def test_compose_rca_answer_reports_root_cause_confidence_and_action() -> None:
    incident = {
        "id": "inc-1",
        "status": "investigating",
        "recommendation": {
            "root_cause": "Payment gateway connection timeouts after Deployment 2.5.",
            "confidence": 0.665,
            "recommended_action": "Rollback deployment",
        },
    }
    result = compose_rca_answer(incident, "INC-123")
    assert result["intent"] == "rca"
    assert "Payment gateway connection timeouts after Deployment 2.5." in result["answer"]
    assert "66%" in result["answer"] or "67%" in result["answer"]
    assert "Rollback deployment" in result["answer"]
    assert result["data"]["recommendation"]["confidence"] == 0.665


def test_compose_approval_status_answer_without_incident_id_asks_for_one() -> None:
    result = compose_approval_status_answer(None, None)
    assert result["intent"] == "approval_status"
    assert "couldn't find an incident or ticket ID" in result["answer"]


def test_compose_approval_status_answer_reports_not_found() -> None:
    result = compose_approval_status_answer({"incident_id": "INC-123", "status": "unknown"}, "INC-123")
    assert "No incident record was found for INC-123" in result["answer"]


def test_compose_approval_status_answer_reports_awaiting_approval() -> None:
    incident = {
        "id": "inc-1",
        "status": "awaiting_approval",
        "recommendation": {"recommended_action": "Rollback deployment"},
    }
    result = compose_approval_status_answer(incident, "INC-123")
    assert "INC-123 is awaiting approval" in result["answer"]
    assert "Rollback deployment" in result["answer"]


def test_compose_approval_status_answer_reports_not_pending() -> None:
    incident = {"id": "inc-1", "status": "closed", "recommendation": {"root_cause": "x"}}
    result = compose_approval_status_answer(incident, "INC-123")
    assert "not waiting on an approval decision" in result["answer"]


def test_compose_incident_summary_answer_ranks_by_risk_and_excludes_closed() -> None:
    rows = [
        {"service": "checkout", "risk_tier": "low", "status": "investigating"},
        {"service": "payments", "risk_tier": "critical", "status": "awaiting_approval"},
        {"service": "inventory", "risk_tier": "high", "status": "closed"},
    ]
    result = compose_incident_summary_answer(rows)
    assert result["intent"] == "incident_summary"
    assert "2 incident(s) need attention" in result["answer"]
    assert result["answer"].index("payments") < result["answer"].index("checkout")
    assert "inventory" not in result["answer"]  # closed, excluded


def test_compose_incident_summary_answer_handles_nothing_open() -> None:
    result = compose_incident_summary_answer([{"service": "checkout", "status": "closed"}])
    assert "Nothing needs attention" in result["answer"]


def test_compose_unsupported_answer_explains_supported_intents() -> None:
    result = compose_unsupported_answer("what's the weather")
    assert result["intent"] is None
    assert "capacity" in result["answer"].lower()
    assert "onboarding" in result["answer"].lower()
    assert "root cause" in result["answer"].lower()
    assert "approval" in result["answer"].lower()


def test_compose_forbidden_onboarding_answer_does_not_leak_data() -> None:
    result = compose_forbidden_onboarding_answer()
    assert result["data"] == {}
    assert "Administrators" in result["answer"]
