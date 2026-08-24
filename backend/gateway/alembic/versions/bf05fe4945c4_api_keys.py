"""api_keys 재정의

손으로 작성했다. ApiKey 도메인이 순수 크레덴셜로 재정의되면서(#20 이후) 옛 테이블
(id VARCHAR ULID · key_hash · upstream_* · allowed_guardrails · scopes · disabled)이 어떤
모델과도 맞지 않게 됐다. 컬럼을 하나씩 ALTER 하는 대신 drop 후 새 스키마로 다시 만든다 —
데이터가 없고(개발), 그 편이 마이그레이션이 정직하다("모델이 통째로 바뀌었다").

Revision ID: bf05fe4945c4
Revises: a1b2c3d4e5f6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "bf05fe4945c4"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("api_keys")
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
    )
    op.create_index(op.f("ix_api_keys_key"), "api_keys", ["key"], unique=True)
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    옛 스키마로 정확히 되돌리지 않는다 — 그 형태는 죽은 모델이다. 새 테이블만 드롭한다.
    """
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key"), table_name="api_keys")
    op.drop_table("api_keys")
