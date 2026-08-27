"""ClickHouse audit table contract tests."""

from pathlib import Path

from gateway.audit.infrastructure.model.audit_event import AUDIT_EVENTS_TABLE
from shared_kernel.clickhouse import CLICKHOUSE_METADATA
from shared_kernel.database import Base

CLICKHOUSE_SCHEMA = Path(__file__).resolve().parents[1] / "clickhouse/001_audit_events.sql"


def _schema_columns() -> list[tuple[str, str]]:
    definition = CLICKHOUSE_SCHEMA.read_text().split("(", maxsplit=1)[1]
    definition = definition.split("\n)\nENGINE", maxsplit=1)[0]
    return [
        tuple(line.strip().removesuffix(",").split(maxsplit=1))
        for line in definition.splitlines()
        if line.strip()
    ]


def test_table_columns_match_the_schema_source() -> None:
    assert [(column.name, str(column.type)) for column in AUDIT_EVENTS_TABLE.columns] == (
        _schema_columns()
    )


def test_clickhouse_table_is_separate_from_postgres_metadata() -> None:
    assert AUDIT_EVENTS_TABLE.metadata is CLICKHOUSE_METADATA
    assert AUDIT_EVENTS_TABLE.metadata is not Base.metadata
    assert AUDIT_EVENTS_TABLE.name not in Base.metadata.tables
