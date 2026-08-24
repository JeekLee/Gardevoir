from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from shared_kernel.database import Base, TimestampMixin


class ApiKeyModel(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    #: 해시가 아니라 원본이다 (SKILL.md). 프록시 인증이 이 값으로 조회한다.
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(Uuid, index=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
