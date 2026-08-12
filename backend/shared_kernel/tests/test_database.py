import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import CreateIndex

from shared_kernel.database import Base, TimestampMixin


class Widget(Base, TimestampMixin):
    __tablename__ = "widgets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)


class Gadget(Base):
    """Exercises the ix / fk / ck rules, which Widget does not reach."""

    __tablename__ = "gadgets"
    __table_args__ = (CheckConstraint("length(label) > 0", name="label_not_empty"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    widget_id: Mapped[str] = mapped_column(String(32), ForeignKey("widgets.id"))
    label: Mapped[str] = mapped_column(String(64), index=True)


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


def test_updated_at_is_written_on_every_update():
    """onupdate가 실제로 UPDATE 문의 SET 절에 들어가는지.

    속성만 단정하면 onupdate를 지워도 통과한다.
    """
    stmt = sa.update(Widget.__table__).values(name="renamed")
    compiled = str(stmt.compile(dialect=postgresql.dialect()))
    assert "updated_at" in compiled
    assert "created_at" not in compiled


def test_index_rule_produces_a_compilable_name():
    """ix 규칙이 없으면 인덱스 이름이 None이 되고 CreateIndex 컴파일이 AssertionError로 죽는다.

    diff 소음이 아니라 크래시이므로 세 규칙 중 가장 먼저 깨진다.
    """
    index = next(i for i in Gadget.__table__.indexes)
    assert index.name == "ix_gadgets_label"
    sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "ix_gadgets_label" in sql


def test_foreign_key_rule_names_the_constraint():
    names = {c.name for c in Gadget.__table__.constraints if c.name}
    assert "fk_gadgets_widget_id_widgets" in names


def test_check_constraint_rule_prefixes_the_given_name():
    names = {c.name for c in Gadget.__table__.constraints if c.name}
    assert "ck_gadgets_label_not_empty" in names
