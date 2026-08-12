import logging
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI

from shared_kernel.exception import (
    AppError,
    ErrorCatalog,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    register_exception_handlers,
)


class ThingError(ErrorCatalog):
    MISSING = ("THING-001", "no such thing", NotFoundError)
    NO_KEY = ("THING-002", "key required", UnauthorizedError)
    NOT_ALLOWED = ("THING-003", "not allowed", ForbiddenError)


class _Opaque:
    """An object with no JSON representation at all."""

    def __repr__(self) -> str:
        return "<opaque>"


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/missing")
    async def missing():
        ThingError.MISSING.raise_()

    @app.get("/detailed")
    async def detailed():
        ThingError.NO_KEY.raise_(details={"header": "authorization"})

    @app.get("/boom")
    async def boom():
        raise AppError("something broke internally")

    @app.get("/unhandled")
    async def unhandled():
        raise RuntimeError("not an AppError")

    # details는 BC가 쓰는 유일한 구조화 채널이므로 JSON 네이티브가 아닌 값이
    # 들어온다. 어느 경우에도 원래 상태·코드를 잃어서는 안 된다.
    @app.get("/details-set")
    async def details_set():
        ThingError.NOT_ALLOWED.raise_(details={"allowed": {"base", "strict"}})

    @app.get("/details-decimal")
    async def details_decimal():
        ThingError.NOT_ALLOWED.raise_(details={"budget": Decimal("1.5")})

    @app.get("/details-opaque")
    async def details_opaque():
        ThingError.NOT_ALLOWED.raise_(details={"thing": _Opaque()})

    @app.get("/details-not-a-dict")
    async def details_not_a_dict():
        ThingError.NOT_ALLOWED.raise_(details=["not", "a", "dict"])

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_catalog_error_maps_to_its_category_status(client):
    async with client as c:
        r = await c.get("/missing")
    assert r.status_code == 404
    assert r.json() == {"code": "THING-001", "message": "no such thing"}


async def test_details_are_included_when_present(client):
    async with client as c:
        r = await c.get("/detailed")
    assert r.status_code == 401
    assert r.json()["details"] == {"header": "authorization"}


async def test_internal_apperror_is_500_with_generic_code(client):
    async with client as c:
        r = await c.get("/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL"


async def test_unexpected_exception_does_not_leak_its_message(client):
    """예상 못 한 예외의 메시지는 내부 정보다. 클라이언트에 흘리지 않는다."""
    async with client as c:
        r = await c.get("/unhandled")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL"
    assert "not an AppError" not in r.text


@pytest.mark.parametrize(
    ("path", "expected_details"),
    [
        ("/details-set", {"allowed": ["base", "strict"]}),
        ("/details-decimal", {"budget": "1.5"}),
        ("/details-opaque", None),
        ("/details-not-a-dict", None),
    ],
)
async def test_unrenderable_details_never_change_status_or_code(client, path, expected_details):
    """직렬화 불가한 details가 403을 500으로 바꿔서는 안 된다.

    진단 필드를 잃는 것은 허용되지만, 클라이언트가 재시도 가능한 서버 장애로
    오해하게 만드는 것은 허용되지 않는다.
    """
    async with client as c:
        r = await c.get(path)

    assert r.status_code == 403
    body = r.json()
    assert body["code"] == "THING-003"
    assert body["message"] == "not allowed"
    if expected_details is None:
        assert "details" not in body
    else:
        got = body["details"]
        if isinstance(expected_details.get("allowed"), list):
            assert sorted(got["allowed"]) == sorted(expected_details["allowed"])
        else:
            assert got == expected_details


async def test_client_error_is_logged_at_warning(client, caplog):
    """4xx가 실제로 WARNING으로 남는지. 로그 호출 자체가 커버돼야 한다."""
    with caplog.at_level(logging.DEBUG, logger="shared_kernel.exception.handlers"):
        async with client as c:
            await c.get("/missing")

    records = [r for r in caplog.records if "THING-001" in r.getMessage()]
    assert records, "4xx 처리에서 로그가 남지 않았다"
    assert records[0].levelno == logging.WARNING


async def test_server_error_is_logged_at_error(client, caplog):
    with caplog.at_level(logging.DEBUG, logger="shared_kernel.exception.handlers"):
        async with client as c:
            await c.get("/boom")

    records = [r for r in caplog.records if "something broke internally" in r.getMessage()]
    assert records, "5xx 처리에서 로그가 남지 않았다"
    assert records[0].levelno == logging.ERROR


async def test_unrenderable_details_are_reported_in_logs(client, caplog):
    """details를 버렸다는 사실이 조용히 사라지면 안 된다."""
    with caplog.at_level(logging.DEBUG, logger="shared_kernel.exception.handlers"):
        async with client as c:
            await c.get("/details-not-a-dict")

    assert any("could not be rendered" in r.getMessage() for r in caplog.records)
