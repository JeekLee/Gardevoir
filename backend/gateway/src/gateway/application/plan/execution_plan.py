"""Compiled guardrail — the executable projection of a node graph (§6).

프로세스 메모리에만 존재한다. 비싼 부분(RE2 오토마톤)이 원리적으로 직렬화되지
않으므로 외부에 저장하지 않는다 (§11.5).

전부 ``slots=True`` 슬롯 dataclass 다. Pydantic 이면 요청당 검증이 붙어서 가드레일
전체 예산(0.63 ms)보다 비싸진다 (§11.8). 명령은 원본 노드 dict 를 붙들지 않고
필요한 필드만 복사한다 — §11.6 의 307 KB 가 그래서 나왔다.
"""

from dataclasses import dataclass, field

from gateway.domain.models.guardrail import Decision, VerdictAction


@dataclass(frozen=True, slots=True)
class Extract:
    """체크포인트 텍스트를 슬롯에 놓는다. 프로그램의 유일한 소스."""

    out: int
    checkpoint: str


@dataclass(frozen=True, slots=True)
class Transform:
    out: int
    src: int
    op: str


@dataclass(frozen=True, slots=True)
class Length:
    out: int
    src: int
    max_chars: int


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
    """결론. 슬롯에 쓰지 않는다 — 판정에는 bool 이 아니라 action 과 node_id 가 필요하다.

    ``srcs`` 가 여럿이면 OR 다. ``node_id`` 를 담는 이유: 감사 로그의 ``checks_fired``
    가 정책 튜닝의 유일한 입력이다 (§4).
    """

    srcs: tuple[int, ...]
    decision: Decision
    action: VerdictAction
    node_id: str


type Instruction = Extract | Transform | Length | RegexOne | RegexSet | Verdict


@dataclass(frozen=True, slots=True)
class Program:
    """한 체크포인트의 직선 명령 목록. 그래프를 걷지 않는다 (§6)."""

    instructions: tuple[Instruction, ...]
    slot_count: int

    #: regex 슬롯 -> 그 슬롯에 쓰는 패턴의 개별 컴파일 결과. **마스킹 전용이다.**
    #: 합쳐진 Set 은 어느 패턴이 걸렸는지만 알려주고 어디인지는 알려주지 않으므로,
    #: 가릴 위치를 찾으려면 그 패턴 하나를 다시 돌려야 한다. 판정 경로는 이것을
    #: 쓰지 않는다 — 마스킹이 실제로 걸릴 때만 비용을 낸다.
    patterns_by_slot: dict[int, object] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.instructions


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

    def program_for(self, checkpoint: str) -> Program | None:
        return self.programs.get(checkpoint)

    @property
    def checkpoints(self) -> frozenset[str]:
        """이 계획이 실제로 검사하는 체크포인트."""
        return frozenset(self.programs)

    @property
    def instruction_count(self) -> int:
        return sum(len(program.instructions) for program in self.programs.values())
