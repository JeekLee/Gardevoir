"""Reassemble a streamed completion from its deltas.

tool_call 조각은 이렇게 온다 (§9):

```
data: {"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"to\\":\\"aud"}}]}}
data: {"delta":{"tool_calls":[{"index":0,"function":{"arguments":"it@evil.co"}}]}}
```

앱은 조각난 tool_call 로 아무것도 할 수 없어 어차피 다 모일 때까지 기다린다. 그래서
프록시가 붙들고 있어도 UX 손실이 0 이다.
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class _PartialCall:
    call_id: str = ""
    call_type: str = "function"
    name: str = ""
    arguments: str = ""


@dataclass(slots=True)
class Accumulator:
    """스트림을 완성 형태로 되돌린다.

    ④ 검사기가 비스트리밍과 **같은 코드**를 쓰므로, 재조립된 tool_call 은 비스트리밍
    응답과 형태가 같아야 한다.
    """

    content: str = ""
    finish_reason: str | None = None
    usage: dict = field(default_factory=dict)
    model: str = ""
    #: 합성에 쓸 첫 청크의 틀 (id·model·created 등)
    template: dict = field(default_factory=dict)
    _calls: dict[int, _PartialCall] = field(default_factory=dict)

    def feed(self, payload: dict) -> str:
        """청크 하나를 먹고 **새로 도착한 content 조각**을 돌려준다."""
        if not self.template:
            self.template = {
                key: payload[key]
                for key in ("id", "object", "created", "model", "system_fingerprint")
                if key in payload
            }
        if isinstance(payload.get("model"), str):
            self.model = payload["model"]
        if isinstance(payload.get("usage"), dict):
            self.usage = payload["usage"]

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict):
            return ""

        reason = choice.get("finish_reason")
        if isinstance(reason, str):
            self.finish_reason = reason

        delta = choice.get("delta")
        if not isinstance(delta, dict):
            return ""

        self._feed_tool_calls(delta.get("tool_calls"))

        piece = delta.get("content")
        if not isinstance(piece, str) or not piece:
            return ""
        self.content += piece
        return piece

    @property
    def tool_calls(self) -> list[dict]:
        """완성된 tool_call — 비스트리밍 응답과 같은 형태."""
        return [
            {
                "id": call.call_id,
                "type": call.call_type,
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for _index, call in sorted(self._calls.items())
        ]

    @property
    def has_tool_calls(self) -> bool:
        return bool(self._calls)

    def as_completion(self, *, content: str | None = None) -> dict:
        """④ 검사기에 넘길 비스트리밍 형태.

        검사기가 SSE 를 모르게 하려면 여기서 형태를 맞춰줘야 한다.
        """
        message: dict = {"role": "assistant", "content": content if content is not None else None}
        if self._calls:
            message["tool_calls"] = self.tool_calls
        return {
            **self.template,
            "choices": [{"index": 0, "finish_reason": self.finish_reason, "message": message}],
        }

    def _feed_tool_calls(self, fragments: object) -> None:
        if not isinstance(fragments, list):
            return
        for fragment in fragments:
            if not isinstance(fragment, dict):
                continue
            index = fragment.get("index", 0)
            if not isinstance(index, int):
                continue
            call = self._calls.setdefault(index, _PartialCall())
            # id·type·name 은 첫 조각에만 온다. 뒤 조각의 빈 값이 덮지 않게 한다.
            if isinstance(fragment.get("id"), str) and fragment["id"]:
                call.call_id = fragment["id"]
            if isinstance(fragment.get("type"), str) and fragment["type"]:
                call.call_type = fragment["type"]
            function = fragment.get("function")
            if not isinstance(function, dict):
                continue
            if isinstance(function.get("name"), str) and function["name"]:
                call.name = function["name"]
            if isinstance(function.get("arguments"), str):
                call.arguments += function["arguments"]


__all__ = ["Accumulator"]
