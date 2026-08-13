"""What to inspect at each checkpoint (§3).

**모양이 이상하면 빈 결과를 낸다.** 업스트림이 거부할 페이로드를 우리가 먼저
터뜨리면 가드레일이 가용성 문제가 된다 — 프록시는 통과시키고 업스트림이 400 을
내게 한다.
"""

from typing import Any

#: ① 은 사용자 입력이다. assistant 는 ③, tool 결과는 ②(Phase 3)가 본다.
INPUT_ROLES = frozenset({"user"})

_JOIN = "\n"


def extract_input_text(payload: Any) -> str:
    """① 검사 대상.

    ``messages`` 는 매 턴 전체가 다시 온다 (§7.4). 마지막 user 메시지만 보면 여러
    턴에 나눠 심은 것을 놓치므로 전부 이어붙인다.
    """
    if not isinstance(payload, dict):
        return ""
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""

    parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in INPUT_ROLES:
            continue
        parts.extend(_content_texts(message.get("content")))
    return _JOIN.join(parts)


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


__all__ = ["INPUT_ROLES", "extract_input_text", "extract_output_texts"]
