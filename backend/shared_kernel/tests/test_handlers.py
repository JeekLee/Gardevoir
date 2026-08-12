import httpx
import pytest
from fastapi import FastAPI

from shared_kernel.exception import (
    AppError,
    ErrorCatalog,
    NotFoundError,
    UnauthorizedError,
    register_exception_handlers,
)


class ThingError(ErrorCatalog):
    MISSING = ("THING-001", "no such thing", NotFoundError)
    NO_KEY = ("THING-002", "key required", UnauthorizedError)


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
