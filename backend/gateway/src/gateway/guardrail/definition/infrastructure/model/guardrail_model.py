"""Guardrail ORM model.

The graph lives in one jsonb column rather than in node/edge tables. §6: the
graph is only ever read whole (to compile it) or written whole (to save a draft),
so splitting it across tables would buy joins we never want. jsonb keeps it
queryable — "which guardrails use this pattern" is a jsonb_array_elements away —
which a bytea blob would not.
"""

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared_kernel.database import Base, TimestampMixin


class GuardrailModel(Base, TimestampMixin):
    __tablename__ = "guardrails"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    #: "draft" for the mutable row, else the decimal version number. Dify's
    #: pattern (§6): one editable draft per name plus immutable published rows.
    version: Mapped[str] = mapped_column(String(64), nullable=False)

    #: NULL on the draft. Postgres treats NULLs as distinct in a unique index,
    #: so one draft per name is enforced by (name, version) alone.
    version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    #: {"nodes": [...], "edges": [...]}
    graph: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_guardrails_name_version"),
        UniqueConstraint("name", "version_number", name="uq_guardrails_name_version_number"),
    )
