from resolution_agent.confidence import ConfidenceInputs, score_confidence


def test_confidence_uses_documented_deterministic_weights() -> None:
    result = score_confidence(ConfidenceInputs(
        evidence_completeness=1.0,
        independent_source_corroboration=1.0,
        temporal_alignment=1.0,
        topology_support=1.0,
        change_correlation=1.0,
        approved_runbook_applicability=1.0,
        historical_success_rate=1.0,
    ))

    assert result.score == 1.0
    assert result.components == {
        "evidence_completeness": 0.25,
        "independent_source_corroboration": 0.2,
        "temporal_alignment": 0.15,
        "topology_support": 0.15,
        "change_correlation": 0.1,
        "approved_runbook_applicability": 0.1,
        "historical_success_rate": 0.05,
    }


def test_unresolved_contradiction_applies_penalty_and_ceiling() -> None:
    result = score_confidence(ConfidenceInputs(
        evidence_completeness=1.0,
        independent_source_corroboration=1.0,
        temporal_alignment=1.0,
        topology_support=1.0,
        change_correlation=1.0,
        approved_runbook_applicability=1.0,
        historical_success_rate=1.0,
        contradiction_penalty=0.1,
        unresolved_contradictions=True,
    ))

    assert result.raw_score == 0.9
    assert result.score == 0.59
    assert result.ceiling == 0.59
    assert result.ceiling_reasons == ("unresolved_contradictions",)


def test_ambiguous_target_has_strictest_confidence_ceiling() -> None:
    result = score_confidence(ConfidenceInputs(
        evidence_completeness=1.0,
        independent_source_corroboration=1.0,
        temporal_alignment=1.0,
        topology_support=1.0,
        change_correlation=1.0,
        approved_runbook_applicability=1.0,
        historical_success_rate=1.0,
        sources_unavailable=True,
        ambiguous_target=True,
    ))

    assert result.score == 0.49
    assert result.ceiling_reasons == ("ambiguous_target",)
