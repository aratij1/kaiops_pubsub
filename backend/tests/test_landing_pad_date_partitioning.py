"""Landing-pad archives (processed/failed/input_replayed/input_failed) are
partitioned by UTC date (YYYY/MM/DD) so no single directory accumulates an
unbounded number of entries as tickets, emails and fault-lab alerts stream in.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def load_monitoring_app_module():
    module_path = Path("backend/src/monitoring-adapter/app.py")
    spec = importlib.util.spec_from_file_location("monitoring_adapter_app_partitioning", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def monitoring_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LANDING_PAD_INPUT_DIR", str(tmp_path / "input"))
    module = load_monitoring_app_module()
    module.LANDING_PAD_INPUT_DIR = tmp_path / "input"
    module.LANDING_PAD_PROCESSED_DIR = tmp_path / "processed"
    module.LANDING_PAD_FAILED_DIR = tmp_path / "failed"
    module.LANDING_PAD_INPUT_REPLAYED_DIR = tmp_path / "input_replayed"
    module.LANDING_PAD_INPUT_FAILED_DIR = tmp_path / "input_failed"
    return module


def _today_partition(base: Path) -> Path:
    now = datetime.now(timezone.utc)
    return base / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"


def test_persist_alert_writes_into_todays_date_partition(monitoring_app) -> None:
    module = monitoring_app
    mapped = {"name": "High error rate", "labels": {"alert_fingerprint": "abc123"}}
    out_path = module._persist_alert_to_landing_pad(mapped, {"raw": True}, status="processed")

    assert out_path is not None
    written = Path(out_path)
    expected_dir = _today_partition(module.LANDING_PAD_PROCESSED_DIR)
    assert written.parent == expected_dir
    assert written.is_file()
    assert json.loads(written.read_text(encoding="utf-8"))["alert"]["name"] == "High error rate"


def test_persist_alert_bounds_long_archive_filename(monitoring_app) -> None:
    module = monitoring_app
    full_name = "Jira qualification outcome " + ("requires-investigation-" * 30)

    out_path = module._persist_alert_to_landing_pad(
        {"name": full_name, "source": "jira", "labels": {}},
        {},
        status="processed",
    )

    assert out_path is not None
    written = Path(out_path)
    assert len(written.name.encode("utf-8")) <= 255
    assert json.loads(written.read_text(encoding="utf-8"))["alert"]["name"] == full_name


def test_archive_input_file_moves_into_todays_date_partition(monitoring_app, tmp_path: Path) -> None:
    module = monitoring_app
    source = tmp_path / "incoming.json"
    source.write_text("{}", encoding="utf-8")

    archived = module._archive_landing_pad_input_file(source, module.LANDING_PAD_INPUT_REPLAYED_DIR)

    expected_dir = _today_partition(module.LANDING_PAD_INPUT_REPLAYED_DIR)
    assert Path(archived).parent == expected_dir
    assert Path(archived).is_file()
    assert not source.exists()


def test_archive_input_file_is_idempotent_when_source_disappears(
    monitoring_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = monitoring_app
    source = tmp_path / "incoming.json"
    source.write_text("{}", encoding="utf-8")

    def raise_missing(_self: Path, _target: Path) -> None:
        raise FileNotFoundError("source already claimed")

    monkeypatch.setattr(type(source), "replace", raise_missing, raising=True)

    archived = module._archive_landing_pad_input_file(source, module.LANDING_PAD_INPUT_REPLAYED_DIR)

    expected_dir = _today_partition(module.LANDING_PAD_INPUT_REPLAYED_DIR)
    assert Path(archived).parent == expected_dir
    assert Path(archived).name == source.name
    assert source.exists()


def test_dedup_finds_match_within_lookback_window(monitoring_app) -> None:
    module = monitoring_app
    mapped = {"name": "Consumer lag", "labels": {"alert_fingerprint": "dup-1"}}
    module._persist_alert_to_landing_pad(mapped, {}, status="processed")

    assert module._processed_landing_pad_match_exists(mapped) is True

    other = {"name": "Consumer lag", "labels": {"alert_fingerprint": "not-seen-before"}}
    assert module._processed_landing_pad_match_exists(other) is False


def test_dedup_ignores_partitions_outside_lookback_window(monitoring_app) -> None:
    module = monitoring_app
    mapped = {"name": "Old alert", "labels": {"alert_fingerprint": "stale-1"}}

    # Simulate a match that only exists far outside the configured lookback window.
    old_moment = datetime.now(timezone.utc) - timedelta(days=module.LANDING_PAD_DEDUP_LOOKBACK_DAYS + 5)
    old_dir = module._date_partition_dir(module.LANDING_PAD_PROCESSED_DIR, old_moment)
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / "old_old-alert_stale-1.json").write_text("{}", encoding="utf-8")

    assert module._processed_landing_pad_match_exists(mapped) is False


def test_landing_pad_recent_does_not_scan_date_partitions(monitoring_app, monkeypatch: pytest.MonkeyPatch) -> None:
    module = monitoring_app
    monkeypatch.setattr(module, "_collect_partitioned_json_files", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("archive scan attempted")))
    for index in range(3):
        module._persist_alert_to_landing_pad(
            {"name": f"alert-{index}", "labels": {"alert_fingerprint": f"fp-{index}"}},
            {},
            status="processed",
        )

    import asyncio

    response = asyncio.run(module.get_landing_pad_recent(limit=10))
    assert response["count"] == 3
    assert response["partition_scheme"] == "YYYY/MM/DD"
    assert response["source"] == "live-memory-buffer"


def test_landing_pad_recent_returns_live_memory_without_archive_scan(monitoring_app) -> None:
    module = monitoring_app
    module._persist_alert_to_landing_pad(
        {"name": "archived-log", "source": "logs", "labels": {"alert_fingerprint": "log-1"}},
        {},
        status="processed",
    )
    module.RECENT_INGESTION_EVENTS.clear()
    module._record_live_stream_event(origin_system="email", name="live-email", source="email")

    import asyncio

    response = asyncio.run(module.get_landing_pad_recent(limit=10, include_archive=False))

    assert response["source"] == "live-memory-buffer"
    assert {row["name"] for row in response["rows"]} == {"live-email"}


def test_landing_pad_recent_requires_mysql_for_archive_history(monitoring_app) -> None:
    module = monitoring_app
    module._persist_alert_to_landing_pad(
        {
            "name": "resolved-email",
            "source": "email",
            "labels": {
                "alert_fingerprint": "email-resolved-1",
                "origin_system": "email",
                "ingestion_channel": "email",
                "alert_status": "resolved",
            },
        },
        {},
        status="processed",
    )
    for index in range(6):
        module._persist_alert_to_landing_pad(
            {
                "name": f"prometheus-{index}",
                "source": "prometheus",
                "labels": {"alert_fingerprint": f"prom-{index}", "alert_status": "firing"},
            },
            {},
            status="processed",
        )
    module.RECENT_INGESTION_EVENTS.clear()

    import asyncio

    with pytest.raises(module.HTTPException) as exc_info:
        asyncio.run(module.get_landing_pad_recent(limit=3, include_archive=True))
    assert exc_info.value.status_code == 503


def test_landing_pad_input_lists_partitioned_replayed_and_failed(monitoring_app, tmp_path: Path) -> None:
    module = monitoring_app
    replayed_source = tmp_path / "replayed.json"
    replayed_source.write_text(json.dumps({"alert": {"name": "replayed-alert"}}), encoding="utf-8")
    module._archive_landing_pad_input_file(replayed_source, module.LANDING_PAD_INPUT_REPLAYED_DIR)

    failed_source = tmp_path / "failed.json"
    failed_source.write_text(json.dumps({"alert": {"name": "failed-alert"}}), encoding="utf-8")
    module._archive_landing_pad_input_file(failed_source, module.LANDING_PAD_INPUT_FAILED_DIR)

    import asyncio

    response = asyncio.run(module.get_landing_pad_input(limit=10))
    assert response["partition_scheme"] == "YYYY/MM/DD"
    assert len(response["replayed_rows"]) == 1
    assert response["replayed_rows"][0]["name"] == "replayed-alert"
    assert len(response["failed_rows"]) == 1
    assert response["failed_rows"][0]["name"] == "failed-alert"
