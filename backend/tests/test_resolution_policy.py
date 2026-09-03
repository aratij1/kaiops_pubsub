from resolution_agent.policy import ResolutionPolicyInput, evaluate_resolution_policy


def _input(**overrides):
    payload = {
        "environment": "prod",
        "risk": "medium",
        "confidence": 0.88,
        "runbook_status": "approved",
        "runbook_success_rate": 0.94,
        "mutating": True,
        "reversible": True,
        "canary_supported": True,
        "blast_radius": "single-service",
        "target_verified": True,
        "validation_available": True,
        "rollback_available": True,
        "contradiction_count": 0,
        "rca_conclusive": True,
    }
    payload.update(overrides)
    return ResolutionPolicyInput(**payload)


def test_inconclusive_rca_is_investigation_only() -> None:
    decision = evaluate_resolution_policy(_input(rca_conclusive=False))
    assert decision.decision == "investigate"
    assert decision.reason_codes == ["rca_inconclusive"]


def test_missing_validation_or_rollback_blocks_mutation() -> None:
    decision = evaluate_resolution_policy(_input(validation_available=False, rollback_available=False))
    assert decision.decision == "block"
    assert set(decision.reason_codes) == {"validation_missing", "rollback_missing"}


def test_high_risk_always_requires_hitl() -> None:
    decision = evaluate_resolution_policy(_input(risk="critical", confidence=0.99))
    assert decision.decision == "hitl"
    assert "high_risk_requires_hitl" in decision.reason_codes


def test_hotl_is_disabled_by_default_even_for_eligible_action(monkeypatch) -> None:
    monkeypatch.delenv("RESOLUTION_HOTL_ENABLED", raising=False)
    decision = evaluate_resolution_policy(_input(risk="low", confidence=0.95))
    assert decision.decision == "hitl"
    assert "hotl_disabled_p0_safety_mode" in decision.reason_codes


def test_environment_variable_cannot_enable_hotl_in_p0_safety_mode(monkeypatch) -> None:
    monkeypatch.setenv("RESOLUTION_HOTL_ENABLED", "true")
    decision = evaluate_resolution_policy(_input(risk="low", confidence=0.95))
    assert decision.decision == "hitl"
    assert "hotl_disabled_p0_safety_mode" in decision.reason_codes


def test_acknowledged_recovery_strategy_is_execution_eligible_but_still_not_reversible() -> None:
    # An acknowledged, catalog-declared recovery strategy (docker-compose
    # restart_service with rollback_mode="not_applicable") makes
    # rollback_available True upstream in app.py, but reversible must stay
    # False - this must never be treated as equivalent to a real rollback,
    # and must still require HITL, never bypass to block or autonomous hotl.
    decision = evaluate_resolution_policy(
        _input(rollback_available=True, reversible=False, risk="low", confidence=0.95)
    )
    assert decision.decision == "hitl"
    assert "action_not_reversible" in decision.reason_codes
    assert "rollback_missing" not in decision.reason_codes
    assert "hotl_disabled_p0_safety_mode" in decision.reason_codes


def test_unacknowledged_missing_rollback_still_blocks_even_with_high_confidence() -> None:
    # Negative test: without rollback_available being explicitly set True (the
    # unacknowledged case), a mutating plan must still be blocked - proving
    # the exemption is not a blanket allowance.
    decision = evaluate_resolution_policy(
        _input(rollback_available=False, reversible=False, confidence=0.99)
    )
    assert decision.decision == "block"
    assert "rollback_missing" in decision.reason_codes
