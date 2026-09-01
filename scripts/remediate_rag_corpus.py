from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class MigrationRecord:
    path: str
    status: str
    before_sha256: str
    after_sha256: str
    changed: bool
    reason: str


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _selected(path: Path, root: Path, includes: list[str], excludes: list[str]) -> bool:
    relative = path.relative_to(root).as_posix()
    return any(fnmatch.fnmatch(relative, pattern) for pattern in includes) and not any(
        fnmatch.fnmatch(relative, pattern) for pattern in excludes
    )


def _normalize(raw: bytes) -> tuple[bytes, str]:
    if b"\x00" in raw:
        raise ValueError("NUL byte makes text normalization ambiguous")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("document is not valid UTF-8") from exc
    normalized = text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    return normalized.encode("utf-8"), "normalized deterministic CR/CRLF line endings"


def migrate(
    root: Path,
    *,
    apply: bool,
    includes: list[str],
    excludes: list[str],
) -> list[MigrationRecord]:
    records: list[MigrationRecord] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if not _selected(path, root, includes, excludes):
            continue
        raw = path.read_bytes()
        before = _sha256(raw)
        try:
            normalized, reason = _normalize(raw)
        except ValueError as exc:
            records.append(
                MigrationRecord(path.relative_to(root).as_posix(), "rejected", before, before, False, str(exc))
            )
            continue
        after = _sha256(normalized)
        changed = raw != normalized
        if changed and apply:
            path.write_bytes(normalized)
        records.append(
            MigrationRecord(
                path.relative_to(root).as_posix(),
                "applied" if changed and apply else "change-required" if changed else "unchanged",
                before,
                after,
                changed,
                reason if changed else "already normalized",
            )
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministically normalize RAG corpus text files")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--rag-root", default="backend/rag")
    parser.add_argument("--report", required=True)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args()

    root = Path(args.rag_root).resolve()
    if not root.is_dir():
        raise SystemExit(f"RAG root not found: {root}")
    includes = args.include or ["*.md", "**/*.md", "*.txt", "**/*.txt"]
    records = migrate(root, apply=args.apply, includes=includes, excludes=args.exclude)
    report = {
        "schema_version": "kaims.rag-text-migration.v1",
        "mode": "apply" if args.apply else "dry-run",
        "root": str(args.rag_root).replace("\\", "/"),
        "records": [asdict(record) for record in records],
        "summary": {
            "scanned": len(records),
            "changed": sum(record.changed for record in records),
            "rejected": sum(record.status == "rejected" for record in records),
        },
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], sort_keys=True))
    for record in records:
        if record.status == "rejected":
            print(f"[REJECTED] {record.path}: {record.reason}")
    return 1 if report["summary"]["rejected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
