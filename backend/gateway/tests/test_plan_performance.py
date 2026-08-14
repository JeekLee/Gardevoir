"""§11 의 성능 성질 — 회귀 감시.

절대값을 단정하지 않는다. 다른 하드웨어에서 깨지고, 그러면 아무도 못 믿는 테스트가
된다. 넉넉한 상한과 **비율** 만 본다 — 설계가 근거로 삼은 것은 비율이다:

- 컴파일된 계획이 그래프를 매번 걷는 것보다 훨씬 빠르다 (§11.4: 10배)
- 합친 regex 가 개별 실행보다 훨씬 빠르다 (§11.2)
- 겹치는 윈도우가 청크당 비용을 평탄하게 만든다 (§9)

실제 측정값은 설계 문서 §11 에 기록한다.
"""

import asyncio
import statistics
import time

import orjson
import pytest
import re2

from gateway.application.inspection.inspector import Inspector
from gateway.application.plan.compiler import compile_guardrail
from gateway.application.plan.execution_plan import RegexOne, RegexSet
from gateway.application.plan.executor import Subject, execute
from gateway.application.streaming.holdback import Holdback
from gateway.application.streaming.relay import StreamRelay
from gateway.contract import Mode
from gateway.domain.models.guardrail import (
    Decision,
    Edge,
    Guardrail,
    Node,
    NodeType,
    VerdictAction,
)

DOCUMENT = ("lorem ipsum dolor sit amet consectetur adipiscing elit " * 40)[:2000]


def _synthetic(pattern_count: int = 90, *, name: str = "bench") -> Guardrail:
    """§11.3 의 합성 코퍼스를 닮은 그래프.

    패턴 절반은 원본을 읽고(합쳐진다), 절반은 transform 출력을 읽는다(따로 합쳐진다).
    §11.4 가 91개 중 34/57 로 갈렸다고 한 구성이다.
    """
    nodes = [
        Node(id="e", type=NodeType.EXTRACT, config={"checkpoint": "input"}),
        Node(id="t", type=NodeType.TRANSFORM, config={"op": "lower"}),
    ]
    edges = [Edge("e", "t")]
    verdict_inputs = []

    for index in range(pattern_count):
        source = "e" if index % 2 == 0 else "t"
        node_id = f"r{index}"
        nodes.append(
            Node(
                id=node_id,
                type=NodeType.REGEX,
                config={"pattern": rf"needle{index}[0-9]{{3}}"},
            )
        )
        edges.append(Edge(source, node_id))
        verdict_inputs.append(node_id)

    nodes.append(
        Node(
            id="v",
            type=NodeType.VERDICT,
            config={"decision": Decision.CONCLUSIVE, "action": VerdictAction.BLOCK},
        )
    )
    edges.extend(Edge(node_id, "v") for node_id in verdict_inputs)

    return Guardrail(
        name=name, version="1", version_number=1, nodes=tuple(nodes), edges=tuple(edges)
    )


def _wide_unmergeable(per_checkpoint: int = 62) -> Guardrail:
    """§11.4 의 단위(명령 ~255개, 체크포인트 여러 곳)에 맞춘 최악 구성.

    regex 마다 자기 transform 출력을 읽게 해서 **합쳐지지 않도록** 만든다. 합침이
    잘 되는 그래프에서 재면 실행이 빨라 보이는 것이 당연하므로, 비교는 합침이
    도움이 되지 않는 쪽에서 해야 정직하다.
    """
    nodes: list[Node] = []
    edges: list[Edge] = []
    for checkpoint in ("input", "output"):
        prefix = checkpoint[0]
        nodes.append(
            Node(id=f"{prefix}e", type=NodeType.EXTRACT, config={"checkpoint": checkpoint})
        )
        verdict_inputs = []
        for index in range(per_checkpoint):
            transform_id = f"{prefix}t{index}"
            regex_id = f"{prefix}r{index}"
            nodes.append(Node(id=transform_id, type=NodeType.TRANSFORM, config={"op": "lower"}))
            nodes.append(
                Node(
                    id=regex_id,
                    type=NodeType.REGEX,
                    config={"pattern": rf"needle{index}[0-9]{{3}}"},
                )
            )
            edges.append(Edge(f"{prefix}e", transform_id))
            edges.append(Edge(transform_id, regex_id))
            verdict_inputs.append(regex_id)
        nodes.append(
            Node(
                id=f"{prefix}v",
                type=NodeType.VERDICT,
                config={"decision": "conclusive", "action": "block"},
            )
        )
        edges.extend(Edge(node_id, f"{prefix}v") for node_id in verdict_inputs)

    return Guardrail(
        name="wide", version="1", version_number=1, nodes=tuple(nodes), edges=tuple(edges)
    )


