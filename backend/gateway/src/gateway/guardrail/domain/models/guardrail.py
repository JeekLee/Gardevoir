"""Guardrail aggregate: one node graph.

Validation lives here because "the graph has no cycle", "an edge points at a real
node", and "a regex node's pattern compiles" are rules about the guardrail
itself, independent of storage or transport (§5). Putting them in a router or the
compiler would duplicate them.

Persistence-ignorant: no SQLAlchemy, no FastAPI.
"""

from collections import deque
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

import re2

from gateway.guardrail.domain.exceptions.guardrail_error import GuardrailError

DRAFT_VERSION = "draft"

#: §3 의 네 검사 지점. 감사 모듈의 Checkpoint 와 어긋나지 않는지는 테스트로
#: 고정한다 — 도메인이 감사 모듈을 임포트하면 의존 방향이 뒤집힌다.
VALID_CHECKPOINTS = frozenset({"input", "output", "tool_result", "tool_call"})
VALID_TRANSFORMS = frozenset({"lower", "strip"})

#: ④ 전용 노드가 붙을 수 있는 체크포인트. 다른 곳에서는 평가할 tool_call 이 없으므로
#: 아무 값이나 내면 조용히 통과한다 — 거부하는 편이 낫다.
CHECKPOINT_TOOL_CALL = "tool_call"

#: 출처 검사의 기본 임계값. "1"·"true"·"id" 같은 짧은 값은 툴 결과에 우연히 나타나므로
#: 임계값이 없으면 정상 호출이 전부 걸린다. 8 은 메일 주소·URL·경로를 잡는 값이다.
DEFAULT_PROVENANCE_MIN_LENGTH = 8

#: 이름은 URL 경로 조각이자 X-Gardevoir-Guardrail 헤더 값이고, API 키의
#: allowed_guardrails 와 문자열 비교된다. 세 자리 모두에서 모호하지 않아야 하므로
#: 슬러그로 제한한다. 프레젠테이션이 아니라 도메인에서 막는다 — CLI 든 라우터든
#: 같은 규칙을 받아야 한다.
#: RE2 는 \Z 를 모른다. fullmatch 로 고정한다.
NAME_PATTERN = re2.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")

#: 오류 details 에 되돌릴 이름의 최대 길이. 호출자가 보낸 것을 그대로 되비추지
#: 않는다 — 경로 조각은 몇 KB 일 수도 있다.
_NAME_ECHO_LIMIT = 64

#: arity 상한이 없다는 표시. sys.maxsize 를 쓰면 오류 메시지에 그 숫자가 나온다.
_MANY = -1


def require_valid_name(name: object) -> str:
    """Reject anything that is not a guardrail name.

    애그리거트를 만들지 않는 경로(조회·발행)도 이 함수를 거쳐야 한다. 그러지 않으면
    이름 규칙이 쓰기 경로에만 걸려서, 경로 조각이 그대로 DB 질의로 내려간다.
    """
    if not isinstance(name, str) or not NAME_PATTERN.fullmatch(name):
        GuardrailError.INVALID_NAME.raise_(details={"name": _echo(name)})
    return name


def _echo(name: object) -> str:
    """What an error may repeat back about a rejected name.

    잘라내고 제어문자를 지운다. 이 값은 응답 본문과 로그 양쪽에 실리므로, 호출자가
    보낸 것을 그대로 되비추면 안 된다 — 경로 조각은 몇 KB 일 수도 있고 NUL 을
    담을 수도 있다.
    """
    if not isinstance(name, str):
        return type(name).__name__
    return "".join(c for c in name[:_NAME_ECHO_LIMIT] if c.isprintable())


class NodeType(StrEnum):
    EXTRACT = "extract"
    REGEX = "regex"
    LENGTH = "length"
    TRANSFORM = "transform"
    VERDICT = "verdict"
    #: 대화에 외부 데이터(role:tool 결과)가 들어왔는가 (§8 1단계). 소스다.
    TAINT = "taint"
    #: 입력이 전부 참인가. VERDICT 의 여러 입력은 OR 이므로 AND 가 따로 필요하다 —
    #: §8 2단계가 "오염됨 AND 부작용 툴"이다.
    ALL = "all"
    #: 이 tool_call 이 부작용 툴인가 (§7.6). 목록에 없으면 부작용 있음 — 미등록 툴이
    #: 안전한 쪽으로 기본 처리된다.
    SIDE_EFFECT = "side_effect"
    #: 인수 값이 외부 데이터(툴 결과)에서 왔는가 (§8 3단계).
    PROVENANCE = "provenance"


