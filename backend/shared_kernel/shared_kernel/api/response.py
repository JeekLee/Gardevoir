"""JSON response class.

orjson, not json — the project uses one serialiser (AGENTS.md). fastapi's own
ORJSONResponse is deprecated as of 0.141, so we own the four lines instead of
importing a warning.
"""

from typing import Any

import orjson
from starlette.responses import Response


class JsonResponse(Response):
    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        # default=str 은 마지막 안전망이다. 응답 모델이 이미 json 모드로 직렬화된
        # 값을 주므로 보통은 쓰이지 않는다.
        return orjson.dumps(content, default=str)
