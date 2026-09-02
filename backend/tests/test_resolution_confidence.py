from resolution_agent.confidence import ConfidenceInputs, score_confidence
from resolution_agent.graph import _canonicalize_rationale_confidence


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


def test_missing_evidence_strictly_lowers_confidence() -> None:
    complete = score_confidence(ConfidenceInputs(
        evidence_quality=0.8, evidence_consistency=0.8, causal_strength=0.8,
        independent_source_corroboration=0.8, temporal_alignment=0.8,
        topology_alignment=0.8, historical_similarity=0.8, successful_test_ratio=0.8,
    ))
    incomplete = score_confidence(ConfidenceInputs(
        evidence_quality=0.8, evidence_consistency=0.8, causal_strength=0.8,
        independent_source_corroboration=0.8, temporal_alignment=0.8,
        topology_alignment=0.8, historical_similarity=0.8, successful_test_ratio=0.8,
        missing_data_penalty=0.3, sources_unavailable=True,
    ))

    assert incomplete.score < complete.score
    assert incomplete.penalties["missing_data"] == 0.3


def test_unavailable_optional_dimensions_are_not_scored_as_observed_failures() -> None:
    result = score_confidence(ConfidenceInputs(
        evidence_quality=0.8, evidence_consistency=0.8, causal_strength=0.8,
        independent_source_corroboration=0.8, temporal_alignment=0.8,
        topology_alignment=0.0, historical_similarity=0.0, successful_test_ratio=0.0,
        available_components=frozenset({
            "evidence_quality", "evidence_consistency", "causal_strength",
            "independent_source_corroboration", "temporal_alignment",
        }),
    ))

    assert result.score == 0.8
    assert "topology_alignment" not in result.components
    assert "historical_similarity" not in result.components
    assert "successful_test_ratio" not in result.components


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


def test_operator_rationale_uses_canonical_bounded_confidence() -> None:
    rationale = (
        "Model reasoning-critical proposed the RCA with 3 validated evidence "
        "citation(s); confidence=0.49."
    )

    result = _canonicalize_rationale_confidence(rationale, 0.5707)

    assert "canonical diagnostic confidence=0.57" in result
    assert "confidence=0.49" not in result
