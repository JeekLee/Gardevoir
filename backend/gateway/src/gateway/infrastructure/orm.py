"""ORM 등록 지점.

**모든 모델을 여기서 임포트해야 한다.** ``Base.metadata`` 는 임포트된 모델만 알고,
Alembic autogenerate 는 그 metadata 를 읽는다 — 여기 빠진 모델은 마이그레이션에서
조용히 사라지고, 배포한 뒤에야 테이블이 없다는 것을 알게 된다.

모델 자체는 각 컨텍스트가 소유한다. 이 파일은 "전부 임포트됐다"만 보장한다.
"""

from gateway.guardrail.definition.infrastructure.guardrail_model import GuardrailModel
from gateway.identity.infrastructure.api_key_model import ApiKeyModel

__all__ = ["ApiKeyModel", "GuardrailModel"]
