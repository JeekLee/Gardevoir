"""Guardrail graph -> ExecutionPlan (§6).

발행 시점과 기동 시점에만 돈다. 요청 경로에 없으므로 여기서는 명료함이 속도보다
우선이다 — 대신 산출물이 요청 경로에서 빨라야 한다.

**노드 문법 검증은 하지 않는다.** 저작 시점에 이미 했다. 발행 시점에 다시 하면
컴파일 시간의 절반을 낭비하고(§11.3), 발행이 문법 오류로 실패하게 된다(§6).
컴파일러는 ``Guardrail.validate()`` 를 통과한 그래프를 전제한다.
"""

from collections import defaultdict, deque

import re2

from gateway.application.plan.execution_plan import (
    ExecutionPlan,
    Extract,
    Instruction,
    Length,
    Program,
    RegexOne,
    RegexSet,
    Transform,
    Verdict,
)
from gateway.domain.exception.guardrail_error import GuardrailError
from gateway.domain.models.guardrail import (
    Decision,
    Guardrail,
    Node,
    NodeType,
    VerdictAction,
)

#: 미발행(draft) 계획의 버전 번호. 감사 로그가 "발행본이 아니다"를 구별할 수 있어야 한다.
UNPUBLISHED = 0

#: 조기 종료를 빠르게 하려면 싼 검사가 앞에 와야 한다 (§6 의 ⑨).
#: 위상 레벨 안에서만 재정렬하므로 의존성은 깨지지 않는다.
_COST = {
    NodeType.EXTRACT: 0,
    NodeType.LENGTH: 1,
    NodeType.TRANSFORM: 2,
    NodeType.REGEX: 3,
    NodeType.VERDICT: 4,
}


def compile_guardrail(guardrail: Guardrail) -> ExecutionPlan:
    graph = _Graph(guardrail)
    programs = {}
    for checkpoint, node_ids in graph.by_checkpoint().items():
        program = graph.build_program(checkpoint, node_ids)
        if not program.is_empty:
            programs[checkpoint] = program

    return ExecutionPlan(
        guardrail=guardrail.name,
        version_number=(
            guardrail.version_number if guardrail.version_number is not None else UNPUBLISHED
        ),
        programs=programs,
    )


