"""Compiled guardrail — the executable projection of a node graph (§6).

프로세스 메모리에만 존재한다. 비싼 부분(RE2 오토마톤)이 원리적으로 직렬화되지
않으므로 외부에 저장하지 않는다 (§11.5).

전부 ``slots=True`` 슬롯 dataclass 다. Pydantic 이면 요청당 검증이 붙어서 가드레일
전체 예산(0.63 ms)보다 비싸진다 (§11.8). 명령은 원본 노드 dict 를 붙들지 않고
필요한 필드만 복사한다 — §11.6 의 307 KB 가 그래서 나왔다.
"""

from dataclasses import dataclass, field

from gateway.guardrail.domain.models.guardrail import VerdictAction, VerdictCombine


@dataclass(frozen=True, slots=True)
class Extract:
    """Place one request/response text source in a slot."""

    out: int
    source: str


@dataclass(frozen=True, slots=True)
class ToolExtract:
    """Place one selected tool-call field in a slot."""

    out: int
    selector: str
    tools: frozenset[str]
    field: str


@dataclass(frozen=True, slots=True)
class Transform:
    out: int
    src: int
    op: str


@dataclass(frozen=True, slots=True)
class ModelCheck:
    """A model-tier check that produces PENDING during rule execution."""

    src: int
    out: int
    node_id: str


@dataclass(frozen=True, slots=True)
class Not:
    """Negate one boolean slot while preserving PENDING."""

    out: int
    src: int


@dataclass(frozen=True, slots=True)
class RegexOne:
    """패턴 하나. 그룹 크기가 1이면 Set 을 만들지 않는다 — re2.compile 이 더 싸다."""

    out: int
    src: int
    pattern: object


@dataclass(frozen=True, slots=True)
class RegexSet:
    """같은 슬롯을 읽는 패턴들을 1패스로 검사한다 (§11.2).

    ``outs[i]`` 가 ``matcher`` 에 i 번째로 등록된 패턴의 결과 슬롯이다.
    """

    outs: tuple[int, ...]
    src: int
    matcher: object


@dataclass(frozen=True, slots=True)
class Verdict:
    """A terminal decision that does not write to a slot.

    ``combine`` interprets multiple inputs as OR/AND. ``node_id`` identifies the
    decision in ``checks_fired``, the audit input for policy tuning (§4).
    """

    srcs: tuple[int, ...]
    action: VerdictAction
    combine: VerdictCombine
    node_id: str


type Instruction = (
    Extract | ToolExtract | Transform | ModelCheck | Not | RegexOne | RegexSet | Verdict
)


@dataclass(frozen=True, slots=True)
class Program:
    """한 체크포인트의 직선 명령 목록. 그래프를 걷지 않는다 (§6)."""

    instructions: tuple[Instruction, ...]
    slot_count: int

    #: 요청 경로에서 명령 전체를 다시 훑지 않도록 발행 시점에 고정한다.
    text_sources: frozenset[str] = field(default_factory=frozenset)
    tool_extracts: tuple[ToolExtract, ...] = ()

    #: regex 슬롯 -> 그 슬롯에 쓰는 패턴의 개별 컴파일 결과. **마스킹 전용이다.**
    #: 합쳐진 Set 은 어느 패턴이 걸렸는지만 알려주고 어디인지는 알려주지 않으므로,
    #: 가릴 위치를 찾으려면 그 패턴 하나를 다시 돌려야 한다. 판정 경로는 이것을
    #: 쓰지 않는다 — 마스킹이 실제로 걸릴 때만 비용을 낸다.
    patterns_by_slot: dict[int, object] = field(default_factory=dict)

    #: MASK 판정 node_id -> 그 판정이 읽는 슬롯들. 마스킹은 **걸린 판정이 읽는**
    #: 패턴만 적용해야 한다 — 계획의 모든 패턴을 돌리면 차단용 패턴까지 가려서
    #: 저작자가 쓰지 않은 정책이 된다.
    mask_slots: dict[str, tuple[int, ...]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.instructions


@dataclass(frozen=True, slots=True)
class ModelNodeSpec:
    """A model judgement specification assembled at publish time (§6⑦)."""

    node_id: str
    checkpoint: str
    policy: str
    action: VerdictAction
    strictness: str
    model_route: str


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """가드레일 하나의 컴파일 산출물.

    체크포인트별로 프로그램이 나뉘어 있다. ①입력은 업스트림 호출 전, ③출력은 후라서
    한 배열을 두 시점에 걸쳐 실행할 수 없다. 부수 효과로, 출력을 보지 않는 가드레일은
    ``program_for("output")`` 이 ``None`` 이어서 그 체크포인트를 통째로 건너뛴다.

    불변이다. 요청 하나는 시작할 때 잡은 계획을 끝까지 쓴다 — 입력을 v37, 출력을
    v38 로 검사하면 판정이 앞뒤가 안 맞고 나중에 재현이 불가능해진다 (§6).
    """

    guardrail: str
    version_number: int
    programs: dict[str, Program] = field(default_factory=dict)
    model_nodes: dict[str, ModelNodeSpec] = field(default_factory=dict)

    def program_for(self, checkpoint: str) -> Program | None:
        return self.programs.get(checkpoint)

    @property
    def checkpoints(self) -> frozenset[str]:
        """이 계획이 실제로 검사하는 체크포인트."""
        return frozenset(self.programs)

    @property
    def instruction_count(self) -> int:
        return sum(len(program.instructions) for program in self.programs.values())
