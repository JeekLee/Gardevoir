"""JsonResponse — 프로젝트는 직렬화기를 하나만 쓴다 (AGENTS.md)."""

import datetime as dt
import decimal

import orjson
import pytest

from shared_kernel.api import JsonResponse


def _rendered(content) -> object:
    return orjson.loads(JsonResponse(content).body)


def test_renders_json():
    assert _rendered({"a": 1, "b": [1, 2]}) == {"a": 1, "b": [1, 2]}


def test_media_type_is_json():
    assert JsonResponse({}).headers["content-type"].startswith("application/json")


def test_uses_orjson_not_json():
    """json.dumps 는 공백을 넣는다. orjson 은 넣지 않는다."""
    assert JsonResponse({"a": 1, "b": 2}).body == b'{"a":1,"b":2}'


def test_serialises_datetime():
    at = dt.datetime(2026, 8, 13, 1, 2, 3, tzinfo=dt.UTC)
    assert _rendered({"at": at}) == {"at": "2026-08-13T01:02:03+00:00"}


def test_unknown_types_fall_back_to_str():
    """마지막 안전망 — 응답을 렌더하다 500 을 내지 않는다."""
    assert _rendered({"d": decimal.Decimal("1.5")}) == {"d": "1.5"}


def test_a_genuinely_unserialisable_value_still_raises():
    """default=str 이 모든 것을 삼키면 조용히 잘못된 응답이 나간다."""

    class Loud:
        def __str__(self):
            raise RuntimeError("nope")

    # orjson 은 default 안의 예외를 JSONEncodeError(TypeError) 로 감싼다.
    with pytest.raises(TypeError):
        JsonResponse({"x": Loud()})
