from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from monitoring_adapter.landing_pad_sources import load_landing_pad_file

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_generator():
    module_path = REPO_ROOT / "scripts" / "generate_email_tickets.py"
    spec = importlib.util.spec_from_file_location("generate_email_tickets", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["generate_email_tickets"] = module
    spec.loader.exec_module(module)
    return module


def _sample_csv(path: Path) -> Path:
    path.write_text(
        "Issue ID,Summary,Description,Priority,Status,Component/s,Labels,Environment,"
        "Alert Name,Service,Severity,Incident Correlation ID\n"
        "KAI-1,High error rate on checkout-api,Faulty release,Highest,Closed,Application,"
        "\"kaiops,kaiops-scenario-01\",Production,High error rate,checkout-api,Critical,INC-1\n"
        "KAI-2,Consumer lag on orders-api,Backlog,Medium,Closed,Queue,"
        "\"kaiops,kaiops-scenario-07\",Staging,Consumer lag,orders-api,Medium,INC-2\n",
        encoding="utf-8",
    )
    return path


def test_generate_email_tickets_roundtrip(tmp_path: Path) -> None:
    gen = _load_generator()
    source = _sample_csv(tmp_path / "tickets.csv")
    input_dir = tmp_path / "input"

    written = gen.generate(source, input_dir, count=10, sender="alerts@kaiops.local")
    assert len(written) == 2
    assert all(path.suffix == ".eml" for path in written)

    by_service = {}
    for path in written:
        rows = load_landing_pad_file(path)
        assert len(rows) == 1
        alert, _raw = rows[0]
        assert alert["source"] == "email"
        by_service[alert["service"]] = alert

    # Header-derived service/severity/environment populate the mapped alert.
    # environment is normalized to its canonical short form ("production" -> "prod").
    checkout = by_service["checkout-api"]
    assert checkout["severity"] == "critical"
    assert checkout["environment"] == "prod"
    assert checkout["labels"]["incident_correlation_id"] == "INC-1"

    orders = by_service["orders-api"]
    assert orders["severity"] == "warning"  # "Medium" -> warning


def test_generate_email_tickets_respects_count(tmp_path: Path) -> None:
    gen = _load_generator()
    source = _sample_csv(tmp_path / "tickets.csv")
    input_dir = tmp_path / "input"

    written = gen.generate(source, input_dir, count=1, sender="alerts@kaiops.local")
    assert len(written) == 1
