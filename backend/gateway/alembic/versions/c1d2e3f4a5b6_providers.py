"""providers

업스트림 프로바이더. 요청 body 의 model 로 라우팅하므로 models(JSONB)에 GIN 인덱스를 걸어
containment 조회(models @> ["gpt-4"])가 인덱스를 타게 한다.

Revision ID: c1d2e3f4a5b6
Revises: bf05fe4945c4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "bf05fe4945c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("api_key", sa.String(length=512), nullable=False),
        sa.Column("models", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_providers")),
    )
    op.create_index(op.f("ix_providers_name"), "providers", ["name"], unique=True)
    op.create_index(
        "ix_providers_models", "providers", ["models"], unique=False, postgresql_using="gin"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_providers_models", table_name="providers", postgresql_using="gin")
    op.drop_index(op.f("ix_providers_name"), table_name="providers")
    op.drop_table("providers")
