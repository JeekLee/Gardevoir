"""§11 의 성능 성질 — 회귀 감시.

절대값을 단정하지 않는다. 다른 하드웨어에서 깨지고, 그러면 아무도 못 믿는 테스트가
된다. 넉넉한 상한과 **비율** 만 본다 — 설계가 근거로 삼은 것은 비율이다:

- 컴파일된 계획이 그래프를 매번 걷는 것보다 훨씬 빠르다 (§11.4: 10배)
- 합친 regex 가 개별 실행보다 훨씬 빠르다 (§11.2)

실제 측정값은 설계 문서 §11 에 기록한다.
"""

import time

import pytest
import re2

from gateway.application.plan.compiler import compile_guardrail
from gateway.application.plan.execution_plan import RegexOne, RegexSet
from gateway.application.plan.executor import Subject, execute
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