class _Graph:
    """컴파일 중에만 존재하는 인접 구조. 산출물은 이것을 붙들지 않는다 (§11.6)."""

    def __init__(self, guardrail: Guardrail) -> None:
        self.nodes: dict[str, Node] = {node.id: node for node in guardrail.nodes}
        self.inputs: dict[str, list[str]] = defaultdict(list)
        self.outputs: dict[str, list[str]] = defaultdict(list)
        for edge in guardrail.edges:
            self.inputs[edge.dst].append(edge.src)
            self.outputs[edge.src].append(edge.dst)

    # -- ① 체크포인트별 분할 -------------------------------------------------

    def by_checkpoint(self) -> dict[str, set[str]]:
        """Group nodes by the checkpoint they descend from.

        ② 를 함께 한다: 한 노드가 서로 다른 체크포인트에서 도달되면 그 노드는 두 시점
        중 어디서도 평가할 수 없다. arity 때문에 regex/length/transform 은 입력이
        하나라 이런 일이 없고, verdict 만 해당된다.
        """
        reached: dict[str, set[str]] = defaultdict(set)
        for node in self.nodes.values():
            if node.type is not NodeType.EXTRACT:
                continue
            checkpoint = node.config["checkpoint"]
            for descendant in self._descendants(node.id):
                reached[descendant].add(checkpoint)

        grouped: dict[str, set[str]] = defaultdict(set)
        for node_id, checkpoints in reached.items():
            if len(checkpoints) > 1:
                GuardrailError.MIXED_CHECKPOINTS.raise_(
                    f"node {node_id!r} is reachable from {sorted(checkpoints)}",
                    details={"node_id": node_id, "checkpoints": sorted(checkpoints)},
                )
            grouped[next(iter(checkpoints))].add(node_id)
        return grouped

    def _descendants(self, start: str) -> set[str]:
        seen = {start}
        queue = deque([start])
        while queue:
            for nxt in self.outputs[queue.popleft()]:
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    # -- ③~⑧ ---------------------------------------------------------------

    def build_program(self, checkpoint: str, node_ids: set[str]) -> Program:
        live = self._prune(node_ids)
        if not live:
            return Program(instructions=(), slot_count=0)

        order = self._topological(live)
        # ⑤ 값을 만드는 노드에만 슬롯을 준다. verdict 는 슬롯에 쓰지 않으므로 자리를
        # 잡아두면 배열이 판정 개수만큼 쓸데없이 커진다.
        slots = {
            node_id: index
            for index, node_id in enumerate(
                n for n in order if self.nodes[n].type is not NodeType.VERDICT
            )
        }
        return Program(
            instructions=self._emit(order, slots, checkpoint),
            slot_count=len(slots),
        )

    def _prune(self, node_ids: set[str]) -> set[str]:
        """④ 판정에 닿지 않는 노드를 버린다.

        UI 에서 노드를 그려두고 연결하지 않은 상태가 흔하다. 실행해도 결과에 영향이
        없으므로 명령을 만들 이유가 없다.
        """
        verdicts = {
            node_id
            for node_id in node_ids
            if self.nodes[node_id].type is NodeType.VERDICT and self.inputs[node_id]
        }
        live: set[str] = set()
        queue = deque(verdicts)
        while queue:
            current = queue.popleft()
            if current in live:
                continue
            live.add(current)
            queue.extend(self.inputs[current])
        return live

    def _topological(self, live: set[str]) -> list[str]:
        """③ 위상 정렬 + ⑦ 레벨 안 비용순 재정렬.

        레벨(모든 선행 노드가 이미 처리된 시점) 단위로 처리하고, 레벨 안에서만
        비용순 정렬한다. 그래서 재정렬이 의존성을 깰 수 없다.
        """
        indegree = {node_id: 0 for node_id in live}
        for node_id in live:
            for src in self.inputs[node_id]:
                if src in live:
                    indegree[node_id] += 1

        ready = [node_id for node_id, degree in indegree.items() if degree == 0]
        order: list[str] = []
        while ready:
            # 비용 다음 id — id 를 넣어야 워커마다 같은 순서가 나온다 (§6: 독립 컴파일).
            ready.sort(key=lambda node_id: (_COST[self.nodes[node_id].type], node_id))
            level, ready = ready, []
            for node_id in level:
                order.append(node_id)
                for dst in self.outputs[node_id]:
                    if dst not in indegree:
                        continue
                    indegree[dst] -= 1
                    if indegree[dst] == 0:
                        ready.append(dst)
        return order

    def _emit(
        self, order: list[str], slots: dict[str, int], checkpoint: str
    ) -> tuple[Instruction, ...]:
        """⑤⑥⑧ 슬롯 배정 · regex 합침 · 명령 생성."""
        merged = self._merge_regexes(order, slots)
        instructions: list[Instruction] = []
        for node_id in order:
            node = self.nodes[node_id]
            if node.type is NodeType.REGEX and node_id in merged:
                # 합쳐진 그룹. 대표 위치에서 Set 하나만 내고 나머지는 자리만 차지한다.
                if (group := merged[node_id]) is not None:
                    instructions.append(group)
                continue
            instructions.append(self._instruction(node, slots, checkpoint))
        return tuple(instructions)

    def _merge_regexes(self, order: list[str], slots: dict[str, int]) -> dict[str, RegexSet | None]:
        """⑥ 같은 슬롯을 읽는 regex 를 하나의 re2.Set 으로.

        서로 다른 슬롯을 읽는 것을 합치면 결과가 뒤섞인다. 그룹 크기가 1이면 Set 을
        만들지 않는다 — re2.compile 이 더 싸다.

        슬롯 번호로 묶으므로, 상위 노드 출력을 읽는 regex 도 같은 노드를 읽으면
        자동으로 합쳐진다 (§11.4 가 v2 로 남겨둔 것이 구조상 공짜로 따라온다).
        """
        groups: dict[int, list[str]] = defaultdict(list)
        for node_id in order:
            if self.nodes[node_id].type is NodeType.REGEX:
                groups[slots[self.inputs[node_id][0]]].append(node_id)

        emitted: dict[str, RegexSet | None] = {}
        for src, members in groups.items():
            if len(members) == 1:
                continue  # RegexOne 로 낸다
            matcher = re2.Set.SearchSet()
            for node_id in members:
                matcher.Add(self.nodes[node_id].config["pattern"])
            matcher.Compile()
            instruction = RegexSet(
                outs=tuple(slots[node_id] for node_id in members),
                src=src,
                matcher=matcher,
            )
            # 첫 멤버 자리에서 한 번만 낸다. 나머지는 자리만 차지한다.
            emitted[members[0]] = instruction
            for node_id in members[1:]:
                emitted[node_id] = None
        return emitted

    def _instruction(self, node: Node, slots: dict[str, int], checkpoint: str) -> Instruction:
        match node.type:
            case NodeType.EXTRACT:
                return Extract(out=slots[node.id], checkpoint=checkpoint)
            case NodeType.TRANSFORM:
                return Transform(
                    out=slots[node.id],
                    src=slots[self.inputs[node.id][0]],
                    op=node.config["op"],
                )
            case NodeType.LENGTH:
                return Length(
                    out=slots[node.id],
                    src=slots[self.inputs[node.id][0]],
                    max_chars=node.config["max_chars"],
                )
            case NodeType.REGEX:
                return RegexOne(
                    out=slots[node.id],
                    src=slots[self.inputs[node.id][0]],
                    pattern=re2.compile(node.config["pattern"]),
                )
            case NodeType.VERDICT:
                return Verdict(
                    srcs=tuple(slots[src] for src in self.inputs[node.id] if src in slots),
                    decision=Decision(node.config["decision"]),
                    action=VerdictAction(node.config["action"]),
                    node_id=node.id,
                )
        raise AssertionError(f"unhandled node type {node.type!r}")  # pragma: no cover


__all__ = ["UNPUBLISHED", "compile_guardrail"]