def _walk_the_graph(guardrail: Guardrail, text: str, verdict: str = "v") -> bool:
    """Dify 방식 — 요청마다 그래프를 걷고 노드를 해석한다 (§11.4 의 비교 대상).

    같은 결과를 내야 비교가 성립하므로, 컴파일러가 하는 일을 요청 시점에 한다:
    인접 구조 만들기, 위상 정렬, 패턴 컴파일, 노드별 실행.
    """
    nodes = {node.id: node for node in guardrail.nodes}
    inputs: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    outputs: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    for edge in guardrail.edges:
        inputs[edge.dst].append(edge.src)
        outputs[edge.src].append(edge.dst)

    indegree = {node_id: len(srcs) for node_id, srcs in inputs.items()}
    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    values: dict[str, object] = {}
    while ready:
        current = ready.pop()
        node = nodes[current]
        match node.type:
            case NodeType.EXTRACT:
                values[current] = text
            case NodeType.TRANSFORM:
                values[current] = str(values[inputs[current][0]]).lower()
            case NodeType.REGEX:
                # 계획이 없으므로 요청마다 컴파일한다 — 이것이 6.2 ms 의 출처다.
                values[current] = (
                    re2.compile(node.config["pattern"]).search(str(values[inputs[current][0]]))
                    is not None
                )
            case NodeType.LENGTH:
                values[current] = len(str(values[inputs[current][0]])) > node.config["max_chars"]
            case NodeType.VERDICT:
                values[current] = any(values[src] for src in inputs[current])
        for dst in outputs[current]:
            indegree[dst] -= 1
            if indegree[dst] == 0:
                ready.append(dst)
    return bool(values[verdict])


