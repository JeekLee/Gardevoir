"""ClickHouse schema application.

Alembic is Postgres-only. ClickHouse gets numbered .sql files applied in name
order — the audit schema is one append-only table and needs no migration tool.
Statements must be idempotent.
"""

from pathlib import Path


def apply_clickhouse_schema(client, sql_dir: Path) -> list[str]:
    applied: list[str] = []
    for path in sorted(sql_dir.glob("*.sql")):
        for statement in path.read_text().split(";"):
            if statement.strip():
                client.command(statement)
        applied.append(path.name)
    return applied
