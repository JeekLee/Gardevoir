import httpx
import pytest_asyncio

from gateway.presentation.http.app import create_app
from shared_kernel.log import REQUEST_ID_HEADER


@pytest_asyncio.fixture
async def app(engine):
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_request_id_is_echoed(client):
    r = await client.get("/healthz", headers={REQUEST_ID_HEADER: "req_caller"})
    assert r.headers[REQUEST_ID_HEADER] == "req_caller"


async def test_request_id_is_generated_when_absent(client):
    r = await client.get("/healthz")
    assert r.headers[REQUEST_ID_HEADER]


async def test_request_ids_differ_between_requests(client):
    a = (await client.get("/healthz")).headers[REQUEST_ID_HEADER]
    b = (await client.get("/healthz")).headers[REQUEST_ID_HEADER]
    assert a != b


async def test_unknown_route_is_json_shaped(client):
    """404가 shared_kernel 의 ErrorResponse 형태로 나가야 한다.

    FastAPI 기본 404 는 {"detail": ...} 이므로, 중앙 핸들러가 HTTPException 을
    받지 않으면 여기서 드러난다. Phase 1a 검토가 넘긴 항목이다.
    """
    r = await client.get("/nope")
    assert r.status_code == 404
    body = r.json()
    assert "code" in body
    assert "message" in body
    assert "detail" not in body


async def test_unhandled_error_response_carries_request_id(client, app):
    """미처리 예외 500에도 상관 ID가 붙어야 한다.

    Exception 핸들러는 RequestContextMiddleware 바깥의 ServerErrorMiddleware 에서
    돌기 때문에 순진하게 조립하면 헤더가 빠진다. Phase 1a 검토가 넘긴 항목이다.
    """

    @app.get("/boom-test")
    async def boom():
        raise RuntimeError("kaboom")

    r = await client.get("/boom-test")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL"
    assert "kaboom" not in r.text
    assert r.headers.get(REQUEST_ID_HEADER)


async def test_validation_error_is_json_shaped_and_hides_the_payload(client, app):
    """422 도 같은 형태로 나가고, 에코된 입력값을 싣지 않는다."""
    from pydantic import BaseModel

    class Body(BaseModel):
        n: int

    @app.post("/needs-int")
    async def needs_int(body: Body):
        return {"n": body.n}

    r = await client.post("/needs-int", json={"n": "not-an-int"})
    assert r.status_code == 422
    body = r.json()
    assert "code" in body
    assert "message" in body
    assert "detail" not in body
    # 호출자 페이로드와 내부 경로가 응답에 실려서는 안 된다
    assert "not-an-int" not in r.text
    assert "url" not in r.text


async def test_key_cache_is_wired_into_app_state(app):
    assert app.state.key_cache is not None
    assert app.state.key_cache.misses == 0
