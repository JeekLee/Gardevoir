"""Error response body.

Task 4에서 CamelModel 상속으로 교체된다. 지금은 api 패키지가 없으므로
pydantic을 직접 쓴다.
"""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ErrorResponse(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    code: str
    message: str
    details: dict | None = None
    request_id: str | None = None
