import httpx
import pytest_asyncio

from gateway.domain.models.api_key import Scope, generate_key, hash_key
from gateway.infrastructure.models.api_key import ApiKeyModel
from gateway.presentation.http.admin_guardrails import ADMIN_PREFIX
from gateway.presentation.http.app import create_app
from gateway.settings import get_settings
from shared_kernel.log import REQUEST_ID_HEADER

BASE = ADMIN_PREFIX


def _graph(max_chars: int = 100) -> dict:
    return {
        "nodes": [
            {"id": "n0", "type": "extract", "config": {"checkpoint": "input"}},
            {"id": "n1", "type": "length", "config": {"max_chars": max_chars}},
        ],
        "edges": [{"src": "n0", "dst": "n1"}],
    }


CYCLIC = {
    "nodes": [
        {"id": "a", "type": "transform", "config": {"op": "lower"}},
        {"id": "b", "type": "transform", "config": {"op": "strip"}},
    ],
    "edges": [{"src": "a", "dst": "b"}, {"src": "b", "dst": "a"}],
}


async def _add_key(session, *, id: str, scopes: list[str]) -> str:
    raw = generate_key()
    session.add(
        ApiKeyModel(
            id=id,
            name=id,
            key_hash=hash_key(raw),
            upstream_base_url="https://api.openai.com/v1",
            upstream_api_key="sk-upstream",
            allowed_guardrails=[],
            default_guardrail=None,
            scopes=scopes,
        )
    )
    await session.commit()
    return raw


@pytest_asyncio.fixture
async def admin_key(session):
    return await _add_key(session, id="k-admin", scopes=[Scope.ADMIN, Scope.PROXY])


@pytest_asyncio.fixture
async def proxy_key(session):
    return await _add_key(session, id="k-proxy", scopes=[Scope.PROXY])


@pytest_asyncio.fixture
async def app(engine, ch_client):
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def client(app, admin_key):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"authorization": f"Bearer {admin_key}"},
    ) as c:
        yield c


# --- 인가 --------------------------------------------------------------------


async def test_missing_authorization_is_401(app):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get(BASE)
    assert r.status_code == 401


async def test_a_proxy_only_key_is_403(app, proxy_key):
    """프록시 키로 정책을 바꿀 수 있으면 스코프가 아무 의미가 없다."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"authorization": f"Bearer {proxy_key}"},
    ) as c:
        r = await c.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    assert r.status_code == 403
    assert r.json()["code"] == "APIKEY-005"


def _iter_api_routes(routes):
    """등록된 라우트를 평탄화한다.

    FastAPI 0.141 은 include_router 한 라우터를 _IncludedRouter 로 감싸서
    app.routes 에 넣으므로, app.routes 만 훑으면 경로가 하나도 안 보인다.
    openapi() 를 쓰지 않는 이유는 include_in_schema=False 라우트를 놓치기 때문이다 —
    스펙에서 숨긴 라우트야말로 인가가 빠지면 위험한 쪽이다.
    """
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _iter_api_routes(included.routes)
            continue
        if getattr(route, "path", None) and getattr(route, "methods", None):
            yield route


def _admin_routes(app) -> list[tuple[str, str]]:
    """앱에 실제로 등록된 admin 라우트를 뽑는다.

    손으로 적은 목록이면 검사에서 빠진 라우트가 생길 수 있고, 그게 바로 이 테스트가
    막으려는 상황이다.
    """
    found = [
        (method, route.path)
        for route in _iter_api_routes(app.routes)
        if route.path.startswith(ADMIN_PREFIX)
        for method in sorted(route.methods - {"HEAD", "OPTIONS"})
    ]
    assert found, "admin 라우트를 찾지 못했다"
    return sorted(found)


def test_the_route_walker_sees_the_whole_app():
    """평탄화가 깨지면 위 두 테스트가 빈 목록으로 통과한다."""
    app = create_app()
    paths = {route.path for route in _iter_api_routes(app.routes)}
    assert "/healthz" in paths
    assert "/v1/chat/completions" in paths
    assert ADMIN_PREFIX in paths


def _concrete(path: str) -> str:
    return path.replace("{name}", "x").replace("{version_number}", "1")


async def test_every_route_requires_the_admin_scope(app, proxy_key):
    """라우트 하나를 놓치면 그 하나로 전부 우회된다.

    라우트 목록을 앱에서 뽑으므로, 인가 없는 라우트를 새로 추가하면 여기서 깨진다.
    """
    routes = _admin_routes(app)
    assert len(routes) >= 7, routes

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"authorization": f"Bearer {proxy_key}"},
    ) as c:
        for method, path in routes:
            r = await c.request(method, _concrete(path), json={"name": "x", "graph": _graph()})
            assert r.status_code == 403, (method, path, r.status_code)
            assert r.json()["code"] == "APIKEY-005", (method, path)


async def test_every_route_rejects_a_missing_credential(app):
    routes = _admin_routes(app)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        for method, path in routes:
            r = await c.request(method, _concrete(path), json={"name": "x", "graph": _graph()})
            assert r.status_code == 401, (method, path, r.status_code)


async def test_authorisation_precedes_body_validation(app):
    """크레덴셜 없는 호출자가 422 로 스키마를 알아내면 안 된다.

    인가가 핸들러 첫 줄이면 FastAPI 가 본문을 먼저 검증해서 422 가 나간다.
    라우터 레벨 의존성이어야 401 이 먼저다.
    """
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(BASE, json={"name": "x"})  # graph 누락
    assert r.status_code == 401
    assert "graph" not in r.text


DOC_PATHS = ("/openapi.json", "/docs", "/redoc")


async def test_the_openapi_spec_is_not_public(app):
    """스펙이 익명으로 열려 있으면 인그레스에서 /v1/admin 을 막아도 경로가 새어나간다."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        for path in DOC_PATHS:
            r = await c.get(path)
            assert r.status_code == 404, path


