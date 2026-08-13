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

from gateway.domain.exception.guardrail_error import GuardrailError

DRAFT_VERSION = "draft"

#: Phase 2 는 텍스트 검사만 다룬다. Phase 3 이 tool_result/tool_call 을 더한다.
#: 감사 모듈의 Checkpoint 와 어긋나지 않는지는 2c 에서 테스트로 고정한다 —
#: 도메인이 감사 모듈을 임포트하면 의존 방향이 뒤집힌다.
VALID_CHECKPOINTS = frozenset({"input", "output"})
VALID_TRANSFORMS = frozenset({"lower", "strip"})

#: 이름은 URL 경로 조각이자 X-Gardevoir-Guardrail 헤더 값이고, API 키의
#: allowed_guardrails 와 문자열 비교된다. 세 자리 모두에서 모호하지 않아야 하므로
#: 슬러그로 제한한다. 프레젠테이션이 아니라 도메인에서 막는다 — CLI 든 라우터든
#: 같은 규칙을 받아야 한다.
#: RE2 는 \Z 를 모른다. fullmatch 로 고정한다.
NAME_PATTERN = re2.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")


class NodeType(StrEnum):
    EXTRACT = "extract"
    REGEX = "regex"
    LENGTH = "length"
    TRANSFORM = "transform"
    VERDICT = "verdict"


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
        if not isinstance(self.name, str) or not NAME_PATTERN.fullmatch(self.name):
            GuardrailError.INVALID_NAME.raise_(details={"name": self.name})

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


_NODE_VALIDATORS = {
    NodeType.EXTRACT: _validate_extract,
    NodeType.REGEX: _validate_regex,
    NodeType.LENGTH: _validate_length,
    NodeType.TRANSFORM: _validate_transform,
    NodeType.VERDICT: _validate_verdict,
}
