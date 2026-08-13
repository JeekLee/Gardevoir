"""What to inspect at each checkpoint (§3).

**모양이 이상하면 빈 결과를 낸다.** 업스트림이 거부할 페이로드를 우리가 먼저
터뜨리면 가드레일이 가용성 문제가 된다 — 프록시는 통과시키고 업스트림이 400 을
내게 한다.
"""

from typing import Any

#: ① 은 사용자 입력이다. assistant 는 ③, tool 결과는 ② 가 본다.
INPUT_ROLES = frozenset({"user"})

#: ② 의 대상. ``function`` 은 구 프로토콜의 같은 자리다 — 빠뜨리면 옛 클라이언트에서
#: 오염 추적이 조용히 꺼진다.
TOOL_RESULT_ROLES = frozenset({"tool", "function"})

#: 출처 판정에 쓰는 "사용자가 말한 것". 시스템 프롬프트는 앱이 통제하므로 신뢰한다 (§8 3단계).
TRUSTED_ROLES = frozenset({"user", "system", "developer"})

_JOIN = "\n"


def extract_input_text(payload: Any) -> str:
    """① 검사 대상.

    ``messages`` 는 매 턴 전체가 다시 온다 (§7.4). 마지막 user 메시지만 보면 여러
    턴에 나눠 심은 것을 놓치므로 전부 이어붙인다.
    """
    return _JOIN.join(_texts_for_roles(payload, INPUT_ROLES))


def extract_output_texts(body: Any) -> list[tuple[int, str]]:
    """③ 검사 대상. ``(위치, 텍스트)`` — 마스킹이 그 자리에 되써야 한다.

    ``index`` 필드가 아니라 리스트 위치를 쓴다. 업스트림이 중복된 index 를 주면
    엉뚱한 선택지를 고치게 된다.
    """
    if not isinstance(body, dict):
        return []
    choices = body.get("choices")
    if not isinstance(choices, list):
        return []

    found: list[tuple[int, str]] = []
    for position, choice in enumerate(choices):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        texts = _content_texts(message.get("content"))
        if texts:
            found.append((position, _JOIN.join(texts)))
    return found


def extract_tool_result_text(payload: Any) -> str:
    """② 검사 대상 — 툴 결과 전체.

    ① 과 같은 이유로 전부 이어붙인다: 마지막 결과만 보면 여러 턴에 걸쳐 심은 지시를
    놓친다 (§7.4).
    """
    return _JOIN.join(_texts_for_roles(payload, TOOL_RESULT_ROLES))


def extract_trusted_text(payload: Any) -> str:
    """출처 판정의 신뢰 원천 — 사용자 메시지와 시스템 프롬프트 (§8 3단계).

    시스템 프롬프트를 신뢰하는 이유: 앱이 통제하는 값이다. 공격자가 심을 수 있는 것은
    툴 결과다.
    """
    return _JOIN.join(_texts_for_roles(payload, TRUSTED_ROLES))


def is_tainted(payload: Any) -> bool:
    """대화에 외부 데이터가 들어왔는가 (§8 1단계).

    ``messages`` 가 매 턴 전체로 오므로 매 요청에서 새로 계산한다 — 세션 저장소도
    세션 헤더도 필요 없다 (§7.4).

    assistant 의 ``tool_calls`` 만으로는 오염이 아니다. **결과가 들어와야** 외부
    데이터다. 부르려고 한 것과 받은 것은 다르다.

    오염은 되돌아가지 않는다 — 위치와 무관하게 하나라도 있으면 오염이다 (§8).
    """
    if not isinstance(payload, dict):
        return False
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return False
    return any(
        isinstance(message, dict) and message.get("role") in TOOL_RESULT_ROLES
        for message in messages
    )


def _texts_for_roles(payload: Any, roles: frozenset[str]) -> list[str]:
    if not isinstance(payload, dict):
        return []
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return []

    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in roles:
            continue
        parts.extend(_content_texts(message.get("content")))
    return parts


def _content_texts(content: Any) -> list[str]:
    """``content`` 는 문자열이거나 멀티모달 조각 리스트다.

    이미지 조각을 문자열화하면 URL 안의 숫자가 패턴에 걸려 헛것을 막는다.
    """
    if isinstance(content, str):
        return [content] if content else []
    if not isinstance(content, list):
        return []

    texts: list[str] = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        text = part.get("text")
        if isinstance(text, str) and text:
            texts.append(text)
    return texts


__all__ = [
    "INPUT_ROLES",
    "TOOL_RESULT_ROLES",
    "TRUSTED_ROLES",
    "extract_input_text",
    "extract_output_texts",
    "extract_tool_result_text",
    "extract_trusted_text",
    "is_tainted",
]
