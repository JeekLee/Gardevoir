"""Decode tool calls and their string argument paths."""

from dataclasses import dataclass
from typing import Any

import orjson

from gateway.guardrail.domain.models.guardrail import TOOL_SELECTOR_INCLUDE

_JOIN = " "
_UNKNOWN_TOOL_NAME = "(unknown)"


@dataclass(frozen=True, slots=True)
class ParsedArguments:
    """String argument paths plus whether JSON decoding failed."""

    values: tuple[tuple[str, str], ...] = ()
    parse_failed: bool = False


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
    return list(parse_argument_strings(tool_call).values)


def parse_argument_strings(tool_call: Any) -> ParsedArguments:
    """Decode string arguments without hiding a malformed JSON string."""
    if not isinstance(tool_call, dict):
        return ParsedArguments()
    function = tool_call.get("function")
    if not isinstance(function, dict):
        return ParsedArguments()

    raw = function.get("arguments")
    if isinstance(raw, dict):
        parsed: Any = raw
    elif isinstance(raw, str):
        try:
            parsed = orjson.loads(raw)
        except orjson.JSONDecodeError:
            return ParsedArguments(parse_failed=True)
    else:
        return ParsedArguments()

    found: list[tuple[str, str]] = []
    _walk(parsed, "", found)
    return ParsedArguments(values=tuple(found))


def tool_selected(name: str, selector: str, tools: frozenset[str]) -> bool:
    """Apply a tool selector with the fail-safe missing-name rule."""
    if not name:
        return True
    if selector == TOOL_SELECTOR_INCLUDE:
        return name in tools
    return name not in tools


def tool_extract_text(name: str, arguments: ParsedArguments, field: str) -> str:
    """Extract one tool-call field as policy text."""
    if field == "name":
        # 이름을 못 읽은 호출도 선택된 툴이다. 빈 문자열을 넣으면 migration의
        # regex(".")가 거짓이 돼 기존 side_effect 정책이 fail-open 한다.
        return name or _UNKNOWN_TOOL_NAME
    if field == "arguments":
        return _JOIN.join(value for _, value in arguments.values)
    return _JOIN.join(value for path, value in arguments.values if _path_matches(field, path))


def tool_extract_paths(arguments: ParsedArguments, field: str) -> tuple[str, ...]:
    """Return only argument path names suitable for audit evidence."""
    if field == "name":
        return ()
    if field == "arguments":
        return tuple(path for path, _ in arguments.values)
    return tuple(path for path, _ in arguments.values if _path_matches(field, path))


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


def _path_matches(pattern: str, path: str) -> bool:
    """Match an argument path, where ``[*]`` consumes one array index."""
    pattern_index = 0
    path_index = 0
    while pattern_index < len(pattern):
        if pattern.startswith("[*]", pattern_index):
            if path_index >= len(path) or path[path_index] != "[":
                return False
            path_index += 1
            digits_start = path_index
            while path_index < len(path) and path[path_index].isdigit():
                path_index += 1
            if path_index == digits_start or path_index >= len(path) or path[path_index] != "]":
                return False
            path_index += 1
            pattern_index += 3
            continue
        if path_index >= len(path) or pattern[pattern_index] != path[path_index]:
            return False
        pattern_index += 1
        path_index += 1
    return path_index == len(path)


__all__ = [
    "ParsedArguments",
    "argument_strings",
    "extract_tool_calls",
    "foreign_arguments",
    "parse_argument_strings",
    "tool_extract_paths",
    "tool_extract_text",
    "tool_name",
    "tool_selected",
]