async def test_the_spec_still_opens_in_debug(engine, ch_client):
    """위 테스트가 '스펙을 영구히 못 켠다'로 통과하는 빈 단정이 아님을 보인다."""
    settings = get_settings().model_copy(update={"debug": True})
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            for path in DOC_PATHS:
                r = await c.get(path)
                assert r.status_code == 200, path

            spec = (await c.get("/openapi.json")).json()
    assert ADMIN_PREFIX in spec["paths"]


# --- create ------------------------------------------------------------------


async def test_create_returns_201_with_the_detail(client):
    r = await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "doc-agent"
    assert body["version"] == "draft"
    assert body["versionNumber"] is None
    assert [n["id"] for n in body["graph"]["nodes"]] == ["n0", "n1"]


async def test_create_duplicate_is_409(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    r = await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    assert r.status_code == 409
    assert r.json()["code"] == "GUARDRAIL-006"


async def test_create_invalid_graph_is_422_and_names_the_node(client):
    r = await client.post(
        BASE,
        json={
            "name": "doc-agent",
            "graph": {"nodes": [{"id": "n9", "type": "length", "config": {}}], "edges": []},
        },
    )
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "GUARDRAIL-005"
    # details 는 불투명한 dict 다 — 안쪽 키는 camel 로 바뀌지 않는다.
    assert body["details"]["node_id"] == "n9"


async def test_create_cycle_is_422(client):
    r = await client.post(BASE, json={"name": "looping", "graph": CYCLIC})
    assert r.status_code == 422
    assert r.json()["code"] == "GUARDRAIL-002"


async def test_create_invalid_name_is_422(client):
    r = await client.post(BASE, json={"name": "Doc Agent!", "graph": _graph()})
    assert r.status_code == 422
    assert r.json()["code"] == "GUARDRAIL-010"


async def test_create_missing_graph_is_422_in_our_shape(client):
    """FastAPI 기본 {"detail": ...} 가 새어나가면 응답 계약이 둘이 된다."""
    r = await client.post(BASE, json={"name": "doc-agent"})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION"


async def test_a_rejected_create_is_not_persisted(client):
    await client.post(BASE, json={"name": "looping", "graph": CYCLIC})
    r = await client.get(BASE)
    assert r.json()["items"] == []


async def test_a_dangerous_path_segment_is_422_not_500(client):
    """이름 규칙이 쓰기 경로에만 걸려 있으면 경로 조각이 그대로 DB 질의로 내려간다.

    psycopg 는 text 파라미터의 NUL 을 거부하므로 500 이 되고, SQL 과 스택트레이스가
    로그에 남는다.
    """
    for path in (
        f"{BASE}/x%00y",
        f"{BASE}/x%00y/draft",
        f"{BASE}/{'a' * 300}",
    ):
        r = await client.get(path)
        assert r.status_code == 422, (path, r.status_code)
        assert r.json()["code"] == "GUARDRAIL-010", path


async def test_a_dangerous_path_segment_is_422_on_writes_too(client):
    for call in (
        client.post(f"{BASE}/x%00y/publish"),
        client.put(f"{BASE}/x%00y/draft", json={"graph": _graph()}),
        client.get(f"{BASE}/x%00y/versions/1"),
    ):
        r = await call
        assert r.status_code == 422, r.request.url
        assert r.json()["code"] == "GUARDRAIL-010"


async def test_the_echoed_name_is_bounded(client):
    """오류 details 가 호출자가 보낸 것을 그대로 되비추면 안 된다."""
    r = await client.get(f"{BASE}/{'a' * 300}")
    assert len(r.json()["details"]["name"]) <= 64


async def test_a_nul_inside_the_graph_is_422_not_500(client):
    """Postgres jsonb 는 \\u0000 을 담지 못한다 — INSERT 가 죽으면 저작자에게 500 이 간다."""
    graph = {
        "nodes": [
            {"id": "n0", "type": "extract", "config": {"checkpoint": "input", "x": "a\u0000b"}}
        ],
        "edges": [],
    }
    r = await client.post(BASE, json={"name": "nul-config", "graph": graph})
    assert r.status_code == 422
    assert r.json()["code"] == "GUARDRAIL-005"


async def test_a_nul_in_a_node_id_is_422_not_500(client):
    graph = {
        "nodes": [{"id": "n\u00000", "type": "extract", "config": {"checkpoint": "input"}}],
        "edges": [],
    }
    r = await client.post(BASE, json={"name": "nul-id", "graph": graph})
    assert r.status_code == 422
    assert r.json()["code"] == "GUARDRAIL-005"


async def test_a_rejected_nul_stores_nothing(client):
    graph = {
        "nodes": [
            {"id": "n0", "type": "extract", "config": {"checkpoint": "input", "x": "a\u0000b"}}
        ],
        "edges": [],
    }
    await client.post(BASE, json={"name": "nul-config", "graph": graph})
    assert (await client.get(BASE)).json()["items"] == []


# --- read --------------------------------------------------------------------


async def test_get_unknown_is_404_in_our_shape(client):
    r = await client.get(f"{BASE}/nope")
    assert r.status_code == 404
    assert r.json()["code"] == "GUARDRAIL-001"


async def test_get_draft_unknown_is_404(client):
    r = await client.get(f"{BASE}/nope/draft")
    assert r.status_code == 404
    assert r.json()["code"] == "GUARDRAIL-008"


async def test_get_returns_the_latest_published_not_the_draft(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph(10)})
    await client.post(f"{BASE}/doc-agent/publish")
    await client.put(f"{BASE}/doc-agent/draft", json={"graph": _graph(999)})

    r = await client.get(f"{BASE}/doc-agent")
    assert r.status_code == 200
    assert r.json()["graph"]["nodes"][1]["config"]["max_chars"] == 10
    assert r.json()["version"] == "1"


