"""Apply pending backend/database/migrations/*.sql files against MySQL.

README.md has always said "Apply migration manually for existing DBs before
starting services" with no tooling to track which files were already run —
operators either re-ran a whole migration by hand (safe here only because
every migration is written with IF NOT EXISTS / information_schema-guarded
conditional DDL) or had to remember state themselves. This script tracks
applied filenames in a `schema_migrations` table and only runs what's new,
in filename order (files are date-prefixed, so lexicographic order is
chronological order). It is intentionally forward-only: no migration in this
repo ships a down-migration, so there is nothing to roll back to here by
design — see the rollback runbook referenced from
docs/END_USER_RELEASE_READINESS_2026-08-03.md for the manual rollback story.

Usage:

    python scripts/apply-migrations.py
    python scripts/apply-migrations.py --dry-run
    python scripts/apply-migrations.py --database-url "mysql+pymysql://user:pass@host:3306/kaiops"
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

import pymysql
from pymysql.constants import CLIENT

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "backend" / "database" / "migrations"

_CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename VARCHAR(255) PRIMARY KEY,
    applied_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def resolve_connection_kwargs(database_url: str | None) -> dict:
    """Parse a mysql(+driver)://user:pass@host:port/db URL, or fall back to
    the same DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_DATABASE env vars every
    service already reads (see backend/src/common/common/config.py)."""
    url = database_url or os.environ.get("DATABASE_URL")
    if url and not url.startswith(("mysql", "mysql+")):
        raise ValueError(f"only MySQL is supported by this migration runner, got: {url.split('://')[0]}")
    if url:
        parsed = urlparse(url.replace("mysql+aiomysql", "mysql").replace("mysql+pymysql", "mysql"))
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or "kaiops"),
            "password": unquote(parsed.password or "kaiops"),
            "database": (parsed.path or "/kaiops").lstrip("/") or "kaiops",
        }
    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "kaiops"),
        "password": os.environ.get("DB_PASSWORD", "kaiops"),
        "database": os.environ.get("DB_DATABASE", "kaiops"),
    }


def list_migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda path: path.name)


def already_applied(cursor) -> set[str]:  # noqa: ANN001
    cursor.execute("SELECT filename FROM schema_migrations")
    return {row[0] for row in cursor.fetchall()}


def apply_migration(cursor, path: Path) -> None:  # noqa: ANN001
    sql = path.read_text(encoding="utf-8")
    if sql.strip():
        cursor.execute(sql)
        while cursor.nextset():
            pass
    cursor.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None, help="mysql(+driver)://user:pass@host:port/db")
    parser.add_argument("--dry-run", action="store_true", help="List pending migrations without applying them.")
    args = parser.parse_args()

    connection_kwargs = resolve_connection_kwargs(args.database_url)
    files = list_migration_files()
    if not files:
        print(f"No migration files found under {MIGRATIONS_DIR}")
        return

    connection = pymysql.connect(
        host=connection_kwargs["host"],
        port=connection_kwargs["port"],
        user=connection_kwargs["user"],
        password=connection_kwargs["password"],
        database=connection_kwargs["database"],
        client_flag=CLIENT.MULTI_STATEMENTS,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(_CREATE_TRACKING_TABLE)
            applied = already_applied(cursor)

            pending = [path for path in files if path.name not in applied]
            if not pending:
                print(f"Up to date: {len(applied)} migration(s) already applied, nothing pending.")
                return

            print(f"{len(pending)} pending migration(s) out of {len(files)} total:")
            for path in pending:
                print(f"  {path.name}")

            if args.dry_run:
                print("Dry run: no migrations applied.")
                return

            for path in pending:
                print(f"Applying {path.name} ...")
                apply_migration(cursor, path)
                print(f"Applied {path.name}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
