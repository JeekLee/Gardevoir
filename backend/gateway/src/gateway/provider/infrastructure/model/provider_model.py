from uuid import UUID

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared_kernel.database import Base, TimestampMixin


class ProviderModel(Base, TimestampMixin):
    __tablename__ = "providers"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    #: 공급자 비밀. 로컬 호스팅이면 빈 문자열.
    api_key: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    #: 이 프로바이더가 서빙하는 모델명. GIN 인덱스로 containment 라우팅한다.
    models: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
