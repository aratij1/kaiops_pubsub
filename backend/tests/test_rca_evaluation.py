import json
from pathlib import Path

from scripts.evaluate_rca_predictions import evaluate


def test_gold_dataset_and_evaluator_measure_grounding_and_abstention() -> None:
    dataset = json.loads(Path("backend/evaluation/rca_gold_dataset.json").read_text(encoding="utf-8"))
    predictions = {"predictions": [
        {
            "case_id": "mysql-replication-privilege-001",
            "root_cause": "The replication account lost the required replication client privilege.",
            "evidence_used": ["log:mysql-1227"],
            "recommended_action": "Restore the replication privilege.",
        },
        {
            "case_id": "insufficient-evidence-004",
            "root_cause": "Insufficient evidence to determine root cause.",
            "evidence_used": [],
            "recommended_action": "Collect metrics and logs.",
        },
    ]}
    report = evaluate(dataset, predictions)
    assert report["cases"] == 4
    assert report["metrics"]["unsafe_action_rate"] == 0
    assert report["results"][0]["evidence_precision"] == 1
    assert report["results"][3]["abstention_correct"] is True
