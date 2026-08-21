from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConfidenceInputs:
    evidence_quality: float
    evidence_consistency: float
    causal_strength: float
    independent_source_corroboration: float
    temporal_alignment: float
    topology_alignment: float
    historical_similarity: float
    successful_test_ratio: float
    contradiction_penalty: float = 0.0
    freshness_penalty: float = 0.0
    missing_data_penalty: float = 0.0
    sources_unavailable: bool = False
    stale_evidence: bool = False
    model_fallback: bool = False
    degraded_context: bool = False
    unresolved_contradictions: bool = False
    ambiguous_target: bool = False


@dataclass(frozen=True)
class ConfidenceResult:
    score: float
    raw_score: float
    ceiling: float
    components: dict[str, float] = field(default_factory=dict)
    penalties: dict[str, float] = field(default_factory=dict)
    ceiling_reasons: tuple[str, ...] = ()


def _unit(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def score_confidence(inputs: ConfidenceInputs) -> ConfidenceResult:
    """Calculate confidence from evidence facts, never model self-assessment."""

    components = {
        "evidence_quality": 0.18 * _unit(inputs.evidence_quality),
        "evidence_consistency": 0.14 * _unit(inputs.evidence_consistency),
        "causal_strength": 0.18 * _unit(inputs.causal_strength),
        "independent_source_corroboration": 0.14 * _unit(inputs.independent_source_corroboration),
        "temporal_alignment": 0.15 * _unit(inputs.temporal_alignment),
        "topology_alignment": 0.10 * _unit(inputs.topology_alignment),
        "historical_similarity": 0.05 * _unit(inputs.historical_similarity),
        "successful_test_ratio": 0.06 * _unit(inputs.successful_test_ratio),
    }
    penalties = {
        "contradictions": min(_unit(inputs.contradiction_penalty), 0.35),
        "freshness": min(_unit(inputs.freshness_penalty), 0.25),
        "missing_data": min(_unit(inputs.missing_data_penalty), 0.30),
    }
    raw = max(0.0, min(sum(components.values()) - sum(penalties.values()), 1.0))
    ceilings: list[tuple[str, float]] = []
    if inputs.sources_unavailable:
        ceilings.append(("required_sources_unavailable", 0.79))
    if inputs.stale_evidence:
        ceilings.append(("stale_evidence", 0.69))
    if inputs.model_fallback:
        ceilings.append(("model_fallback", 0.59))
    if inputs.degraded_context:
        ceilings.append(("degraded_context", 0.69))
    if inputs.unresolved_contradictions:
        ceilings.append(("unresolved_contradictions", 0.59))
    if inputs.ambiguous_target:
        ceilings.append(("ambiguous_target", 0.49))
    ceiling = min((value for _, value in ceilings), default=1.0)
    return ConfidenceResult(
        score=round(min(raw, ceiling), 4),
        raw_score=round(raw, 4),
        ceiling=ceiling,
        components={key: round(value, 4) for key, value in components.items()},
        penalties={key: round(value, 4) for key, value in penalties.items()},
        ceiling_reasons=tuple(reason for reason, _ in ceilings if _ == ceiling),
    )
