"""Add privacy-aware audit content columns.

Revision ID: a4b5c6d7e8f9
Revises: 37cad59a5234
Create Date: 2026-08-27

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "37cad59a5234"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS content_fingerprint String")
    op.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS excerpt String")
    op.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS input_body String")
    op.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS output_body String")
    op.execute("ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS tool_calls_body String")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE audit_events DROP COLUMN IF EXISTS tool_calls_body")
    op.execute("ALTER TABLE audit_events DROP COLUMN IF EXISTS output_body")
    op.execute("ALTER TABLE audit_events DROP COLUMN IF EXISTS input_body")
    op.execute("ALTER TABLE audit_events DROP COLUMN IF EXISTS excerpt")
    op.execute("ALTER TABLE audit_events DROP COLUMN IF EXISTS content_fingerprint")
