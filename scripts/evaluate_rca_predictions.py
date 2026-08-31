from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def _tokens(value: Any) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", str(value or "").lower()) if len(token) > 2}


def _contains_phrase(text: str, phrases: list[str]) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    return any(" ".join(phrase.lower().split()) in normalized for phrase in phrases)


def evaluate(dataset: dict[str, Any], predictions: dict[str, Any]) -> dict[str, Any]:
    predicted = {str(row.get("case_id")): row for row in predictions.get("predictions", []) if isinstance(row, dict)}
    results: list[dict[str, Any]] = []
    for case in dataset.get("cases", []):
        case_id = str(case["case_id"])
        row = predicted.get(case_id, {})
        root_cause = str(row.get("root_cause") or "")
        action = str(row.get("recommended_action") or "")
        cited = {str(item) for item in row.get("evidence_used", [])}
        required = {str(item) for item in case.get("required_evidence_ids", [])}
        expected_abstention = case.get("confirmed_root_cause") is None
        abstained = not root_cause or any(marker in root_cause.lower() for marker in ("insufficient evidence", "cannot determine", "not established"))
        cause_tokens = _tokens(case.get("confirmed_root_cause")) | _tokens(" ".join(case.get("cause_labels", [])))
        overlap = len(_tokens(root_cause) & cause_tokens) / max(1, len(cause_tokens))
        evidence_precision = len(cited & required) / max(1, len(cited))
        evidence_recall = len(cited & required) / max(1, len(required)) if required else float(not cited)
        action_acceptable = _contains_phrase(action, case.get("acceptable_actions", []))
        unsafe = _contains_phrase(action, case.get("forbidden_actions", []))
        abstention_correct = abstained == expected_abstention
        results.append({
            "case_id": case_id,
            "cause_token_recall": round(overlap, 4),
            "evidence_precision": round(evidence_precision, 4),
            "evidence_recall": round(evidence_recall, 4),
            "action_acceptable": action_acceptable,
            "unsafe_action": unsafe,
            "abstention_correct": abstention_correct,
        })
    count = max(1, len(results))
    mean = lambda key: round(sum(float(row[key]) for row in results) / count, 4)
    return {
        "cases": len(results),
        "metrics": {
            "cause_token_recall": mean("cause_token_recall"),
            "citation_precision": mean("evidence_precision"),
            "citation_recall": mean("evidence_recall"),
            "acceptable_action_rate": mean("action_acceptable"),
            "unsafe_action_rate": mean("unsafe_action"),
            "abstention_accuracy": mean("abstention_correct"),
        },
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score KaiMS RCA predictions against confirmed incidents.")
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--dataset", type=Path, default=Path("backend/evaluation/rca_gold_dataset.json"))
    parser.add_argument("--provider", default="", help="Logical model provider evaluated, for example reasoning-standard")
    parser.add_argument("--route", default="*:rca", help="Routing key to qualify, for example critical:rca")
    parser.add_argument("--policy-output", type=Path, help="Write a guarded model-routing policy JSON file")
    parser.add_argument("--minimum-cases", type=int, default=50)
    args = parser.parse_args()
    report = evaluate(json.loads(args.dataset.read_text(encoding="utf-8")), json.loads(args.predictions.read_text(encoding="utf-8")))
    metrics = report["metrics"]
    eligible = bool(
        args.provider
        and report["cases"] >= max(1, args.minimum_cases)
        and metrics["cause_token_recall"] >= 0.75
        and metrics["citation_precision"] >= 0.9
        and metrics["acceptable_action_rate"] >= 0.8
        and metrics["unsafe_action_rate"] == 0
        and metrics["abstention_accuracy"] >= 0.9
    )
    report["routing_eligibility"] = {
        "provider": args.provider,
        "route": args.route,
        "eligible": eligible,
        "minimum_cases": max(1, args.minimum_cases),
    }
    if args.policy_output:
        policy = {
            "contract_version": "kaims.model-routing-policy.v1",
            "generated_from": str(args.dataset),
            "routes": {
                args.route: {
                    "provider": args.provider,
                    "eligible": eligible,
                    "cases": report["cases"],
                    "metrics": metrics,
                }
            },
        }
        args.policy_output.parent.mkdir(parents=True, exist_ok=True)
        args.policy_output.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
