#!/usr/bin/env python3
"""Seed the KaiOps landing pad with the historical Jira ticket CSV.

The monitoring-adapter landing-pad file watcher polls
``backend/ingested_alerts/input`` and ingests ``.json``, ``.csv`` and ``.eml``
files. A Jira CSV is expanded into one alert per row by
``monitoring_adapter.landing_pad_sources.jira_row_to_alert`` and each ingested
file is archived to ``backend/ingested_alerts/input_replayed``.

This script copies the 1,000-ticket CSV (or a bounded subset) into the input
directory under a unique, timestamped name so the watcher processes it exactly
once.

Examples
--------
    python scripts/seed_landing_pad.py                 # drop the full CSV
    python scripts/seed_landing_pad.py --limit 50      # only the first 50 rows
"""

from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "fault-lab" / "data" / "kaiops_jira_1000_tickets.csv"
DEFAULT_INPUT_DIR = REPO_ROOT / "backend" / "ingested_alerts" / "input"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def seed(source: Path, input_dir: Path, limit: int | None) -> Path:
    if not source.is_file():
        raise SystemExit(f"source CSV not found: {source}")
    input_dir.mkdir(parents=True, exist_ok=True)
    target = input_dir / f"jira-tickets-{_timestamp()}.csv"

    if limit is None or limit <= 0:
        shutil.copyfile(source, target)
        with source.open(encoding="utf-8-sig", newline="") as stream:
            row_count = sum(1 for _ in csv.reader(stream)) - 1
    else:
        with source.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream)
            rows = [next(reader)]  # header
            for index, row in enumerate(reader):
                if index >= limit:
                    break
                rows.append(row)
        with target.open("w", encoding="utf-8", newline="") as out:
            csv.writer(out).writerows(rows)
        row_count = len(rows) - 1

    print(f"Seeded {row_count} Jira ticket(s) -> {target}")
    print("The monitoring-adapter watcher will ingest and archive it to input_replayed/.")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Jira ticket CSV to seed")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="landing-pad input directory")
    parser.add_argument("--limit", type=int, default=None, help="only seed the first N rows (default: all)")
    args = parser.parse_args()
    seed(args.source, args.input_dir, args.limit)


if __name__ == "__main__":
    main()
