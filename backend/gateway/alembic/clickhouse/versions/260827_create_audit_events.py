"""Create the audit events table.

Revision ID: 37cad59a5234
Revises:
Create Date: 2026-08-27

"""

from collections.abc import Sequence

from alembic import op

revision: str = "37cad59a5234"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CREATE_AUDIT_EVENTS_TABLE = """\
CREATE TABLE IF NOT EXISTS audit_events (
    id                String,
    created_at        DateTime64(3),
    request_id        String,
    api_key_id        String,
    app_name          LowCardinality(String),
    guardrail         LowCardinality(String),
    guardrail_version UInt32,
    mode              LowCardinality(String),
    action            LowCardinality(String),
    checkpoint        LowCardinality(String),
    checks_fired      Array(LowCardinality(String)),
    verdicts          String,
    tier_reached      LowCardinality(String),
    tainted           UInt8,
    latency_ms        Float32,
    model             LowCardinality(String),
    prompt_tokens     UInt32,
    completion_tokens UInt32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (app_name, created_at, id)"""


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(CREATE_AUDIT_EVENTS_TABLE)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE IF EXISTS audit_events")