def _median_ms(fn, repeats: int = 21) -> float:
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    samples.sort()
    return samples[len(samples) // 2]


# --- 컴파일 ------------------------------------------------------------------


def test_compiling_one_plan_is_a_background_cost():
    """§11.3: 계획 1개 10.16 ms, 문법 검증을 저작 시점으로 옮기면 ~4.5 ms.

    요청 경로에 없으므로 사용자가 체감하는 것은 '발행 후 반영까지'뿐이다.
    """
    guardrail = _synthetic()
    elapsed = _median_ms(lambda: compile_guardrail(guardrail), repeats=11)
    print(f"\n  컴파일 1개 (패턴 90): {elapsed:.3f} ms")
    assert elapsed < 100, "발행이 배경 작업이라고 부를 수 없을 만큼 느려졌다"


def test_the_compiler_does_not_revalidate_node_syntax():
    """§11.3 의 최적화: 노드 검증이 컴파일 시간의 55% 였다.

    컴파일러가 문법을 다시 확인하면 잘못된 패턴에서 터진다. 터지지 않아야 한다 —
    저작 시점에 이미 걸렀다는 전제로 돌기 때문이다.
    """
    guardrail = Guardrail(
        name="unchecked",
        version="1",
        version_number=1,
        nodes=(
            Node(id="e", type=NodeType.EXTRACT, config={"checkpoint": "input"}),
            Node(id="l", type=NodeType.LENGTH, config={"max_chars": 10}),
            Node(
                id="v",
                type=NodeType.VERDICT,
                config={"decision": "conclusive", "action": "block"},
            ),
        ),
        edges=(Edge("e", "l"), Edge("l", "v")),
    )
    compile_guardrail(guardrail)  # validate() 를 부르지 않았는데도 통과해야 한다


def test_compiling_many_plans_scales_linearly():
    """§11.3: 전역 정책 변경 -> 50개 재컴파일 258 ms."""
    guardrails = [_synthetic(30, name=f"g{i}") for i in range(50)]
    start = time.perf_counter()
    for guardrail in guardrails:
        compile_guardrail(guardrail)
    elapsed = (time.perf_counter() - start) * 1000
    print(f"  컴파일 50개 (패턴 30씩): {elapsed:.1f} ms ({elapsed / 50:.3f} ms/개)")
    assert elapsed < 5000


# --- 실행 --------------------------------------------------------------------


def test_executing_a_plan_is_far_cheaper_than_walking_the_graph():
    """§11.4: 컴파일함 0.618 ms vs 매번 걷기 6.200 ms — 10배.

    설계가 자유 DAG 를 채택한 근거가 이 비율이다. '중요한 것은 자유도가 아니라
    컴파일 여부였다'가 뒤집히면 구조를 다시 봐야 한다.
    """
    guardrail = _synthetic()
    plan = compile_guardrail(guardrail)
    program = plan.program_for("input")
    assert program is not None

    # 같은 결과를 내는지 먼저 확인한다 — 아니면 비교가 무의미하다
    assert execute(program, Subject(text=DOCUMENT)).is_allow
    assert _walk_the_graph(guardrail, DOCUMENT) is False

    compiled = _median_ms(lambda: execute(program, Subject(text=DOCUMENT)), repeats=51)
    walked = _median_ms(lambda: _walk_the_graph(guardrail, DOCUMENT), repeats=51)
    ratio = walked / compiled
    print(f"  실행: 컴파일함 {compiled:.4f} ms / 매번 걷기 {walked:.4f} ms ({ratio:.1f}배)")

    assert compiled < 5, "요청당 예산(0.63 ms)에서 한참 벗어났다"
    assert walked > compiled * 3, "컴파일의 이득이 사라졌다 — §11.4 를 다시 재야 한다"


def test_a_matching_document_still_executes_fast():
    guardrail = _synthetic()
    program = compile_guardrail(guardrail).program_for("input")
    assert program is not None
    text = DOCUMENT + " needle10123"
    assert execute(program, Subject(text=text)).action is VerdictAction.BLOCK

    elapsed = _median_ms(lambda: execute(program, Subject(text=text)), repeats=51)
    print(f"  실행 (차단됨): {elapsed:.4f} ms")
    assert elapsed < 5


def test_the_plan_merges_regexes_into_two_sets():
    """구성이 §11.4 의 34/57 분할을 닮았는지 확인한다 — 성능 수치의 전제다."""
    program = compile_guardrail(_synthetic()).program_for("input")
    assert program is not None
    sets = [i for i in program.instructions if isinstance(i, RegexSet)]
    ones = [i for i in program.instructions if isinstance(i, RegexOne)]
    assert len(sets) == 2, "원본을 읽는 그룹과 transform 출력을 읽는 그룹"
    assert sum(len(s.outs) for s in sets) == 90
    assert ones == []


# --- regex 합침 --------------------------------------------------------------


@pytest.mark.parametrize("pattern_count", [200])
def test_a_regex_set_beats_running_patterns_individually(pattern_count):
    """§11.2: re2.Set 이 합침을 이미 구현해놨다."""
    patterns = [rf"needle{i}[0-9]{{3}}" for i in range(pattern_count)]

    matcher = re2.Set.SearchSet()
    for pattern in patterns:
        matcher.Add(pattern)
    matcher.Compile()
    compiled = [re2.compile(pattern) for pattern in patterns]

    one_pass = _median_ms(lambda: matcher.Match(DOCUMENT), repeats=51)
    looped = _median_ms(lambda: [c.search(DOCUMENT) for c in compiled], repeats=51)
    ratio = looped / one_pass
    print(f"  regex {pattern_count}개: Set {one_pass:.5f} / 개별 {looped:.5f} ms ({ratio:.0f}배)")

    assert looped > one_pass * 5, "합치는 이득이 사라졌다 — §11.2 를 다시 재야 한다"


# --- 메모리 ------------------------------------------------------------------


def test_a_plan_does_not_retain_the_source_graph():
    """§11.6 의 307 KB 는 명령이 원본 노드 dict 를 붙들어서 나온 값이다.

    크기를 단정하지 않는다 — 붙들지 '않는다'는 사실만 고정한다.
    """
    guardrail = _synthetic(10)
    plan = compile_guardrail(guardrail)
    program = plan.program_for("input")
    assert program is not None

    node_configs = {id(node.config) for node in guardrail.nodes}
    held = {
        id(getattr(instruction, name))
        for instruction in program.instructions
        for name in instruction.__slots__
    }
    assert not (held & node_configs)


def test_plan_memory_is_reported(capsys):
    """실측값을 문서에 옮기기 위한 출력. 단정하지 않는다."""
    import sys

    plan = compile_guardrail(_synthetic())
    program = plan.program_for("input")
    assert program is not None

    total = sys.getsizeof(plan) + sys.getsizeof(program) + sys.getsizeof(program.instructions)
    for instruction in program.instructions:
        total += sys.getsizeof(instruction)
        total += sum(sys.getsizeof(getattr(instruction, n)) for n in instruction.__slots__)
    count = len(program.instructions)
    print(f"  계획 1개 (명령 {count}개, 패턴 90): 약 {total / 1024:.1f} KB (오토마톤 제외)")


# --- §11.4 의 단위에 맞춘 비교 ------------------------------------------------


def test_a_request_sized_plan_stays_inside_the_budget():
    """§11.4 의 단위: 요청 1건, 체크포인트 여러 곳, 명령 ~255개.

    합침이 도움이 되지 않는 그래프로 잰다 — 합침이 잘 듣는 구성에서만 빠르면
    그 숫자는 설계 근거로 쓸 수 없다.
    """
    guardrail = _wide_unmergeable()
    plan = compile_guardrail(guardrail)
    print(f"\n  명령 수: {plan.instruction_count} (체크포인트 {sorted(plan.checkpoints)})")
    assert plan.instruction_count > 240, "§11.4 의 단위에 맞지 않는다"

    def one_request() -> None:
        for checkpoint in ("input", "output"):
            program = plan.program_for(checkpoint)
            assert program is not None
            execute(program, Subject(text=DOCUMENT))

    elapsed = _median_ms(one_request, repeats=51)
    print(f"  요청 1건 (명령 {plan.instruction_count}개, 체크포인트 2곳): {elapsed:.4f} ms")
    assert elapsed < 5, "요청당 예산(0.63 ms)에서 한참 벗어났다"


def test_a_request_sized_plan_beats_walking_the_graph():
    guardrail = _wide_unmergeable()
    plan = compile_guardrail(guardrail)

    def one_request() -> None:
        for checkpoint in ("input", "output"):
            program = plan.program_for(checkpoint)
            assert program is not None
            execute(program, Subject(text=DOCUMENT))

    def walked() -> None:
        _walk_the_graph(guardrail, DOCUMENT, verdict="iv")
        _walk_the_graph(guardrail, DOCUMENT, verdict="ov")

    compiled_ms = _median_ms(one_request, repeats=31)
    walked_ms = _median_ms(walked, repeats=31)
    ratio = walked_ms / compiled_ms
    print(f"  요청 1건: 컴파일함 {compiled_ms:.4f} / 걷기 {walked_ms:.4f} ms ({ratio:.1f}배)")
    assert walked_ms > compiled_ms * 3


def test_a_request_sized_plan_compiles_as_a_background_cost():
    guardrail = _wide_unmergeable()
    elapsed = _median_ms(lambda: compile_guardrail(guardrail), repeats=11)
    print(f"  컴파일 1개 (명령 ~250개): {elapsed:.3f} ms")
    assert elapsed < 100


# --- 스트리밍 (§9) ------------------------------------------------------------

#: 영어 62자. 청크 하나를 흉내내는 단위 — 실제 델타는 토큰 하나(~4자)지만, 그러면
#: 청크 수가 커져 측정 시간이 길어진다. 청크당 비용이 관심사이므로 단위는 무관하다.
STREAM_CHUNK = "The quarterly report shows steady growth across every region. "
STREAM_CHUNKS = 400
RRN = "900101-1234567"


class _StubRegistry:
    def __init__(self, plan):
        self._plan = plan

    def get(self, name):
        return self._plan


def _stream_setup(pattern_count: int = 90):
    """③ 계획(패턴 다수, BLOCK)과 그것을 물린 검사기 — 비용 측정용."""
    source = _synthetic(pattern_count, name="stream")
    guardrail = Guardrail(
        name="stream",
        version="1",
        version_number=1,
        nodes=tuple(
            Node(id="e", type=NodeType.EXTRACT, config={"checkpoint": "output"})
            if node.id == "e"
            else node
            for node in source.nodes
        ),
        edges=source.edges,
    )
    plan = compile_guardrail(guardrail)
    program = plan.program_for("output")
    assert program is not None
    return plan, program, Inspector(plans=_StubRegistry(plan))


def _mask_setup():
    """③ MASK 계획 — 구간을 돌려받아야 탐지 여부를 볼 수 있다.

    MASK 는 extract 를 직접 읽는 regex 에만 걸 수 있으므로 (컴파일러의 제약) 여기서는
    transform 을 끼우지 않는다.
    """
    guardrail = Guardrail(
        name="mask",
        version="1",
        version_number=1,
        nodes=(
            Node(id="e", type=NodeType.EXTRACT, config={"checkpoint": "output"}),
            Node(id="r", type=NodeType.REGEX, config={"pattern": r"\d{6}-\d{7}"}),
            Node(
                id="v",
                type=NodeType.VERDICT,
                config={"decision": "conclusive", "action": "mask"},
            ),
        ),
        edges=(Edge("e", "r"), Edge("r", "v")),
    )
    guardrail.validate()
    plan = compile_guardrail(guardrail)
    program = plan.program_for("output")
    assert program is not None
    return program, Inspector(plans=_StubRegistry(plan))


def _windowed_costs(program, inspector, *, window: int) -> list[float]:
    """§9 의 방식 — 직전 ``window`` 자 + 새 청크만 검사한다."""
    hold = Holdback(chars=128, window=window)
    costs = []
    for _ in range(STREAM_CHUNKS):
        hold.append(STREAM_CHUNK)
        start = time.perf_counter()
        text, _offset = hold.inspection_window()
        inspector.stream_text(program, text, mode=Mode.ENFORCE)
        costs.append((time.perf_counter() - start) * 1000)
        hold.release()
    return costs


def _whole_buffer_costs(program, inspector) -> list[float]:
    """윈도우가 막는 것 — 누적 전체를 매 청크마다 다시 스캔한다."""
    costs = []
    buffer = ""
    for _ in range(STREAM_CHUNKS):
        buffer += STREAM_CHUNK
        start = time.perf_counter()
        inspector.stream_text(program, buffer, mode=Mode.ENFORCE)
        costs.append((time.perf_counter() - start) * 1000)
    return costs


def _mean(costs: list[float]) -> float:
    return statistics.mean(costs)


def test_the_sliding_window_keeps_the_per_chunk_cost_flat():
    """§9 가 겹치는 윈도우를 쓰는 이유 — 누적 재스캔은 O(n²) 다.

    실측(§11.11): 윈도우는 청크당 0.005 ms 로 평탄하고, 누적 재스캔은 처음 50개
    0.006 ms 에서 마지막 50개 0.035 ms 로 5.4배 커진다. 스트림이 길어질수록 벌어지므로
    긴 응답에서 먼저 아프다.
    """
    _plan_obj, program, inspector = _stream_setup()
    windowed = _windowed_costs(program, inspector, window=512)
    whole = _whole_buffer_costs(program, inspector)

    windowed_growth = _mean(windowed[-50:]) / _mean(windowed[:50])
    whole_growth = _mean(whole[-50:]) / _mean(whole[:50])
    print(
        f"\n  청크당 (청크 {STREAM_CHUNKS}개, 누적 {STREAM_CHUNKS * len(STREAM_CHUNK)}자): "
        f"윈도우 {statistics.median(windowed):.4f} ms (증가 {windowed_growth:.2f}배) / "
        f"누적 재스캔 {statistics.median(whole):.4f} ms (증가 {whole_growth:.2f}배)"
    )
    print(f"  스트림 전체: 윈도우 {sum(windowed):.2f} ms / 누적 재스캔 {sum(whole):.2f} ms")

    assert windowed_growth < 2, "윈도우가 누적 길이에 끌려가고 있다 — 경계가 풀렸다"
    assert whole_growth > 2, "비교 대상이 자라지 않는다 — 이 측정은 근거가 못 된다"
    assert sum(windowed) < sum(whole), "윈도우의 이득이 사라졌다 — §9 를 다시 재야 한다"


def test_the_relay_cost_per_chunk_is_negligible_against_generation():
    """§9 결정 5: 청크마다 검사해도 생성 속도(50 tok/s = 20 ms/토큰) 대비 무해하다.

    실측(§11.11): SSE 파싱·합성까지 포함해 청크당 9.8 µs. 토큰 하나 만드는 시간의
    0.05% 다. 여기에는 홀드백 지연이 포함되지 않는다 — 그것은 별도 성질이다.
    """
    plan, _program, inspector = _stream_setup()

    def frame(**delta) -> bytes:
        return (
            b"data: "
            + orjson.dumps(
                {
                    "id": "c",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "gpt-4o",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                }
            )
            + b"\n\n"
        )

    raws = [
        frame(role="assistant"),
        *[frame(content=STREAM_CHUNK) for _ in range(STREAM_CHUNKS)],
        b'data: {"id":"c","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    async def upstream():
        for raw in raws:
            yield raw

    async def relay_once() -> float:
        relay = StreamRelay(
            inspector=inspector,
            plan=plan,
            mode=Mode.ENFORCE,
            tainted=False,
            payload={"messages": []},
            holdback_chars=128,
            window_chars=512,
        )
        async for _chunk in relay.relay(upstream()):
            pass
        return relay.outcome.processing_ms

    totals, inspections = [], []
    for _ in range(11):
        start = time.perf_counter()
        inspections.append(asyncio.run(relay_once()))
        totals.append((time.perf_counter() - start) * 1000)
    totals.sort()
    inspections.sort()
    total = totals[len(totals) // 2]
    inspection = inspections[len(inspections) // 2]
    print(
        f"  중계기 (청크 {STREAM_CHUNKS}개): 전체 {total:.2f} ms "
        f"({total / STREAM_CHUNKS * 1000:.1f} µs/청크), "
        f"검사만 {inspection:.2f} ms ({inspection / STREAM_CHUNKS * 1000:.1f} µs/청크)"
    )

    per_chunk_ms = total / STREAM_CHUNKS
    assert per_chunk_ms < 2, "청크당 비용이 토큰 생성 시간(20 ms)에 근접했다"


@pytest.mark.parametrize("chars", [0, 32, 128, 512])
def test_the_holdback_delay_is_exactly_its_size_in_characters(chars):
    """홀드백이 만드는 지연은 정확히 ``chars`` 자만큼의 생성 시간이다.

    §9 는 "홀드백 32토큰 / 50 tok/s = 640 ms" 라고 쓴다. 우리 단위는 문자이므로
    영어 ~4자/토큰을 대입해야 그 수가 나온다: 128자 = 32토큰 = 640 ms. 한국어는
    자당 토큰이 더 많아 같은 문자 수가 더 짧은 시간이 된다.
    """
    hold = Holdback(chars=chars, window=512)
    arrived = 0
    for _ in range(20):
        hold.append(STREAM_CHUNK)
        arrived += len(STREAM_CHUNK)
        hold.release()

    lag = arrived - hold.emitted
    print(
        f"  홀드백 {chars:>3}자: 지연 {lag:>3}자 (영어 4자/토큰·50 tok/s => {lag / 4 * 20:.0f} ms)"
    )
    assert lag == chars, "홀드백이 약속한 만큼 붙들고 있지 않다"


@pytest.mark.parametrize(
    ("window", "expected_prefix"),
    [(8, 8), (512, len(RRN) - 1)],
)
def test_the_window_bounds_what_a_split_pattern_can_hide(window, expected_prefix):
    """윈도우 크기가 곧 "경계 앞에 얼마나 놓을 수 있는가" 다.

    청크 A 가 패턴의 앞 p자로 끝나면, p <= window 일 때만 잡힌다. 실측(§11.11):
    윈도우 8자는 8자까지, 512자는 13자(=패턴 14자에서 가능한 최대 분할)까지 잡는다.
    기본 512자면 어떤 현실적인 패턴도 경계에 숨길 수 없다.
    """
    program, inspector = _mask_setup()

    def caught(prefix_len: int) -> bool:
        hold = Holdback(chars=128, window=window)
        found = False
        for piece in ("x" * 100 + RRN[:prefix_len], RRN[prefix_len:] + " 입니다"):
            hold.append(piece)
            text, _offset = hold.inspection_window()
            _verdict, spans = inspector.stream_text(program, text, mode=Mode.ENFORCE)
            found = found or bool(spans)
            hold.release()
        return found

    boundary = max((p for p in range(1, len(RRN)) if caught(p)), default=0)
    print(f"  윈도우 {window:>3}자: 경계 앞 조각 {boundary}자까지 잡는다 (패턴 {len(RRN)}자)")
    assert boundary == expected_prefix