class Decision(StrEnum):
    """규칙 티어의 역할. 설계 문서 §4 의 세 유형.

    CONCLUSIVE  규칙만으로 종료. 모델을 부르지 않는다.
    HINT        규칙에 걸리면 모델로 넘긴다.
    MODEL_ONLY  규칙 없이 항상 모델.
    """

    CONCLUSIVE = "conclusive"
    HINT = "hint"
    MODEL_ONLY = "model_only"


class VerdictAction(StrEnum):
    BLOCK = "block"
    MASK = "mask"
    ALLOW = "allow"


@dataclass(frozen=True, slots=True)
class Node:
    id: str
    type: NodeType
    config: dict

    def validate(self) -> None:
        validator = _NODE_VALIDATORS.get(self.type)
        if validator is None:
            self.fail(f"unknown node type {self.type!r}")
        validator(self)

    def fail(self, reason: str) -> None:
        """Raise with the node id attached so a UI can point at the node."""
        GuardrailError.INVALID_NODE_CONFIG.raise_(
            f"node {self.id!r}: {reason}", details={"node_id": self.id, "reason": reason}
        )


@dataclass(frozen=True, slots=True)
class Edge:
    src: str
    dst: str


@dataclass(frozen=True, slots=True)
class Guardrail:
    name: str
    version: str
    version_number: int | None
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    def __post_init__(self) -> None:
        require_valid_name(self.name)

    @classmethod
    def draft(cls, name: str, graph: dict) -> "Guardrail":
        return cls.from_graph(name=name, version=DRAFT_VERSION, version_number=None, graph=graph)

    @classmethod
    def from_graph(
        cls, *, name: str, version: str, version_number: int | None, graph: dict
    ) -> "Guardrail":
        """Build from the serialised graph.

        The domain owns this shape rather than the ORM mapper or a router, because
        both of those need it — and two parsers would drift. The input is
        untrusted (it comes off the wire), so malformed structure raises a domain
        error instead of a ``KeyError`` that would surface as a 500.
        """
        return cls(
            name=name,
            version=version,
            version_number=version_number,
            nodes=tuple(_parse_node(n) for n in _sequence(graph, "nodes")),
            edges=tuple(_parse_edge(e) for e in _sequence(graph, "edges")),
        )

    def to_graph(self) -> dict:
        """The serialised form. StrEnum is lowered to str so storage has one shape."""
        return {
            "nodes": [
                {"id": n.id, "type": str(n.type), "config": _plain(n.config)} for n in self.nodes
            ],
            "edges": [{"src": e.src, "dst": e.dst} for e in self.edges],
        }

    @property
    def is_draft(self) -> bool:
        return self.version == DRAFT_VERSION

    def validate(self) -> None:
        self._validate_node_ids()
        for node in self.nodes:
            node.validate()
        self._validate_edges()
        self._validate_acyclic()
        self._validate_arity()

    def published_as(self, version_number: int) -> "Guardrail":
        """Return a published copy. The draft itself is left editable (§6)."""
        if not self.is_draft:
            GuardrailError.PUBLISHED_IS_IMMUTABLE.raise_(
                details={"name": self.name, "version": self.version}
            )
        return replace(self, version=str(version_number), version_number=version_number)

    # -- validation ---------------------------------------------------------

    def _validate_node_ids(self) -> None:
        seen: set[str] = set()
        for node in self.nodes:
            if node.id in seen:
                GuardrailError.DUPLICATE_NODE_ID.raise_(details={"node_id": node.id})
            seen.add(node.id)

    def _validate_edges(self) -> None:
        ids = {node.id for node in self.nodes}
        for edge in self.edges:
            missing = [end for end in (edge.src, edge.dst) if end not in ids]
            if missing:
                GuardrailError.DANGLING_EDGE.raise_(
                    details={"edge": [edge.src, edge.dst], "missing": missing}
                )

    def _validate_arity(self) -> None:
        """How many inputs each node type may read.

        컴파일러가 "regex 는 읽을 슬롯이 정확히 하나"를 가정할 수 있어야 한다.
        여기(도메인)에 두는 이유: 컴파일 시점에 처음 터지면 발행이 문법 오류로
        실패하는데, §6 이 문법 검증을 저작 시점으로 옮긴 이유가 그것이다.

        나가는 엣지는 세지 않는다 — 한 extract 를 여러 체크가 읽는 전개는 정상이다.
        """
        incoming = dict.fromkeys((node.id for node in self.nodes), 0)
        for edge in self.edges:
            incoming[edge.dst] += 1

        for node in self.nodes:
            low, high = NODE_ARITY[node.type]
            count = incoming[node.id]
            if count >= low and (high == _MANY or count <= high):
                continue
            GuardrailError.INVALID_ARITY.raise_(
                f"node {node.id!r}: expected {_arity_text(low, high)} input(s), got {count}",
                details={
                    "node_id": node.id,
                    "inputs": count,
                    "expected": _arity_text(low, high),
                },
            )

    def _validate_acyclic(self) -> None:
        """Kahn's algorithm. A self-loop is a cycle too."""
        indegree = {node.id: 0 for node in self.nodes}
        adjacency: dict[str, list[str]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            adjacency[edge.src].append(edge.dst)
            indegree[edge.dst] += 1

        queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for neighbour in adjacency[current]:
                indegree[neighbour] -= 1
                if indegree[neighbour] == 0:
                    queue.append(neighbour)

        if visited != len(self.nodes):
            unresolved = sorted(node for node, degree in indegree.items() if degree > 0)
            GuardrailError.CYCLE.raise_(details={"nodes": unresolved})


#: 노드 타입별 허용 입력 개수 (최소, 최대). verdict 의 여러 입력은 OR 다.
NODE_ARITY: dict[NodeType, tuple[int, int]] = {
    NodeType.EXTRACT: (0, 0),
    NodeType.REGEX: (1, 1),
    NodeType.LENGTH: (1, 1),
    NodeType.TRANSFORM: (1, 1),
    NodeType.VERDICT: (1, _MANY),
    NodeType.TAINT: (0, 0),
    NodeType.SIDE_EFFECT: (0, 0),
    NodeType.PROVENANCE: (0, 0),
    #: 입력이 하나면 AND 가 무의미하다 — 저작자가 뭔가 잘못 그린 것이다.
    NodeType.ALL: (2, _MANY),
}


def _arity_text(low: int, high: int) -> str:
    if low == high:
        return str(low)
    if high == _MANY:
        return f"{low} or more"
    return f"{low}-{high}"


# -- serialised graph parsing -----------------------------------------------


def _sequence(graph: dict, key: str) -> list:
    if not isinstance(graph, dict):
        GuardrailError.MALFORMED_GRAPH.raise_(details={"reason": "graph must be an object"})
    value = graph.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        GuardrailError.MALFORMED_GRAPH.raise_(details={"reason": f"{key} must be an array"})
    return value


def _parse_node(raw: object) -> Node:
    if not isinstance(raw, dict):
        GuardrailError.MALFORMED_GRAPH.raise_(details={"reason": "each node must be an object"})
    node_id = raw.get("id")
    if not isinstance(node_id, str) or not node_id:
        GuardrailError.MALFORMED_GRAPH.raise_(
            details={"reason": "each node needs a non-empty string id"}
        )
    try:
        node_type = NodeType(raw.get("type"))
    except ValueError:
        GuardrailError.INVALID_NODE_CONFIG.raise_(
            f"node {node_id!r}: unknown type {raw.get('type')!r}",
            details={
                "node_id": node_id,
                "reason": f"type must be one of {sorted(t.value for t in NodeType)}",
            },
        )
    config = raw.get("config")
    if config is None:
        config = {}
    if not isinstance(config, dict):
        GuardrailError.INVALID_NODE_CONFIG.raise_(
            f"node {node_id!r}: config must be an object",
            details={"node_id": node_id, "reason": "config must be an object"},
        )
    _reject_nul_in_node(node_id, config)
    return Node(id=node_id, type=node_type, config=config)


def _parse_edge(raw: object) -> Edge:
    if not isinstance(raw, dict):
        GuardrailError.MALFORMED_GRAPH.raise_(details={"reason": "each edge must be an object"})
    src, dst = raw.get("src"), raw.get("dst")
    if not isinstance(src, str) or not isinstance(dst, str) or not src or not dst:
        GuardrailError.MALFORMED_GRAPH.raise_(
            details={"reason": "each edge needs non-empty string src and dst"}
        )
    return Edge(src=src, dst=dst)


def _reject_nul_in_node(node_id: str, value: Any) -> None:
    """NUL 은 정책 문자열에 쓸 일이 없고, 저장할 수도 없다.

    Postgres jsonb 는 \\u0000 을 담지 못해 INSERT 가 UntranslatableCharacter 로
    죽는다 — 즉 저작자에게 422 가 아니라 500 이 간다. 노드 id 는 슬러그가 아니라
    임의 문자열이므로 여기서 함께 막는다.
    """
    if "\x00" in node_id:
        GuardrailError.INVALID_NODE_CONFIG.raise_(
            "a node id may not contain a NUL character",
            details={"node_id": node_id.replace("\x00", ""), "reason": "NUL is not allowed"},
        )
    if _contains_nul(value):
        GuardrailError.INVALID_NODE_CONFIG.raise_(
            f"node {node_id!r}: config may not contain a NUL character",
            details={"node_id": node_id, "reason": "NUL is not allowed"},
        )


def _contains_nul(value: Any) -> bool:
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_contains_nul(k) or _contains_nul(v) for k, v in value.items())
    if isinstance(value, list | tuple):
        return any(_contains_nul(item) for item in value)
    return False


