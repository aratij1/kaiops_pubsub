from __future__ import annotations

import argparse
from typing import Iterable

from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy existing relational data from source DB to target DB.")
    parser.add_argument("--source-url", required=True, help="Source SQLAlchemy URL")
    parser.add_argument("--target-url", required=True, help="Target SQLAlchemy URL")
    parser.add_argument("--tables", default="", help="Comma-separated tables. Empty means all discovered tables")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--truncate-target", action="store_true", help="Truncate target tables before insert")
    parser.add_argument("--dry-run", action="store_true", help="Discover and count only")
    return parser.parse_args()


def resolve_tables(source: Engine, explicit_tables: str) -> list[str]:
    if explicit_tables.strip():
        return [name.strip() for name in explicit_tables.split(",") if name.strip()]

    with source.connect() as conn:
        rows = conn.execute(text("SHOW TABLES")).fetchall()
    return [str(row[0]) for row in rows]


def stream_rows(source: Engine, table: Table, chunk_size: int) -> Iterable[list[dict]]:
    with source.connect() as conn:
        cursor = conn.execute(select(table))
        while True:
            chunk = cursor.fetchmany(chunk_size)
            if not chunk:
                break
            yield [dict(row._mapping) for row in chunk]


def copy_table(source: Engine, target: Engine, table_name: str, chunk_size: int, truncate_target: bool, dry_run: bool) -> tuple[int, int]:
    source_meta = MetaData()
    target_meta = MetaData()

    source_table = Table(table_name, source_meta, autoload_with=source)
    target_table = Table(table_name, target_meta, autoload_with=target)

    read_count = 0
    write_count = 0

    if dry_run:
        with source.connect() as conn:
            read_count = int(conn.execute(select(text("count(*)")).select_from(source_table)).scalar_one())
        return read_count, 0

    with target.begin() as tx:
        if truncate_target:
            tx.execute(text(f"TRUNCATE TABLE `{table_name}`"))

        for batch in stream_rows(source, source_table, chunk_size):
            if not batch:
                continue
            read_count += len(batch)
            tx.execute(target_table.insert(), batch)
            write_count += len(batch)

    return read_count, write_count


def main() -> int:
    args = parse_args()
    source = create_engine(args.source_url)
    target = create_engine(args.target_url)

    try:
        tables = resolve_tables(source, args.tables)
        if not tables:
            print("No tables found to migrate")
            return 0

        total_read = 0
        total_write = 0
        for table_name in tables:
            read_count, write_count = copy_table(
                source,
                target,
                table_name,
                args.chunk_size,
                args.truncate_target,
                args.dry_run,
            )
            total_read += read_count
            total_write += write_count
            print(f"table={table_name} read={read_count} written={write_count}")

        print(f"migration_complete tables={len(tables)} rows_read={total_read} rows_written={total_write}")
        return 0
    except SQLAlchemyError as exc:
        print(f"migration_failed error={exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
