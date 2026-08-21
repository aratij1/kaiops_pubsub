from resolution_agent.confidence import ConfidenceInputs, score_confidence


def test_confidence_uses_documented_deterministic_weights() -> None:
    result = score_confidence(ConfidenceInputs(
        evidence_quality=1.0,
        evidence_consistency=1.0,
        causal_strength=1.0,
        independent_source_corroboration=1.0,
        temporal_alignment=1.0,
        topology_alignment=1.0,
        historical_similarity=1.0,
        successful_test_ratio=1.0,
    ))

    assert result.score == 1.0
    assert result.components == {
        "evidence_quality": 0.18,
        "evidence_consistency": 0.14,
        "causal_strength": 0.18,
        "independent_source_corroboration": 0.14,
        "temporal_alignment": 0.15,
        "topology_alignment": 0.1,
        "historical_similarity": 0.05,
        "successful_test_ratio": 0.06,
    }


def test_unresolved_contradiction_applies_penalty_and_ceiling() -> None:
    result = score_confidence(ConfidenceInputs(
        evidence_quality=1.0,
        evidence_consistency=1.0,
        causal_strength=1.0,
        independent_source_corroboration=1.0,
        temporal_alignment=1.0,
        topology_alignment=1.0,
        historical_similarity=1.0,
        successful_test_ratio=1.0,
        contradiction_penalty=0.1,
        unresolved_contradictions=True,
    ))

    assert result.raw_score == 0.9
    assert result.score == 0.59
    assert result.ceiling == 0.59
    assert result.ceiling_reasons == ("unresolved_contradictions",)


def test_ambiguous_target_has_strictest_confidence_ceiling() -> None:
    result = score_confidence(ConfidenceInputs(
        evidence_quality=1.0,
        evidence_consistency=1.0,
        causal_strength=1.0,
        independent_source_corroboration=1.0,
        temporal_alignment=1.0,
        topology_alignment=1.0,
        historical_similarity=1.0,
        successful_test_ratio=1.0,
        sources_unavailable=True,
        ambiguous_target=True,
    ))

    assert result.score == 0.49
    assert result.ceiling_reasons == ("ambiguous_target",)
