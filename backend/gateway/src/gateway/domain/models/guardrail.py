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

import re2

from gateway.domain.exception.guardrail_error import GuardrailError

DRAFT_VERSION = "draft"

#: Phase 2 는 텍스트 검사만 다룬다. Phase 3 이 tool_result/tool_call 을 더한다.
#: 감사 모듈의 Checkpoint 와 어긋나지 않는지는 2c 에서 테스트로 고정한다 —
#: 도메인이 감사 모듈을 임포트하면 의존 방향이 뒤집힌다.
VALID_CHECKPOINTS = frozenset({"input", "output"})
VALID_TRANSFORMS = frozenset({"lower", "strip"})


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
        node.fail(f"pattern does not compile: {exc}")


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
