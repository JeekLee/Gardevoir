"""계획 레지스트리 — 원자적 교체와 폴링 (§6).

소스는 스텁이다. DB 어댑터는 test_guardrail_source.py 가 본다.
"""

import asyncio
import time

import pytest

from gateway.application.plan.executor import Subject, execute
from gateway.application.plan.registry import PlanRegistry
from gateway.domain.models.guardrail import Edge, Guardrail, Node, NodeType, VerdictAction


def _guardrail(name: str, version_number: int, *, pattern: str = "alpha") -> Guardrail:
    return Guardrail(
        name=name,
        version=str(version_number),
        version_number=version_number,
        nodes=(
            Node(id="e", type=NodeType.EXTRACT, config={"checkpoint": "input"}),
            Node(id="r", type=NodeType.REGEX, config={"pattern": pattern}),
            Node(
                id="v",
                type=NodeType.VERDICT,
                config={"decision": "conclusive", "action": "block"},
            ),
        ),
        edges=(Edge("e", "r"), Edge("r", "v")),
    )


class StubSource:
    def __init__(self, guardrails: list[Guardrail] | None = None) -> None:
        #: (name, version_number) -> Guardrail
        self.published: dict[tuple[str, int], Guardrail] = {}
        for guardrail in guardrails or []:
            self.publish(guardrail)
        self.version_calls = 0
        self.load_calls = 0
        self.fail_versions = False
        #: 폴러가 한 바퀴 시작할 때마다 켜진다. 테스트가 sleep 대신 이것을 기다린다.
        self.polled = asyncio.Event()

    def publish(self, guardrail: Guardrail) -> None:
        assert guardrail.version_number is not None
        self.published[(guardrail.name, guardrail.version_number)] = guardrail

    async def latest_versions(self) -> dict[str, int]:
        self.version_calls += 1
        self.polled.set()
        if self.fail_versions:
            raise RuntimeError("source is down")
        latest: dict[str, int] = {}
        for name, version_number in self.published:
            latest[name] = max(latest.get(name, 0), version_number)
        return latest

    async def load_published(self, name: str, version_number: int) -> Guardrail | None:
        self.load_calls += 1
        return self.published.get((name, version_number))


def _registry(source: StubSource, **kw) -> PlanRegistry:
    return PlanRegistry(source=source, **kw)


async def _wait_for_cycles(source: StubSource, cycles: int = 2) -> None:
    """폴링 주기가 ``cycles`` 번 시작되기를 기다린다.

    이벤트가 주기 *시작* 에 켜지므로, N+1 번째 시작은 N 번째가 끝났다는 뜻이다.
    그래서 "재컴파일이 끝났는지"를 확인하려면 두 번 기다려야 한다.
    """
    for _ in range(cycles):
        source.polled.clear()
        await asyncio.wait_for(source.polled.wait(), timeout=5)


# --- 조회 -------------------------------------------------------------------


async def test_get_returns_none_for_an_unknown_guardrail():
    assert _registry(StubSource()).get("nope") is None


async def test_load_all_compiles_every_published_guardrail():
    source = StubSource([_guardrail("a", 1), _guardrail("b", 1)])
    registry = _registry(source)
    assert await registry.load_all() == 2
    assert registry.loaded == frozenset({"a", "b"})


async def test_load_all_takes_the_latest_version():
    source = StubSource([_guardrail("a", 1), _guardrail("a", 2)])
    registry = _registry(source)
    await registry.load_all()
    plan = registry.get("a")
    assert plan is not None
    assert plan.version_number == 2


async def test_load_all_skips_a_guardrail_with_only_a_draft():
    """draft 는 운영에 영향이 없다 (§6). 컴파일하면 미발행 정책이 적용된다."""
    registry = _registry(StubSource())
    assert await registry.load_all() == 0
    assert registry.loaded == frozenset()


async def test_get_does_not_touch_the_source():
    """요청 경로에 DB 0회 (§6). dict 조회 한 번이어야 한다."""
    source = StubSource([_guardrail("a", 1)])
    registry = _registry(source)
    await registry.load_all()

    before = (source.version_calls, source.load_calls)
    for _ in range(100):
        registry.get("a")
        registry.get("missing")
    assert (source.version_calls, source.load_calls) == before


# --- 교체 -------------------------------------------------------------------


async def test_refresh_swaps_in_the_new_version():
    source = StubSource([_guardrail("a", 1, pattern="alpha")])
    registry = _registry(source)
    await registry.load_all()

    source.publish(_guardrail("a", 2, pattern="bravo"))
    await registry.refresh("a")

    plan = registry.get("a")
    assert plan is not None
    assert plan.version_number == 2
    program = plan.program_for("input")
    assert program is not None
    assert execute(program, Subject(text="bravo")).action is VerdictAction.BLOCK
    assert execute(program, Subject(text="alpha")).is_allow


async def test_a_held_plan_is_unaffected_by_a_swap():
    """요청 하나는 시작할 때 잡은 계획을 끝까지 쓴다 (§6).

    이 성질이 깨지면 입력을 v1, 출력을 v2 로 검사해서 판정이 앞뒤가 안 맞고 나중에
    재현이 불가능해진다.
    """
    source = StubSource([_guardrail("a", 1, pattern="alpha")])
    registry = _registry(source)
    await registry.load_all()

    held = registry.get("a")
    assert held is not None

    source.publish(_guardrail("a", 2, pattern="bravo"))
    await registry.refresh("a")

    assert held.version_number == 1
    program = held.program_for("input")
    assert program is not None
    assert execute(program, Subject(text="alpha")).action is VerdictAction.BLOCK


async def test_refresh_is_a_noop_for_an_unknown_name():
    registry = _registry(StubSource())
    assert await registry.refresh("nope") is None
    assert registry.loaded == frozenset()


