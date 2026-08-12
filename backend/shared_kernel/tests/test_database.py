from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from shared_kernel.database import Base, TimestampMixin


class Widget(Base, TimestampMixin):
    __tablename__ = "widgets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)


def test_primary_key_gets_convention_name():
    """Alembic autogenerate가 안정적인 이름을 내야 마이그레이션 diff가 조용해진다."""
    names = {c.name for c in Widget.__table__.constraints if c.name}
    assert "pk_widgets" in names


def test_unique_constraint_gets_convention_name():
    """unique=True는 UniqueConstraint로 표현되고 uq_ 규칙을 받는다.

    Index로 바뀌면 Alembic이 내는 diff가 달라지므로 여기서 실패해야 한다.
    """
    names = {c.name for c in Widget.__table__.constraints if c.name}
    assert "uq_widgets_name" in names
    assert Widget.__table__.indexes == set()


def test_timestamp_mixin_adds_both_columns():
    cols = Widget.__table__.c
    assert "created_at" in cols
    assert "updated_at" in cols
    assert cols["created_at"].type.timezone is True
    assert cols["updated_at"].type.timezone is True
    assert cols["created_at"].server_default is not None
    assert cols["updated_at"].server_default is not None


def test_timestamp_columns_are_not_nullable():
    cols = Widget.__table__.c
    assert cols["created_at"].nullable is False
    assert cols["updated_at"].nullable is False