async def test_get_before_publishing_is_404(client):
    """draft 만 있는 가드레일은 프록시가 실행할 수 있는 것이 없다."""
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    r = await client.get(f"{BASE}/doc-agent")
    assert r.status_code == 404


async def test_list_returns_summaries(client):
    await client.post(BASE, json={"name": "alpha", "graph": _graph()})
    await client.post(BASE, json={"name": "bravo", "graph": _graph()})
    await client.post(f"{BASE}/bravo/publish")

    r = await client.get(BASE)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert [s["name"] for s in body["items"]] == ["alpha", "bravo"]


async def test_camel_case_on_the_wire(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    await client.post(f"{BASE}/doc-agent/publish")

    summary = (await client.get(BASE)).json()["items"][0]
    assert summary["latestVersionNumber"] == 1
    assert summary["hasDraft"] is True
    assert "latest_version_number" not in summary
    assert "has_draft" not in summary

    detail = (await client.get(f"{BASE}/doc-agent")).json()
    assert detail["versionNumber"] == 1
    assert "version_number" not in detail
    assert "createdAt" in detail


async def test_graph_keys_are_not_camelised(client):
    """graph 는 불투명한 dict 다. max_chars 가 maxChars 로 바뀌면 컴파일러가 깨진다."""
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    detail = (await client.get(f"{BASE}/doc-agent/draft")).json()
    assert detail["graph"]["nodes"][1]["config"] == {"max_chars": 100}


# --- write -------------------------------------------------------------------


async def test_put_draft_updates(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph(10)})
    r = await client.put(f"{BASE}/doc-agent/draft", json={"graph": _graph(999)})
    assert r.status_code == 200
    assert r.json()["graph"]["nodes"][1]["config"]["max_chars"] == 999

    again = await client.get(f"{BASE}/doc-agent/draft")
    assert again.json()["graph"]["nodes"][1]["config"]["max_chars"] == 999


