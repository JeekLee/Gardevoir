"""ApiKey ORM model."""

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared_kernel.database import Base, TimestampMixin


class ApiKeyModel(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    #: sha256 hex of the raw key. The raw key is never stored.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    upstream_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    upstream_api_key: Mapped[str] = mapped_column(String(512), nullable=False)

    #: Guardrails this key may select via X-Gardevoir-Guardrail. A request can
    #: never escape this set — that is why guardrail choice is bound to the
    #: credential rather than to a header (§7.2).
    allowed_guardrails: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    default_guardrail: Mapped[str | None] = mapped_column(String(255), nullable=True)

    disabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    #: 인가는 크레덴셜에서 온다 (§7.2, §12). 기본값을 안전한 쪽으로 둔다 —
    #: 스코프가 명시되지 않은 키는 admin 에 접근할 수 없다.
    scopes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=lambda: ["proxy"], server_default='["proxy"]'
    )
