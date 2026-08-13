# Phase 2a: Guardrail 저작 + 발행 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **REQUIRED READING:** `skills/gardevoir-be/SKILL.md` before any step.

**Goal:** 가드레일(노드 그래프)을 Admin API 로 저작·검증·발행할 수 있게 만든다. 컴파일과 판정은 2b·2c.

**Architecture:** `Guardrail` 은 노드 그래프 1개를 담는 애그리거트다. 유효성(순환·끊긴 엣지·노드 설정)은 도메인이 소유한다 — 저장소나 전송과 무관한 규칙이다. 버전은 Dify 패턴을 따른다: `draft` 행 하나가 가변, 발행된 행은 불변으로 누적. 발행 가능성 검증이 발행의 게이트다(§6).

**Tech Stack:** SQLAlchemy 2.0 (jsonb) · Alembic · google-re2 · FastAPI · pytest

**설계 문서:** `docs/superpowers/specs/2026-08-12-gardevoir-design.md`
**선행:** Phase 1a·1b·1c (PR #1·#2·#3)

---

## Global Constraints

Phase 1 의 제약이 모두 유효하다. 이번 단계에서 특히:

- **regex 검증은 `re2` 로 한다.** 표준 `re` 는 ReDoS 에 취약하다(§11.1). 저작 시점에
  패턴을 컴파일해 문법을 확인하고, **그 결과를 발행 시점에 다시 검증하지 않는다** —
  §11.3 에서 그 중복이 컴파일 시간의 55% 였다.
- **`Guardrail` 은 순수 도메인이다.** SQLAlchemy·FastAPI 임포트 금지. AST 테스트로 고정.
- **발행된 버전은 절대 수정하지 않는다.** 감사 로그가 `guardrail_version` 으로 판정을
  재현하므로(§6), 발행 후 내용이 바뀌면 재현이 거짓이 된다.
- **`Guardrail` 은 `CamelModel` 이 아니다.** 도메인 모델이다. 경계 DTO 는 별도.
- 돌연변이 테스트 전에 커밋하고, 원복 후 `__pycache__` 를 지운다.
- 테스트 함수 독스트링은 한국어, 모듈·클래스 독스트링은 영어.

---

## 도메인 모델

노드 카탈로그는 Phase 2 범위(①③ 텍스트 검사)에 맞춰 작게 시작한다. Phase 3 이
`tool_result`/`tool_call` 체크포인트와 액션 노드를 더한다.

```
Guardrail (애그리거트)
  name: str                    요청이 X-Gardevoir-Guardrail 로 지정하는 이름
  version: str                 "draft" 또는 발행 번호의 문자열
  version_number: int | None   발행 시 부여. draft 는 None
  nodes: tuple[Node, ...]
  edges: tuple[Edge, ...]

Node
  id: str
  type: NodeType
  config: dict                 타입별 설정. 검증은 타입이 소유

NodeType
  EXTRACT     checkpoint: "input" | "output"
  REGEX       pattern: str                     re2 로 문법 검증
  LENGTH      max_chars: int
  TRANSFORM   op: "lower" | "strip"
  VERDICT     決: "conclusive" | "hint" | "model_only"
              action: "block" | "mask" | "allow"
```

**`VERDICT.決` 은 오타다 — `decision` 으로 쓴다.** (계획서 자체 검토에서 발견)

---

## File Structure

```
backend/gateway/src/gateway/
├── domain/
│   ├── models/guardrail.py           Guardrail · Node · Edge · NodeType · Checkpoint 재사용
│   └── exception/guardrail_error.py  GuardrailError(ErrorCatalog)
├── application/
│   ├── repository/guardrail_repository.py   Protocol (쓰기)
│   ├── dao/__init__.py  dao/guardrail_dao.py  Protocol (읽기 → Result DTO)
│   ├── command/guardrail_command.py         CreateGuardrail · UpdateDraft (CamelModel)
│   ├── result/guardrail_result.py           GuardrailDetail · GuardrailSummary (CamelModel)
│   └── service/guardrail_service.py         GuardrailService
├── infrastructure/
│   ├── models/guardrail.py           GuardrailModel (jsonb)
│   ├── mappers/guardrail.py
│   ├── repository/guardrail_repository.py
│   └── dao/__init__.py  dao/guardrail_dao.py
└── presentation/http/admin_guardrails.py    /v1/admin/guardrails
alembic/versions/…                   guardrails 테이블
```

---

## Task 1: Guardrail 도메인 모델 + 검증

**Files:**
- Create: `src/gateway/domain/models/guardrail.py`
- Create: `src/gateway/domain/exception/guardrail_error.py`
- Modify: `src/gateway/domain/models/__init__.py`, `domain/exception/__init__.py`
- Test: `tests/test_guardrail_domain.py`

**Interfaces:**
- Produces:
  - `NodeType(StrEnum)`: `EXTRACT`, `REGEX`, `LENGTH`, `TRANSFORM`, `VERDICT`
  - `Decision(StrEnum)`: `CONCLUSIVE`, `HINT`, `MODEL_ONLY`
  - `VerdictAction(StrEnum)`: `BLOCK`, `MASK`, `ALLOW`
  - `Node` frozen dataclass: `id: str`, `type: NodeType`, `config: dict`
  - `Edge` frozen dataclass: `src: str`, `dst: str`
  - `Guardrail` frozen dataclass: `name`, `version`, `version_number`, `nodes`, `edges`
    - `DRAFT_VERSION: str = "draft"`
    - `is_draft: bool` (property)
    - `validate() -> None` — raises `GuardrailError.*`
    - `published_as(version_number: int) -> "Guardrail"` — 발행된 복제본
  - `GuardrailError(ErrorCatalog)`:
    `NOT_FOUND`(404/`GUARDRAIL-001`), `CYCLE`(422/`GUARDRAIL-002`),
    `DANGLING_EDGE`(422/`GUARDRAIL-003`), `DUPLICATE_NODE_ID`(422/`GUARDRAIL-004`),
    `INVALID_NODE_CONFIG`(422/`GUARDRAIL-005`), `NAME_TAKEN`(409/`GUARDRAIL-006`),
    `PUBLISHED_IS_IMMUTABLE`(409/`GUARDRAIL-007`), `NO_DRAFT`(404/`GUARDRAIL-008`)

**검증이 도메인에 있는 이유:** "그래프에 순환이 없다", "엣지가 존재하는 노드를 가리킨다",
"regex 노드의 패턴이 컴파일된다" — 전부 저장소·전송과 무관한 규칙이다. 라우터나
컴파일러에 두면 같은 규칙이 여러 곳에 복제된다 (§5).

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_guardrail_domain.py`)

아래 성질을 각각 독립 테스트로 쓴다:

1. `test_valid_graph_passes` — extract → regex → verdict 그래프가 통과
2. `test_cycle_is_rejected` — a→b→a 가 `GUARDRAIL-002`
3. `test_self_loop_is_rejected` — a→a 가 `GUARDRAIL-002`
4. `test_dangling_edge_is_rejected` — 존재하지 않는 노드를 가리키면 `GUARDRAIL-003`
5. `test_duplicate_node_id_is_rejected` — `GUARDRAIL-004`
6. `test_regex_pattern_is_validated_with_re2` — `(a+)+$` 는 통과(re2 는 안전),
   `[unclosed` 는 `GUARDRAIL-005`
7. `test_extract_requires_a_known_checkpoint` — `"nowhere"` 는 `GUARDRAIL-005`
8. `test_length_requires_a_positive_max` — `max_chars=0` 은 `GUARDRAIL-005`
9. `test_verdict_requires_known_decision_and_action` — 오타는 `GUARDRAIL-005`
10. `test_transform_requires_a_known_op` — `GUARDRAIL-005`
11. `test_unknown_node_type_is_rejected` — 열거형 밖의 타입
12. `test_empty_graph_is_valid` — 노드 0개는 유효(빈 가드레일 = 아무것도 안 함)
13. `test_guardrail_is_immutable` — `FrozenInstanceError`
14. `test_is_draft` — `version == "draft"` 일 때만 True
15. `test_published_as_produces_an_immutable_copy` — 원본은 draft 로 남고,
    복제본은 `version="3"`, `version_number=3`
16. `test_published_guardrail_cannot_be_published_again` — `GUARDRAIL-007`
17. `test_domain_imports_nothing_from_outer_layers` — AST 검사 (Phase 1b 의
    `_imports_of` 헬퍼를 공유 모듈로 뽑아 재사용)
18. `test_validate_reports_the_offending_node` — `details` 에 노드 id 가 있어야
    UI 가 어느 노드를 붉게 칠할지 안다

- [ ] **Step 2: 실패 확인 → Step 3: 구현**

`domain/exception/guardrail_error.py`:

```python
"""Guardrail error catalog."""

from shared_kernel.exception import (
    ConflictError,
    ErrorCatalog,
    NotFoundError,
    ValidationError,
)


class GuardrailError(ErrorCatalog):
    NOT_FOUND = ("GUARDRAIL-001", "no such guardrail", NotFoundError)
    CYCLE = ("GUARDRAIL-002", "the graph contains a cycle", ValidationError)
    DANGLING_EDGE = ("GUARDRAIL-003", "an edge points at a missing node", ValidationError)
    DUPLICATE_NODE_ID = ("GUARDRAIL-004", "node ids must be unique", ValidationError)
    INVALID_NODE_CONFIG = ("GUARDRAIL-005", "a node's configuration is invalid", ValidationError)
    NAME_TAKEN = ("GUARDRAIL-006", "a guardrail with this name already exists", ConflictError)
    PUBLISHED_IS_IMMUTABLE = (
        "GUARDRAIL-007",
        "a published guardrail cannot be modified",
        ConflictError,
    )
    NO_DRAFT = ("GUARDRAIL-008", "this guardrail has no draft", NotFoundError)
```

`domain/models/guardrail.py` — 요지:

```python
"""Guardrail aggregate: one node graph.

Validation lives here because "the graph has no cycle", "an edge points at a
real node", and "a regex node's pattern compiles" are rules about the guardrail
itself, independent of storage or transport (§5).

Persistence-ignorant: no SQLAlchemy, no FastAPI.
"""

from collections import deque
from dataclasses import dataclass, replace
from enum import StrEnum

import re2

from gateway.domain.exception.guardrail_error import GuardrailError

DRAFT_VERSION = "draft"

#: Phase 2 는 텍스트 검사만 다룬다. Phase 3 이 tool_result/tool_call 을 더한다.
VALID_CHECKPOINTS = frozenset({"input", "output"})
VALID_TRANSFORMS = frozenset({"lower", "strip"})


class NodeType(StrEnum):
    EXTRACT = "extract"
    REGEX = "regex"
    LENGTH = "length"
    TRANSFORM = "transform"
    VERDICT = "verdict"


class Decision(StrEnum):
    """규칙 티어의 역할. 설계 문서 §4 의 세 유형."""

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
        checker = _NODE_VALIDATORS.get(self.type)
        if checker is None:
            self._fail("unknown node type")
        checker(self)

    def _fail(self, reason: str) -> None:
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
        if not self.is_draft:
            GuardrailError.PUBLISHED_IS_IMMUTABLE.raise_(
                details={"name": self.name, "version": self.version}
            )
        return replace(self, version=str(version_number), version_number=version_number)
```

검증 헬퍼 (같은 파일):

```python
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
        """Kahn's algorithm. 자기 루프도 순환이다."""
        indegree = {node.id: 0 for node in self.nodes}
        adjacency: dict[str, list[str]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            adjacency[edge.src].append(edge.dst)
            indegree[edge.dst] += 1

        queue = deque(node_id for node_id, deg in indegree.items() if deg == 0)
        visited = 0
        while queue:
            current = queue.popleft()
            visited += 1
            for neighbour in adjacency[current]:
                indegree[neighbour] -= 1
                if indegree[neighbour] == 0:
                    queue.append(neighbour)

        if visited != len(self.nodes):
            unresolved = sorted(n for n, deg in indegree.items() if deg > 0)
            GuardrailError.CYCLE.raise_(details={"nodes": unresolved})
```

노드 타입별 검증기 (모듈 하단):

```python
def _validate_extract(node: Node) -> None:
    checkpoint = node.config.get("checkpoint")
    if checkpoint not in VALID_CHECKPOINTS:
        node._fail(f"checkpoint must be one of {sorted(VALID_CHECKPOINTS)}")


def _validate_regex(node: Node) -> None:
    pattern = node.config.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        node._fail("pattern must be a non-empty string")
    try:
        # 저작 시점에 한 번만 확인한다. 발행 시점에 다시 하면 컴파일 시간의
        # 절반을 낭비한다 (§11.3).
        re2.compile(pattern)
    except Exception as exc:
        node._fail(f"pattern does not compile: {exc}")


def _validate_length(node: Node) -> None:
    max_chars = node.config.get("max_chars")
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars <= 0:
        node._fail("max_chars must be a positive integer")


def _validate_transform(node: Node) -> None:
    if node.config.get("op") not in VALID_TRANSFORMS:
        node._fail(f"op must be one of {sorted(VALID_TRANSFORMS)}")


def _validate_verdict(node: Node) -> None:
    decision = node.config.get("decision")
    action = node.config.get("action")
    if decision not in set(Decision):
        node._fail(f"decision must be one of {sorted(d.value for d in Decision)}")
    if action not in set(VerdictAction):
        node._fail(f"action must be one of {sorted(a.value for a in VerdictAction)}")


_NODE_VALIDATORS = {
    NodeType.EXTRACT: _validate_extract,
    NodeType.REGEX: _validate_regex,
    NodeType.LENGTH: _validate_length,
    NodeType.TRANSFORM: _validate_transform,
    NodeType.VERDICT: _validate_verdict,
}
```

- [ ] **Step 4: 통과 확인 + 커밋 + 돌연변이**

돌연변이 (전부 CAUGHT 되어야 한다): 순환 검사 제거 · 끊긴 엣지 검사 제거 ·
중복 id 검사 제거 · regex 컴파일 검증 제거 · `published_as` 의 draft 검사 제거 ·
`max_chars <= 0` 검사 제거 · `details` 의 `node_id` 제거

---

## Task 2: ORM + mapper + Alembic

**Files:**
- Create: `src/gateway/infrastructure/models/guardrail.py`
- Create: `src/gateway/infrastructure/mappers/guardrail.py`
- Modify: `infrastructure/models/__init__.py` (**re-export 필수** — 빠뜨리면
  autogenerate 가 테이블을 놓친다), `infrastructure/mappers/__init__.py`
- Test: `tests/test_guardrail_mapper.py`

**Interfaces:**
- Produces:
  - `GuardrailModel` — `__tablename__ = "guardrails"`,
    `id: str`(PK, ULID), `name: str`, `version: str`, `version_number: int | None`,
    `graph: dict`(JSONB, `{"nodes": [...], "edges": [...]}`), + `TimestampMixin`
  - 인덱스: `(name, version)` 유일, `(name, version_number)` 유일 (부분: not null)
  - `to_domain(row) -> Guardrail`, `to_model(g: Guardrail, *, id: str) -> GuardrailModel`

**`graph` 를 하나의 jsonb 로 두는 이유:** Dify 도 `workflows.graph` 에 그래프 전체를
담는다(§6). 노드를 별도 테이블로 정규화하면 발행마다 수십 행을 복제해야 하고, 우리는
그래프 내부를 SQL 로 조회할 필요가 컴파일러 밖에 없다. 다만 Dify 와 달리 `jsonb` 를
쓴다 — "이 regex 를 쓰는 가드레일이 어디 있나" 같은 질의가 관리에 필요해진다(§6).

- [ ] Step 1~4: 테스트 → 실패 확인 → 구현 → 커밋

테스트 성질:
1. `test_mapper_roundtrip_preserves_the_graph` — 노드·엣지·설정이 전부 보존
2. `test_mapper_returns_tuples` — jsonb 는 list 로 돌아온다. 도메인은 불변
3. `test_mapper_tolerates_an_empty_graph`
4. `test_node_type_round_trips_as_a_string` — jsonb 에 StrEnum 이 문자열로
5. `test_draft_and_published_can_coexist_for_one_name` (세션 필요)
6. `test_duplicate_name_and_version_is_rejected_by_the_database` — 유일 제약
7. `test_duplicate_version_number_is_rejected` — 같은 이름에 같은 번호 두 개 금지
8. `test_null_version_number_does_not_collide` — draft 가 여러 이름에 존재 가능
9. Alembic: `naming_convention` 이 적용된 이름, upgrade/downgrade 왕복

---

## Task 3: Repository + DAO

**Files:**
- Create: `application/repository/guardrail_repository.py` (Protocol)
- Create: `application/dao/__init__.py`, `application/dao/guardrail_dao.py` (Protocol)
- Create: `application/result/__init__.py`, `application/result/guardrail_result.py`
- Create: `infrastructure/repository/guardrail_repository.py`
- Create: `infrastructure/dao/__init__.py`, `infrastructure/dao/guardrail_dao.py`
- Test: `tests/test_guardrail_repository.py`, `tests/test_guardrail_dao.py`

**Interfaces:**
- Produces:
  - `GuardrailRepository` Protocol —
    `async add(g, *, id: str) -> None`,
    `async find_draft(name) -> Guardrail | None`,
    `async find_published(name, version_number: int | None = None) -> Guardrail | None`
      (`None` 이면 최신 발행본),
    `async replace_draft(g) -> None`,
    `async next_version_number(name) -> int`
  - `GuardrailDao` Protocol (읽기, **Result DTO 만 반환**) —
    `async get_detail(name, version) -> GuardrailDetail | None`,
    `async list_summaries() -> tuple[list[GuardrailSummary], int]`
  - `GuardrailSummary(CamelModel)`: `name`, `latest_version_number: int | None`,
    `has_draft: bool`, `updated_at`
  - `GuardrailDetail(CamelModel)`: `name`, `version`, `version_number`, `graph: dict`,
    `created_at`, `updated_at`

**Repository vs DAO:** Repository 는 도메인 애그리거트를 다루고(발행·검증에 필요),
DAO 는 Result DTO 를 반환한다(목록·상세 화면). `get` 이 양쪽에 있는 것이 정상이다 —
쓰기용 로드와 읽기용 투영은 다른 일이다 (§5).

- [ ] Step 1~4: 테스트 → 실패 확인 → 구현 → 커밋

테스트 성질 (repository):
1. `test_add_then_find_draft`
2. `test_find_published_returns_the_latest_by_default`
3. `test_find_published_can_target_a_specific_version`
4. `test_next_version_number_starts_at_one`
5. `test_next_version_number_increments_past_the_highest`
6. `test_replace_draft_overwrites_in_place` — draft 행이 하나만 남는다
7. `test_replace_draft_does_not_touch_published_rows` — **발행본 불변성**
8. `test_find_draft_returns_none_when_absent`

테스트 성질 (dao):
1. `test_list_summaries_reports_latest_and_draft_presence`
2. `test_list_summaries_returns_total`
3. `test_get_detail_returns_the_graph`
4. `test_dao_never_returns_domain_objects` — 반환 타입이 `GuardrailDetail` 이다

---

## Task 4: GuardrailService (유스케이스)

**Files:**
- Create: `application/command/__init__.py`, `application/command/guardrail_command.py`
- Create: `application/service/guardrail_service.py`
- Test: `tests/test_guardrail_service.py`

**Interfaces:**
- Produces:
  - `CreateGuardrail(CamelModel)`: `name: str`, `graph: dict`
  - `UpdateDraft(CamelModel)`: `graph: dict`
  - `GuardrailService` — `__init__(*, guardrails: GuardrailRepository, dao: GuardrailDao)`
    - `async create(cmd) -> GuardrailDetail` — draft 생성. 이름 중복은 `GUARDRAIL-006`
    - `async update_draft(name, cmd) -> GuardrailDetail`
    - `async publish(name) -> GuardrailDetail` — draft 를 검증하고 다음 번호로 발행
    - `async get(name, version) -> GuardrailDetail`
    - `async list() -> Page[GuardrailSummary]`

**발행 흐름:**

```
draft 로드 → validate() → next_version_number() → published_as(n) → add()
                                                   draft 는 그대로 남는다
```

**draft 를 남기는 이유:** 발행 후에도 계속 편집할 수 있어야 한다. Dify 와 같다(§6).

**서비스가 쓰기 후 DAO 로 재조회하는 이유:** 투영 경로를 하나로 유지한다 — 응답이
목록·상세와 같은 형태여야 한다 (§5, "Single DTO at the boundary").

- [ ] Step 1~4: 테스트 → 실패 확인 → 구현 → 커밋

테스트 성질:
1. `test_create_makes_a_draft`
2. `test_create_rejects_a_duplicate_name` — `GUARDRAIL-006`
3. `test_create_validates_the_graph` — 순환이면 `GUARDRAIL-002`
4. `test_update_draft_replaces_the_graph`
5. `test_update_draft_validates`
6. `test_update_draft_fails_without_a_draft` — `GUARDRAIL-008`
7. `test_publish_assigns_version_one_first`
8. `test_publish_increments`
9. `test_publish_validates_before_assigning_a_number` — **검증 실패 시 번호를
   소모하지 않는다.** 그러지 않으면 버전 번호에 구멍이 생겨 감사 추적이 헷갈린다
10. `test_publish_leaves_the_draft_editable`
11. `test_published_rows_are_never_rewritten` — 발행 후 draft 를 고쳐도 발행본 불변
12. `test_get_returns_a_result_dto`
13. `test_list_returns_a_page`

---

## Task 5: Admin API

**Files:**
- Create: `presentation/http/admin_guardrails.py`
- Modify: `composition.py`, `presentation/http/app.py`
- Test: `tests/test_admin_guardrails.py`

**Interfaces:**
- Produces:
  - `POST   /v1/admin/guardrails`               → 201 `GuardrailDetail`
  - `GET    /v1/admin/guardrails`               → 200 `Page[GuardrailSummary]`
  - `GET    /v1/admin/guardrails/{name}`        → 200 `GuardrailDetail` (최신 발행본)
  - `GET    /v1/admin/guardrails/{name}/draft`  → 200 `GuardrailDetail`
  - `PUT    /v1/admin/guardrails/{name}/draft`  → 200 `GuardrailDetail`
  - `POST   /v1/admin/guardrails/{name}/publish` → 200 `GuardrailDetail`
  - `composition.provide_guardrail_service` / `GuardrailServiceDep`

> ⚠️ **인증은 이 태스크의 범위가 아니다.** Admin API 는 아직 인증이 없다.
> Phase 5(UI)가 관리자 인증을 정할 때 함께 붙인다 — 설계 문서 §14 에 미정으로
> 기록돼 있다. **그때까지 이 라우터를 외부에 노출하면 안 된다.** 라우터 독스트링과
> `infra/README.md` 에 그 사실을 적는다.

- [ ] Step 1~5: 테스트 → 실패 확인 → 구현 → 실제 기동 → 커밋

테스트 성질:
1. `test_create_returns_201_with_the_detail`
2. `test_create_duplicate_is_409`
3. `test_create_invalid_graph_is_422_and_names_the_node` — `details.node_id`
4. `test_get_unknown_is_404_in_our_shape` — `{"code": "GUARDRAIL-001"}`
5. `test_put_draft_updates`
6. `test_publish_returns_the_published_detail`
7. `test_publish_then_get_returns_the_published_version`
8. `test_list_returns_summaries`
9. `test_camel_case_on_the_wire` — `versionNumber`, `hasDraft`
10. `test_responses_carry_the_request_id`

---

## Self-Review

**1. 범위**

Phase 2a 는 저작·검증·발행까지다. 컴파일(2b)과 프록시 통합(2c)은 범위 밖.
`SharedNode` 와 `BaseGuardrail` 은 2b 에서 컴파일 시 병합될 때 만든다 — 지금
만들면 쓰이지 않는 코드가 된다.

**2. 계획서 자체 검토에서 고친 것**

- 도메인 모델 표의 `VERDICT.決` 은 오타였다 → `decision`.
- 처음에 발행 시 regex 를 다시 검증하려 했다 → §11.3 에서 그 중복이 컴파일
  시간의 55% 였으므로 저작 시점 한 번으로 고정했다.
- `test_publish_validates_before_assigning_a_number` 를 추가했다. 검증 실패가
  번호를 소모하면 감사 추적에 구멍이 생긴다 — 처음 초안에 없던 성질이다.

**3. Type consistency**

- `Checkpoint` 는 Phase 1c 의 `application/audit/audit_event.py` 가 이미 소유한다.
  도메인이 감사 모듈을 임포트하면 의존 방향이 뒤집히므로, 도메인은 `VALID_CHECKPOINTS`
  문자열 집합을 자기 것으로 둔다. 2c 에서 둘이 어긋나지 않는지 테스트로 고정한다.
- `Node.config` 는 `dict` 다. 타입별 스키마를 Pydantic 으로 두지 않는 이유: jsonb 에서
  그대로 오고, 컴파일러가 읽고, 요청 경로에 Pydantic 검증이 들어갈 이유가 없다(§11.8).
  검증은 `Node.validate()` 가 명시적으로 한다.
- `Guardrail.version` 은 문자열이다(`"draft"` 또는 `"3"`). `version_number` 가 정수
  버전이고 draft 는 `None`. Dify 와 같은 형태(§6).