async def test_put_draft_without_a_draft_is_404(client):
    r = await client.put(f"{BASE}/nope/draft", json={"graph": _graph()})
    assert r.status_code == 404
    assert r.json()["code"] == "GUARDRAIL-008"


async def test_a_rejected_update_is_not_persisted(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph(10)})
    r = await client.put(f"{BASE}/doc-agent/draft", json={"graph": CYCLIC})
    assert r.status_code == 422

    draft = await client.get(f"{BASE}/doc-agent/draft")
    assert draft.json()["graph"]["nodes"][1]["config"]["max_chars"] == 10


async def test_publish_returns_the_published_detail(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    r = await client.post(f"{BASE}/doc-agent/publish")
    assert r.status_code == 200
    assert r.json()["version"] == "1"
    assert r.json()["versionNumber"] == 1


async def test_publish_then_get_returns_the_published_version(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    await client.post(f"{BASE}/doc-agent/publish")
    r = await client.get(f"{BASE}/doc-agent")
    assert r.json()["versionNumber"] == 1


async def test_publish_twice_increments(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    await client.post(f"{BASE}/doc-agent/publish")
    r = await client.post(f"{BASE}/doc-agent/publish")
    assert r.json()["versionNumber"] == 2


async def test_get_specific_version_is_immutable(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph(10)})
    await client.post(f"{BASE}/doc-agent/publish")
    await client.put(f"{BASE}/doc-agent/draft", json={"graph": _graph(999)})
    await client.post(f"{BASE}/doc-agent/publish")

    v1 = await client.get(f"{BASE}/doc-agent/versions/1")
    assert v1.json()["graph"]["nodes"][1]["config"]["max_chars"] == 10


async def test_get_unknown_version_is_404(client):
    await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    r = await client.get(f"{BASE}/doc-agent/versions/7")
    assert r.status_code == 404


async def test_publish_without_a_draft_is_404(client):
    r = await client.post(f"{BASE}/nope/publish")
    assert r.status_code == 404
    assert r.json()["code"] == "GUARDRAIL-008"


# --- 계약 --------------------------------------------------------------------


async def test_responses_carry_the_request_id(client):
    r = await client.post(BASE, json={"name": "doc-agent", "graph": _graph()})
    assert r.headers[REQUEST_ID_HEADER]

    err = await client.get(f"{BASE}/nope")
    assert err.headers[REQUEST_ID_HEADER]


async def test_the_caller_request_id_is_reused(client):
    r = await client.get(BASE, headers={REQUEST_ID_HEADER: "corr-1"})
    assert r.headers[REQUEST_ID_HEADER] == "corr-1"


# --- 발행 -> 컴파일 ----------------------------------------------------------


BLOCKING = {
    "nodes": [
        {"id": "e", "type": "extract", "config": {"checkpoint": "input"}},
        {"id": "r", "type": "regex", "config": {"pattern": "alpha"}},
        {"id": "v", "type": "verdict", "config": {"decision": "conclusive", "action": "block"}},
    ],
    "edges": [{"src": "e", "dst": "r"}, {"src": "r", "dst": "v"}],
}


def _swap_pattern(pattern: str) -> dict:
    graph = {"nodes": [dict(n) for n in BLOCKING["nodes"]], "edges": BLOCKING["edges"]}
    graph["nodes"][1]["config"] = {"pattern": pattern}
    return graph


async def test_a_draft_is_not_compiled(client, app):
    """draft 는 운영에 영향이 없다 (§6)."""
    await client.post(BASE, json={"name": "live", "graph": BLOCKING})
    assert app.state.plans.get("live") is None


async def test_publishing_compiles_the_plan_before_responding(client, app):
    """발행이 200 을 돌려주면 그 워커에서는 이미 반영돼 있어야 한다.

    커밋 뒤에 재컴파일해야 하고(커밋 전이면 새 세션이 그 행을 못 본다), 그것이
    **응답 전에** 끝나야 한다. 조립 루트의 yield 정리 코드에 맡겼을 때는 FastAPI 가
    응답을 보낸 뒤에 돌려서, 실제 uvicorn 에서 발행 직후의 요청이 이전 계획을 봤다.

    이 테스트만으로는 그 차이를 못 본다 — ASGITransport 가 전체 ASGI 호출을
    기다려주기 때문이다. 그래서 서비스가 커밋·재컴파일 시점을 직접 갖는다.
    """
    await client.post(BASE, json={"name": "live", "graph": BLOCKING})
    await client.post(f"{BASE}/live/publish")

    plan = app.state.plans.get("live")
    assert plan is not None
    assert plan.version_number == 1
    assert plan.checkpoints == frozenset({"input"})


async def test_publish_returns_the_version_the_registry_holds(client, app):
    """응답의 versionNumber 와 레지스트리의 계획이 같아야 한다.

    한 단계 밀리면 저작자가 방금 발행한 것을 시험할 수 없다.
    """
    await client.post(BASE, json={"name": "live", "graph": BLOCKING})
    for expected in (1, 2, 3):
        if expected > 1:
            await client.put(f"{BASE}/live/draft", json={"graph": _swap_pattern(f"p{expected}")})
        response = await client.post(f"{BASE}/live/publish")
        assert response.json()["versionNumber"] == expected
        plan = app.state.plans.get("live")
        assert plan is not None
        assert plan.version_number == expected, "레지스트리가 한 단계 밀렸다"


async def test_republishing_swaps_the_plan(client, app):
    from gateway.application.plan.executor import Subject, execute
    from gateway.domain.models.guardrail import VerdictAction

    await client.post(BASE, json={"name": "live", "graph": BLOCKING})
    await client.post(f"{BASE}/live/publish")
    await client.put(f"{BASE}/live/draft", json={"graph": _swap_pattern("bravo")})
    await client.post(f"{BASE}/live/publish")

    plan = app.state.plans.get("live")
    assert plan is not None
    assert plan.version_number == 2

    program = plan.program_for("input")
    assert program is not None
    assert execute(program, Subject(text="bravo")).action is VerdictAction.BLOCK
    assert execute(program, Subject(text="alpha")).is_allow, "이전 버전이 남아 있다"


async def test_a_failed_publish_does_not_change_the_plan(client, app):
    """422 로 끝난 요청이 계획을 건드리면, 실패한 발행이 정책을 바꾼 셈이 된다."""
    await client.post(BASE, json={"name": "live", "graph": BLOCKING})
    await client.post(f"{BASE}/live/publish")

    r = await client.put(f"{BASE}/live/draft", json={"graph": CYCLIC})
    assert r.status_code == 422

    plan = app.state.plans.get("live")
    assert plan is not None
    assert plan.version_number == 1


async def test_updating_a_draft_does_not_recompile(client, app):
    await client.post(BASE, json={"name": "live", "graph": BLOCKING})
    await client.post(f"{BASE}/live/publish")
    before = app.state.plans.compiles

    await client.put(f"{BASE}/live/draft", json={"graph": _swap_pattern("bravo")})
    assert app.state.plans.compiles == before, "draft 수정이 재컴파일을 걸었다"