def _plain(value: Any) -> Any:
    """Strip StrEnum/IntEnum identity so the serialised graph has one representation."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return str(value)
    if isinstance(value, int):
        return int(value)
    return value


# -- per-type node validators -----------------------------------------------


def _validate_extract(node: Node) -> None:
    if node.config.get("checkpoint") not in VALID_CHECKPOINTS:
        node.fail(f"checkpoint must be one of {sorted(VALID_CHECKPOINTS)}")


def _validate_regex(node: Node) -> None:
    pattern = node.config.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        node.fail("pattern must be a non-empty string")
    try:
        # 저작 시점에 한 번만 확인한다. 발행 시점에 다시 하면 컴파일 시간의
        # 절반을 낭비한다 (§11.3).
        re2.compile(pattern)
    except Exception as exc:
        node.fail(f"pattern does not compile: {_reason(exc)}")


def _reason(exc: Exception) -> str:
    """re2 는 이유를 bytes 로 담아 올린다. b'...' 를 그대로 응답에 싣지 않는다."""
    arg = exc.args[0] if exc.args else exc
    return arg.decode(errors="replace") if isinstance(arg, bytes) else str(arg)


def _validate_length(node: Node) -> None:
    max_chars = node.config.get("max_chars")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        node.fail("max_chars must be a positive integer")


def _validate_transform(node: Node) -> None:
    if node.config.get("op") not in VALID_TRANSFORMS:
        node.fail(f"op must be one of {sorted(VALID_TRANSFORMS)}")


def _validate_verdict(node: Node) -> None:
    if node.config.get("decision") not in set(Decision):
        node.fail(f"decision must be one of {sorted(d.value for d in Decision)}")
    if node.config.get("action") not in set(VerdictAction):
        node.fail(f"action must be one of {sorted(a.value for a in VerdictAction)}")


def _validate_taint(node: Node) -> None:
    """extract 와 같은 규칙으로 체크포인트를 요구한다.

    오염 여부는 대화 전체의 성질이라 체크포인트와 무관한 값이지만, 컴파일러가
    부분 그래프를 소스의 체크포인트로 나누므로 어디서 실행할지는 명시돼야 한다.
    """
    if node.config.get("checkpoint") not in VALID_CHECKPOINTS:
        node.fail(f"checkpoint must be one of {sorted(VALID_CHECKPOINTS)}")


def _validate_all(node: Node) -> None:
    """설정이 없다. 입력 개수는 arity 가 본다."""


def _require_tool_call(node: Node) -> None:
    if node.config.get("checkpoint") != CHECKPOINT_TOOL_CALL:
        GuardrailError.WRONG_CHECKPOINT.raise_(
            f"node {node.id!r}: {node.type} only works at the {CHECKPOINT_TOOL_CALL!r} checkpoint",
            details={
                "node_id": node.id,
                "type": str(node.type),
                "checkpoint": CHECKPOINT_TOOL_CALL,
            },
        )


def _validate_side_effect(node: Node) -> None:
    """``read_only`` 목록에 없는 툴은 부작용 있음이다 (§7.6).

    부작용 툴을 따로 나열하지 않는다. 목록이 둘이면 어느 쪽에도 없는 툴의 처리가 설정
    실수에 달리게 된다 — 안전한 기본값은 정책 선택이 아니라 구조여야 한다.
    """
    _require_tool_call(node)
    read_only = node.config.get("read_only", [])
    if not isinstance(read_only, list) or not all(isinstance(name, str) for name in read_only):
        node.fail("read_only must be a list of tool names")


def _validate_provenance(node: Node) -> None:
    _require_tool_call(node)
    if "min_length" not in node.config:
        return
    min_length = node.config["min_length"]
    if isinstance(min_length, bool) or not isinstance(min_length, int) or min_length <= 0:
        node.fail("min_length must be a positive integer")


_NODE_VALIDATORS = {
    NodeType.EXTRACT: _validate_extract,
    NodeType.REGEX: _validate_regex,
    NodeType.LENGTH: _validate_length,
    NodeType.TRANSFORM: _validate_transform,
    NodeType.VERDICT: _validate_verdict,
    NodeType.TAINT: _validate_taint,
    NodeType.ALL: _validate_all,
    NodeType.SIDE_EFFECT: _validate_side_effect,
    NodeType.PROVENANCE: _validate_provenance,
}
