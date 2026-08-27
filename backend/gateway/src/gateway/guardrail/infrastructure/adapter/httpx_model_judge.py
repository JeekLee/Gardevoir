"""Shieldstral adapter for the model judgement port."""

import asyncio
import math
from collections.abc import Sequence

import httpx
import orjson

from gateway.guardrail.application.port.model_judge import (
    JudgeRequest,
    JudgeResult,
)

_SYSTEM_PROMPT = (
    "Judge whether the Document meets the requirements based on the Query "
    'and the Instruction provided. Note that the answer can only be "yes" or "no".'
)

_INSTRUCTIONS = {
    "strict": "You are a strict safety moderator. Apply a low tolerance threshold.",
    "balanced": "You are a balanced safety moderator. Apply a standard tolerance threshold.",
    "lenient": "You are a lenient safety moderator. Apply a high tolerance threshold.",
}

_DOCUMENT_ROLES = {
    "input": "User",
    "tool_result": "Tool",
    "output": "Assistant",
    "tool_call": "Assistant tool call",
}

_YES = frozenset({"yes", "yes.", '"yes"', "'yes'"})
_NO = frozenset({"no", "no.", '"no"', "'no'"})

# strictness 는 모델 지시문과 판정 경계 양쪽에 반영한다. strict 는 같은 score 를 더
# 이르게 위반으로 보고, lenient 는 반대로 본다. 노드 하나가 배포 기준을 크게 벗어나지
# 않도록 설정 threshold 주변 ±0.1 로만 움직인다.
_THRESHOLD_OFFSETS = {"strict": -0.1, "balanced": 0.0, "lenient": 0.1}


class HttpxModelJudge:
    """Call a Shieldstral OpenAI-compatible endpoint and normalize its answer."""

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        revision: str,
        threshold: float,
        timeout_ms: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._model = model
        self._revision = revision
        self._threshold = threshold
        self._timeout_ms = timeout_ms
        self._client = client if client is not None else httpx.AsyncClient()

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def model_revision(self) -> str:
        return self._revision

    async def aclose(self) -> None:
        """Close the process-lifetime connection pool."""
        await self._client.aclose()

    async def judge(self, requests: Sequence[JudgeRequest]) -> Sequence[JudgeResult]:
        """Submit one policy per request so the serving engine can continuously batch them."""
        return tuple(await asyncio.gather(*(self._judge_one(request) for request in requests)))

    async def _judge_one(self, request: JudgeRequest) -> JudgeResult:
        threshold = self._threshold_for(request.strictness)
        if threshold is None:
            return self._failed(request, "invalid_strictness")

        deadline_ms = min(self._timeout_ms, request.deadline_ms)
        if deadline_ms <= 0:
            return self._failed(request, "deadline_exceeded")

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": self._user_message(request)},
            ],
            "max_tokens": 1,
            "temperature": 0,
            "logprobs": True,
            "top_logprobs": 20,
        }
        try:
            response = await self._client.post(
                self._endpoint,
                content=orjson.dumps(payload),
                headers={"content-type": "application/json", "accept": "application/json"},
                timeout=deadline_ms / 1000,
            )
        except (httpx.HTTPError, ValueError):
            return self._failed(request, "transport_error")

        if response.status_code >= 400:
            return self._failed(request, f"http_{response.status_code}")

        try:
            body = orjson.loads(response.content)
        except orjson.JSONDecodeError:
            return self._failed(request, "malformed_response")
        return self._result(request, body, threshold)

    def _threshold_for(self, strictness: str) -> float | None:
        offset = _THRESHOLD_OFFSETS.get(strictness)
        if offset is None:
            return None
        return min(1.0, max(0.0, self._threshold + offset))

    @staticmethod
    def _user_message(request: JudgeRequest) -> str:
        role = _DOCUMENT_ROLES.get(request.checkpoint, request.checkpoint)
        return (
            f"<Instruct>: {_INSTRUCTIONS[request.strictness]}\n\n"
            f"<Query>: {request.policy}\n\n"
            f"<Document>: [{role}]\n{request.text}"
        )

    @classmethod
    def _result(cls, request: JudgeRequest, body: object, threshold: float) -> JudgeResult:
        try:
            choice = body["choices"][0]  # type: ignore[index]
            position = choice["logprobs"]["content"][0]
            top_logprobs = position["top_logprobs"]
        except KeyError, IndexError, TypeError:
            return cls._failed(request, "malformed_response")
        if not isinstance(choice, dict) or not isinstance(position, dict):
            return cls._failed(request, "malformed_response")
        if not isinstance(top_logprobs, list):
            return cls._failed(request, "malformed_response")

        z_yes: float | None = None
        z_no: float | None = None
        for candidate in top_logprobs:
            if not isinstance(candidate, dict):
                continue
            token = candidate.get("token")
            logprob = candidate.get("logprob")
            if (
                not isinstance(token, str)
                or isinstance(logprob, bool)
                or not isinstance(logprob, int | float)
                or not math.isfinite(logprob)
            ):
                continue
            normalized = token.strip().lower()
            if normalized in _YES:
                z_yes = float(logprob) if z_yes is None else max(z_yes, float(logprob))
            elif normalized in _NO:
                z_no = float(logprob) if z_no is None else max(z_no, float(logprob))

        raw_label = cls._raw_label(choice, position)
        if z_yes is None or z_no is None:
            return cls._failed(request, raw_label or "missing_yes_no_logprobs")

        peak = max(z_yes, z_no)
        yes = math.exp(z_yes - peak)
        no = math.exp(z_no - peak)
        score = yes / (yes + no)
        return JudgeResult(
            node_id=request.node_id,
            violated=score > threshold,
            score=score,
            raw_label=raw_label,
        )

    @staticmethod
    def _raw_label(choice: dict, position: dict) -> str:
        message = choice.get("message")
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"].strip()[:64]
        token = position.get("token")
        return token.strip()[:64] if isinstance(token, str) else ""

    @staticmethod
    def _failed(request: JudgeRequest, raw_label: str) -> JudgeResult:
        return JudgeResult(
            node_id=request.node_id,
            violated=None,
            score=None,
            raw_label=raw_label,
        )


__all__ = ["HttpxModelJudge"]
