"""Shieldstral HTTP adapter contract tests."""

import math

import httpx
import orjson
import pytest

from gateway.guardrail.application.port.model_judge import JudgeImage, JudgeRequest
from gateway.guardrail.infrastructure.adapter.httpx_model_judge import HttpxModelJudge


def _request(*, strictness: str = "balanced", images: tuple[JudgeImage, ...] = ()) -> JudgeRequest:
    return JudgeRequest(
        checkpoint="input",
        node_id=f"model-{strictness}",
        policy="Does this text contain a secret?",
        text="the document",
        strictness=strictness,
        deadline_ms=500,
        images=images,
    )


def _response(*, yes: float, no: float, raw_label: str = "Yes.") -> httpx.Response:
    return httpx.Response(
        200,
        content=orjson.dumps(
            {
                "choices": [
                    {
                        "message": {"content": raw_label},
                        "logprobs": {
                            "content": [
                                {
                                    "token": raw_label,
                                    "top_logprobs": [
                                        {"token": ' "YES" ', "logprob": yes},
                                        {"token": "'no'", "logprob": no},
                                    ],
                                }
                            ]
                        },
                    }
                ]
            }
        ),
    )


async def test_shieldstral_payload_score_and_strictness_threshold() -> None:
    """공식 one-token 계약과 strict의 낮은 threshold를 함께 적용한다."""
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(orjson.loads(request.content))
        # yes 확률 약 0.45: balanced(0.5)는 통과, strict(0.4)는 위반이다.
        return _response(yes=math.log(0.45), no=math.log(0.55))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = HttpxModelJudge(
        endpoint="http://judge/v1/chat/completions",
        model="mistralai/Shieldstral-1.0-3B",
        revision="revision",
        threshold=0.5,
        timeout_ms=1_000,
        client=client,
    )
    try:
        strict, balanced = await adapter.judge(
            [_request(strictness="strict"), _request(strictness="balanced")]
        )
    finally:
        await adapter.aclose()

    assert strict.violated is True
    assert balanced.violated is False
    assert strict.score == balanced.score
    assert strict.score == pytest.approx(0.45)
    assert strict.raw_label == "Yes."
    assert adapter.model_id == "mistralai/Shieldstral-1.0-3B"
    assert adapter.model_revision == "revision"
    assert len(payloads) == 2
    assert payloads[0]["max_tokens"] == 1
    assert payloads[0]["temperature"] == 0
    assert payloads[0]["logprobs"] is True
    assert payloads[0]["top_logprobs"] == 20
    assert "<Query>: Does this text contain a secret?" in payloads[0]["messages"][1]["content"]
    assert "<Document>: [User]\nthe document" in payloads[0]["messages"][1]["content"]


async def test_images_switch_only_the_user_content_to_openai_parts() -> None:
    """이미지가 있을 때만 원본 URL 순서의 content part 배열을 보낸다."""
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(orjson.loads(request.content))
        return _response(yes=math.log(0.1), no=math.log(0.9), raw_label="no")

    adapter = HttpxModelJudge(
        endpoint="http://judge/v1/chat/completions",
        model="model",
        revision="",
        threshold=0.5,
        timeout_ms=1_000,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    images = (
        JudgeImage("user", 1, 2, "data:image/png;base64,AAAA"),
        JudgeImage("user", 3, 0, "https://images.example/second.png"),
    )
    try:
        await adapter.judge([_request(images=images)])
    finally:
        await adapter.aclose()

    content = payloads[0]["messages"][1]["content"]
    assert isinstance(content, list)
    assert content[0]["text"].endswith("<Document>: [User]\nthe document")
    assert content[1:] == [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {
            "type": "image_url",
            "image_url": {"url": "https://images.example/second.png"},
        },
    ]


async def test_missing_yes_or_no_logprob_is_a_failed_judgement() -> None:
    """yes/no 둘 중 하나라도 top logprobs에 없으면 allow로 만들지 않는다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=orjson.dumps(
                {
                    "choices": [
                        {
                            "message": {"content": "yes"},
                            "logprobs": {
                                "content": [
                                    {
                                        "token": "yes",
                                        "top_logprobs": [{"token": "yes", "logprob": -0.1}],
                                    }
                                ]
                            },
                        }
                    ]
                }
            ),
        )

    adapter = HttpxModelJudge(
        endpoint="http://judge/v1/chat/completions",
        model="model",
        revision="",
        threshold=0.5,
        timeout_ms=1_000,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        result = (await adapter.judge([_request()]))[0]
    finally:
        await adapter.aclose()

    assert result.violated is None
    assert result.score is None


async def test_transport_and_server_failures_return_failed_judgements() -> None:
    """timeout과 서버 오류는 예외나 조용한 allow가 아니라 violated=None이다."""

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    adapters = [
        HttpxModelJudge(
            endpoint="http://judge/v1/chat/completions",
            model="model",
            revision="",
            threshold=0.5,
            timeout_ms=1_000,
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        for handler in (timeout, server_error)
    ]
    try:
        results = [(await adapter.judge([_request()]))[0] for adapter in adapters]
    finally:
        for adapter in adapters:
            await adapter.aclose()

    assert [result.violated for result in results] == [None, None]
    assert results[0].raw_label == "transport_error"
    assert results[1].raw_label == "http_503"
