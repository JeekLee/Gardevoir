import httpx
import pytest_asyncio

from gateway.domain.models.api_key import Scope, generate_key, hash_key
from gateway.infrastructure.models.api_key import ApiKeyModel
from gateway.presentation.http.app import create_app
from shared_kernel.log import REQUEST_ID_HEADER

BASE = "/v1/admin/guardrails"


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


async def test_every_route_requires_the_admin_scope(app, proxy_key):
    """라우트 하나를 놓치면 그 하나로 전부 우회된다."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"authorization": f"Bearer {proxy_key}"},
    ) as c:
        calls = [
            c.post(BASE, json={"name": "x", "graph": _graph()}),
            c.get(BASE),
            c.get(f"{BASE}/x"),
            c.get(f"{BASE}/x/draft"),
            c.put(f"{BASE}/x/draft", json={"graph": _graph()}),
            c.post(f"{BASE}/x/publish"),
            c.get(f"{BASE}/x/versions/1"),
        ]
        for call in calls:
            r = await call
            assert r.status_code == 403, r.request.url


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
