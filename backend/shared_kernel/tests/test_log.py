import logging

import httpx
import orjson
import pytest
from fastapi import FastAPI

from shared_kernel.config import LogSettings
from shared_kernel.log import (
    RequestContextMiddleware,
    configure_logging,
    get_request_id,
    set_request_id,
)


@pytest.fixture
def preserve_root_logger():
    """configure_logging은 루트 핸들러를 전부 교체한다.

    복원하지 않으면 pytest의 로그 캡처 핸들러까지 날아가 이후 테스트의
    caplog가 조용히 망가진다.
    """
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    yield root
    for h in root.handlers[:]:
        root.removeHandler(h)
    for h in saved_handlers:
        root.addHandler(h)
    root.setLevel(saved_level)


def test_request_id_context_roundtrip():
    set_request_id("req_abc")
    assert get_request_id() == "req_abc"


@pytest.fixture
def app():
    application = FastAPI()
    application.add_middleware(RequestContextMiddleware)

    @application.get("/who")
    async def who():
        return {"request_id": get_request_id()}

    return application


async def test_middleware_reuses_incoming_request_id(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/who", headers={"x-request-id": "req_from_caller"})
    assert r.json()["request_id"] == "req_from_caller"
    assert r.headers["x-request-id"] == "req_from_caller"


async def test_middleware_generates_one_when_absent(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/who")
    generated = r.json()["request_id"]
    assert generated
    assert r.headers["x-request-id"] == generated


async def test_request_ids_are_not_shared_between_requests(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        first = (await c.get("/who")).json()["request_id"]
        second = (await c.get("/who")).json()["request_id"]
    assert first != second


def test_configure_logging_is_idempotent(preserve_root_logger):
    root = preserve_root_logger
    configure_logging(LogSettings(level="DEBUG", json_output=True))
    configure_logging(LogSettings(level="DEBUG", json_output=True))
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG


def test_json_formatter_emits_parseable_lines_with_request_id(preserve_root_logger, capsys):
    configure_logging(LogSettings(level="INFO", json_output=True))
    set_request_id("req_json")
    logging.getLogger("probe").info("hello %s", "world")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = orjson.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "probe"
    assert payload["message"] == "hello world"
    assert payload["request_id"] == "req_json"


def test_json_formatter_includes_exception_text(preserve_root_logger, capsys):
    configure_logging(LogSettings(level="INFO", json_output=True))
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        logging.getLogger("probe").exception("failed")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = orjson.loads(line)
    assert "kaboom" in payload["exception"]


def test_configured_level_actually_filters(preserve_root_logger, capsys):
    """레벨이 설정만 되고 적용되지 않으면 조용히 로그가 넘쳐난다."""
    configure_logging(LogSettings(level="WARNING", json_output=True))
    log = logging.getLogger("probe")
    log.info("suppressed")
    log.warning("emitted")

    out = capsys.readouterr().out
    assert "emitted" in out
    assert "suppressed" not in out


def test_text_formatter_is_used_when_json_disabled(preserve_root_logger, capsys):
    configure_logging(LogSettings(level="INFO", json_output=False))
    set_request_id("req_text")
    logging.getLogger("probe").warning("plain output")

    out = capsys.readouterr().out
    assert "req_text" in out
    assert "plain output" in out
    assert not out.strip().startswith("{")
