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
MAX_DESCRIPTION_LENGTH = 2000

#: §3 의 네 검사 지점. 감사 모듈의 Checkpoint 와 어긋나지 않는지는 테스트로
#: 고정한다 — 도메인이 감사 모듈을 임포트하면 의존 방향이 뒤집힌다.
VALID_CHECKPOINTS = frozenset({"input", "output", "tool_result", "tool_call"})
VALID_TRANSFORMS = frozenset({"lower", "strip"})
VALID_MODEL_STRICTNESSES = frozenset({"strict", "balanced", "lenient"})
DEFAULT_MODEL_STRICTNESS = "strict"

EXTRACT_SOURCE_USER_TEXT = "user_text"
EXTRACT_SOURCE_TOOL_RESULT = "tool_result"
EXTRACT_SOURCE_TRUSTED_TEXT = "trusted_text"
EXTRACT_SOURCE_OUTPUT_TEXT = "output_text"
VALID_EXTRACT_SOURCES = frozenset(
    {
        EXTRACT_SOURCE_USER_TEXT,
        EXTRACT_SOURCE_TOOL_RESULT,
        EXTRACT_SOURCE_TRUSTED_TEXT,
        EXTRACT_SOURCE_OUTPUT_TEXT,
    }
)

TOOL_SELECTOR_EXCLUDE = "exclude"
TOOL_SELECTOR_INCLUDE = "include"
VALID_TOOL_SELECTORS = frozenset({TOOL_SELECTOR_EXCLUDE, TOOL_SELECTOR_INCLUDE})

#: tool_extract 가 고정되는 체크포인트. 다른 곳에서는 평가할 tool_call 이 없다.
CHECKPOINT_TOOL_CALL = "tool_call"

# 기존 extract 저장 형식은 checkpoint 하나가 from과 at을 함께 뜻했다.
# 콘솔 2단계가 배포되기 전까지 이 형식을 읽어야 저장 API가 깨지지 않는다.
_LEGACY_EXTRACT_SOURCES = {
    "input": EXTRACT_SOURCE_USER_TEXT,
    "tool_result": EXTRACT_SOURCE_TOOL_RESULT,
    "output": EXTRACT_SOURCE_OUTPUT_TEXT,
}

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
    TOOL_EXTRACT = "tool_extract"
    REGEX = "regex"
    MODEL = "model"
    NOT = "not"
    TRANSFORM = "transform"
    VERDICT = "verdict"


class VerdictAction(StrEnum):
    BLOCK = "block"
    MASK = "mask"
    ALLOW = "allow"


class VerdictCombine(StrEnum):
    ANY = "any"
    ALL = "all"


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


def extract_source(node: Node) -> str:
    """Return the text source selected by an extract node."""
    if "from" in node.config:
        return node.config["from"]
    return _LEGACY_EXTRACT_SOURCES[node.config["checkpoint"]]


def source_at(node: Node) -> str:
    """Return the checkpoint that owns a source node's partial graph."""
    if node.type is NodeType.TOOL_EXTRACT:
        return CHECKPOINT_TOOL_CALL
    return node.config.get("at", node.config.get("checkpoint"))


def tool_selector(node: Node) -> tuple[str, frozenset[str]]:
    """Return the validated tool selector, defaulting to fail-safe exclusion."""
    tools = node.config.get("tools") or {}
    if not tools:
        return TOOL_SELECTOR_EXCLUDE, frozenset()
    mode = next(iter(tools))
    return mode, frozenset(tools[mode])


@dataclass(frozen=True, slots=True)
class Edge:
    src: str
    dst: str