async def test_refresh_does_not_recompile_an_unchanged_version():
    source = StubSource([_guardrail("a", 1)])
    registry = _registry(source)
    await registry.load_all()

    before = registry.compiles
    await registry.refresh("a")
    assert registry.compiles == before


async def test_a_compile_failure_keeps_the_previous_plan():
    """잘못된 발행 하나가 가드레일 해제와 같아서는 안 된다."""
    source = StubSource([_guardrail("a", 1, pattern="alpha")])
    registry = _registry(source)
    await registry.load_all()

    broken = Guardrail(
        name="a",
        version="2",
        version_number=2,
        nodes=(
            Node(id="ei", type=NodeType.EXTRACT, config={"checkpoint": "input"}),
            Node(id="eo", type=NodeType.EXTRACT, config={"checkpoint": "output"}),
            Node(id="ri", type=NodeType.REGEX, config={"pattern": "x"}),
            Node(id="ro", type=NodeType.REGEX, config={"pattern": "y"}),
            Node(
                id="v",
                type=NodeType.VERDICT,
                config={"decision": "conclusive", "action": "block"},
            ),
        ),
        # 체크포인트를 섞은 verdict — 컴파일러가 거부한다
        edges=(Edge("ei", "ri"), Edge("eo", "ro"), Edge("ri", "v"), Edge("ro", "v")),
    )
    source.publish(broken)
    assert await registry.refresh("a") is None

    plan = registry.get("a")
    assert plan is not None
    assert plan.version_number == 1, "깨진 발행이 운영 중인 계획을 날렸다"


async def test_a_vanished_guardrail_keeps_the_previous_plan():
    """번호를 읽은 뒤 행이 사라질 수 있다."""
    source = StubSource([_guardrail("a", 1)])
    registry = _registry(source)
    await registry.load_all()

    source.published[("a", 2)] = None  # type: ignore[assignment]
    assert await registry.refresh("a") is None
    plan = registry.get("a")
    assert plan is not None
    assert plan.version_number == 1


# --- 폴러 -------------------------------------------------------------------


async def test_the_poller_picks_up_a_new_publish():
    source = StubSource([_guardrail("a", 1, pattern="alpha")])
    registry = _registry(source, poll_interval_s=0.01)
    await registry.load_all()
    await registry.start()
    try:
        source.publish(_guardrail("a", 2, pattern="bravo"))
        await _wait_for_cycles(source)
    finally:
        await registry.stop()

    plan = registry.get("a")
    assert plan is not None
    assert plan.version_number == 2


async def test_the_poller_ignores_an_unchanged_version():
    source = StubSource([_guardrail("a", 1)])
    registry = _registry(source, poll_interval_s=0.01)
    await registry.load_all()
    before = registry.compiles

    await registry.start()
    try:
        await _wait_for_cycles(source, 3)
    finally:
        await registry.stop()

    assert registry.compiles == before, "바뀌지 않았는데 다시 컴파일했다"


async def test_the_poller_survives_a_source_failure():
    """예외로 루프가 죽으면 그 워커는 영원히 낡은 계획을 쓴다 — 조용히 낡는다."""
    source = StubSource([_guardrail("a", 1)])
    registry = _registry(source, poll_interval_s=0.01)
    await registry.load_all()

    source.fail_versions = True
    await registry.start()
    try:
        await _wait_for_cycles(source, 3)

        source.fail_versions = False
        source.publish(_guardrail("a", 2))
        await _wait_for_cycles(source)
    finally:
        await registry.stop()

    plan = registry.get("a")
    assert plan is not None
    assert plan.version_number == 2, "실패 후 루프가 회복되지 않았다"


async def test_the_poller_does_not_block_the_event_loop():
    """컴파일이 동기이므로 폴링 주기마다 프록시 지연이 튈 수 있다.

    1c 의 ClickHouse 싱크에서 같은 함정을 겪었다. 반복 횟수가 아니라 동시에 돌리는
    ticker 의 벽시계로 잰다 — 막힌 루프도 늦게나마 반복은 끝낸다.
    """
    source = StubSource([_guardrail(f"g{i}", 1) for i in range(30)])
    registry = _registry(source, poll_interval_s=0.01)

    gaps: list[float] = []

    async def ticker() -> None:
        previous = time.perf_counter()
        for _ in range(60):
            await asyncio.sleep(0.005)
            now = time.perf_counter()
            gaps.append(now - previous)
            previous = now

    await registry.start()
    try:
        await ticker()
    finally:
        await registry.stop()

    assert max(gaps) < 0.2, f"이벤트 루프가 {max(gaps) * 1000:.0f} ms 막혔다"


async def test_stop_is_idempotent():
    registry = _registry(StubSource())
    await registry.start()
    await registry.stop()
    await registry.stop()


async def test_start_twice_runs_one_poller():
    source = StubSource([_guardrail("a", 1)])
    registry = _registry(source, poll_interval_s=0.01)
    await registry.start()
    await registry.start()
    try:
        await _wait_for_cycles(source, 3)
    finally:
        await registry.stop()
    # 폴러가 둘이면 stop 뒤에도 호출이 계속 늘어난다
    settled = source.version_calls
    await asyncio.sleep(0.05)
    assert source.version_calls == settled


async def test_stop_without_start_is_fine():
    await _registry(StubSource()).stop()


@pytest.mark.parametrize("interval", [0.01, 0.02])
async def test_the_poller_keeps_running_across_cycles(interval):
    source = StubSource([_guardrail("a", 1)])
    registry = _registry(source, poll_interval_s=interval)
    await registry.start()
    try:
        await _wait_for_cycles(source, 3)
    finally:
        await registry.stop()
    assert source.version_calls >= 3
