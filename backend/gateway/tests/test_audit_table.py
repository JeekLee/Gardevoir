"""ClickHouse audit table contract tests."""

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from gateway.audit.infrastructure.model.audit_event import (
    AUDIT_EVENTS_TABLE,
    AuditEventModel,
)
from shared_kernel.clickhouse import CLICKHOUSE_METADATA
from shared_kernel.database import Base

CLICKHOUSE_BASELINE = (
    Path(__file__).resolve().parents[1]
    / "alembic/clickhouse/versions/260827_create_audit_events.py"
)


def _baseline_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("clickhouse_audit_baseline", CLICKHOUSE_BASELINE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _baseline_ddl() -> str:
    migration = _baseline_module()
    with patch.object(migration.op, "execute") as execute:
        migration.upgrade()
    execute.assert_called_once()
    return str(execute.call_args.args[0])


def _schema_columns() -> list[tuple[str, str]]:
    definition = _baseline_ddl().split("(", maxsplit=1)[1]
    definition = definition.split("\n)\nENGINE", maxsplit=1)[0]
    return [
        tuple(line.strip().removesuffix(",").split(maxsplit=1))
        for line in definition.splitlines()
        if line.strip()
    ]


def _compact(value: str) -> str:
    return value.replace("`", "").replace(" ", "")


def _schema_table_options() -> tuple[str, str, str]:
    definition = _baseline_ddl()
    return (
        definition.split("ENGINE = ", maxsplit=1)[1].splitlines()[0],
        definition.split("PARTITION BY ", maxsplit=1)[1].splitlines()[0],
        definition.split("ORDER BY ", maxsplit=1)[1].splitlines()[0],
    )


def _model_table_options() -> tuple[str, str, str]:
    definition = AuditEventModel.__table__.engine.compile()
    engine, clauses = definition.removeprefix("Engine ").split(maxsplit=1)
    order_by, partition_by = clauses.split("PARTITION BY ", maxsplit=1)
    return engine, partition_by, order_by.removeprefix("ORDER BY ").strip()


def test_table_columns_match_the_schema_source() -> None:
    assert [(column.name, str(column.type)) for column in AuditEventModel.__table__.columns] == (
        _schema_columns()
    )


def test_table_engine_matches_the_schema_source() -> None:
    assert tuple(map(_compact, _model_table_options())) == tuple(
        map(_compact, _schema_table_options())
    )


def test_clickhouse_table_is_separate_from_postgres_metadata() -> None:
    assert AUDIT_EVENTS_TABLE is AuditEventModel.__table__
    assert AUDIT_EVENTS_TABLE.metadata is CLICKHOUSE_METADATA
    assert AUDIT_EVENTS_TABLE.metadata is not Base.metadata
    assert AUDIT_EVENTS_TABLE.name not in Base.metadata.tables