@dataclass(frozen=True, slots=True)
class Guardrail:
    name: str
    version: str
    version_number: int | None
    description: str
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]

    def __post_init__(self) -> None:
        require_valid_name(self.name)
        if not isinstance(self.description, str):
            GuardrailError.INVALID_DESCRIPTION.raise_(
                details={"reason": "description must be a string"}
            )
        if _contains_nul(self.description):
            GuardrailError.INVALID_DESCRIPTION.raise_(details={"reason": "NUL is not allowed"})
        if len(self.description) > MAX_DESCRIPTION_LENGTH:
            GuardrailError.INVALID_DESCRIPTION.raise_(
                details={
                    "reason": f"description must be at most {MAX_DESCRIPTION_LENGTH} characters",
                    "max_length": MAX_DESCRIPTION_LENGTH,
                }
            )

    @classmethod
    def draft(cls, *, name: str, description: str, graph: dict) -> Guardrail:
        return cls.from_graph(
            name=name,
            version=DRAFT_VERSION,
            version_number=None,
            description=description,
            graph=graph,
        )

    @classmethod
    def from_graph(
        cls,
        *,
        name: str,
        version: str,
        version_number: int | None,
        description: str,
        graph: dict,
    ) -> Guardrail:
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
            description=description,
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
        self._validate_model_verdict_actions()

    def published_as(self, version_number: int) -> Guardrail:
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

    def _validate_model_verdict_actions(self) -> None:
        """Reject MASK verdicts influenced by MODEL checks."""
        inputs: dict[str, list[str]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            inputs[edge.dst].append(edge.src)

        for verdict in self.nodes:
            if verdict.type is not NodeType.VERDICT:
                continue
            if VerdictAction(verdict.config["action"]) is not VerdictAction.MASK:
                continue

            ancestors: set[str] = set()
            queue = deque(inputs[verdict.id])
            while queue:
                node_id = queue.popleft()
                if node_id in ancestors:
                    continue
                ancestors.add(node_id)
                queue.extend(inputs[node_id])

            model_ids = [
                node.id
                for node in self.nodes
                if node.type is NodeType.MODEL and node.id in ancestors
            ]
            if model_ids:
                GuardrailError.MODEL_CHECK_CANNOT_MASK.raise_(
                    details={"node_id": verdict.id, "model_nodes": model_ids}
                )


#: 노드 타입별 허용 입력 개수 (최소, 최대).
NODE_ARITY: dict[NodeType, tuple[int, int]] = {
    NodeType.EXTRACT: (0, 0),
    NodeType.TOOL_EXTRACT: (0, 0),
    NodeType.REGEX: (1, 1),
    NodeType.MODEL: (1, 1),
    NodeType.NOT: (1, 1),
    NodeType.TRANSFORM: (1, 1),
    NodeType.VERDICT: (1, _MANY),
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
    canonical = "from" in node.config or "at" in node.config
    legacy = "checkpoint" in node.config
    if canonical and legacy:
        node.fail("use from/at or the legacy checkpoint, not both")
    if legacy:
        checkpoint = node.config.get("checkpoint")
        if checkpoint not in _LEGACY_EXTRACT_SOURCES:
            node.fail(
                "legacy checkpoint must be one of "
                f"{sorted(_LEGACY_EXTRACT_SOURCES)}; use tool_extract for tool_call"
            )
        return
    if node.config.get("from") not in VALID_EXTRACT_SOURCES:
        node.fail(f"from must be one of {sorted(VALID_EXTRACT_SOURCES)}")
    if node.config.get("at") not in VALID_CHECKPOINTS:
        node.fail(f"at must be one of {sorted(VALID_CHECKPOINTS)}")


def _validate_tool_extract(node: Node) -> None:
    configured_at = node.config.get("at", node.config.get("checkpoint", CHECKPOINT_TOOL_CALL))
    if configured_at != CHECKPOINT_TOOL_CALL:
        GuardrailError.WRONG_CHECKPOINT.raise_(
            f"node {node.id!r}: {node.type} only works at the {CHECKPOINT_TOOL_CALL!r} checkpoint",
            details={
                "node_id": node.id,
                "type": str(node.type),
                "checkpoint": CHECKPOINT_TOOL_CALL,
            },
        )
    if "at" in node.config and "checkpoint" in node.config:
        node.fail("use at or checkpoint, not both")

    tools = node.config.get("tools")
    if tools is not None:
        if not isinstance(tools, dict):
            node.fail("tools must be an object with exclude or include")
        keys = set(tools)
        if keys and (len(keys) != 1 or not keys <= VALID_TOOL_SELECTORS):
            node.fail("tools must contain exactly one of exclude or include")
        if keys:
            names = tools[next(iter(keys))]
            if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
                node.fail("the tool selector must be a list of tool names")

    field = node.config.get("field")
    if not isinstance(field, str) or not field:
        node.fail("field must be name, arguments, or a non-empty argument path")


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


def _validate_model(node: Node) -> None:
    policy = node.config.get("policy")
    if not isinstance(policy, str) or not policy.strip():
        node.fail("policy must be a non-empty string")
    if node.config.get("checkpoint") not in VALID_CHECKPOINTS:
        node.fail(f"checkpoint must be one of {sorted(VALID_CHECKPOINTS)}")
    strictness = node.config.get("strictness")
    if strictness is not None and strictness not in VALID_MODEL_STRICTNESSES:
        node.fail(f"strictness must be one of {sorted(VALID_MODEL_STRICTNESSES)}")


def _reason(exc: Exception) -> str:
    """re2 는 이유를 bytes 로 담아 올린다. b'...' 를 그대로 응답에 싣지 않는다."""
    arg = exc.args[0] if exc.args else exc
    return arg.decode(errors="replace") if isinstance(arg, bytes) else str(arg)


def _validate_transform(node: Node) -> None:
    if node.config.get("op") not in VALID_TRANSFORMS:
        node.fail(f"op must be one of {sorted(VALID_TRANSFORMS)}")


def _validate_not(node: Node) -> None:
    if node.config:
        node.fail("not does not take configuration")


def _validate_verdict(node: Node) -> None:
    if node.config.get("action") not in set(VerdictAction):
        node.fail(f"action must be one of {sorted(a.value for a in VerdictAction)}")
    if node.config.get("combine", VerdictCombine.ANY) not in set(VerdictCombine):
        node.fail(f"combine must be one of {sorted(c.value for c in VerdictCombine)}")


_NODE_VALIDATORS = {
    NodeType.EXTRACT: _validate_extract,
    NodeType.TOOL_EXTRACT: _validate_tool_extract,
    NodeType.REGEX: _validate_regex,
    NodeType.MODEL: _validate_model,
    NodeType.NOT: _validate_not,
    NodeType.TRANSFORM: _validate_transform,
    NodeType.VERDICT: _validate_verdict,
}
