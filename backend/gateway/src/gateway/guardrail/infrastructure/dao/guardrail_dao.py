"""SQLAlchemy Guardrail read projections."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.guardrail.application.result.guardrail_result import (
    GuardrailDetail,
    GuardrailSummary,
)
from gateway.guardrail.domain.models.guardrail import (
    DRAFT_VERSION,
    VALID_CHECKPOINTS,
    NodeType,
    VerdictAction,
)
from gateway.guardrail.infrastructure.model.guardrail_model import GuardrailModel

_CHECKPOINT_ORDER = ("input", "tool_result", "tool_call", "output")
_ACTION_ORDER = tuple(
    action.value for action in (VerdictAction.BLOCK, VerdictAction.MASK, VerdictAction.ALLOW)
)
_CHECK_NODE_TYPES = frozenset(
    {
        NodeType.REGEX.value,
        NodeType.MODEL.value,
        NodeType.TAINT.value,
        NodeType.SIDE_EFFECT.value,
        NodeType.PROVENANCE.value,
    }
)
_TOOL_CALL_NODE_TYPES = frozenset({NodeType.SIDE_EFFECT.value, NodeType.PROVENANCE.value})


@dataclass(slots=True)
class _SummaryState:
    name: str
    description: str
    latest_version_number: int | None
    has_draft: bool
    updated_at: datetime
    graph: object


class SqlAlchemyGuardrailDao:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_detail(self, name: str, version: str) -> GuardrailDetail | None:
        row = (
            await self._session.execute(
                select(GuardrailModel).where(
                    GuardrailModel.name == name,
                    GuardrailModel.version == version,
                )
            )
        ).scalar_one_or_none()
        return GuardrailDetail.model_validate(row) if row is not None else None

    async def get_latest_detail(self, name: str) -> GuardrailDetail | None:
        row = (
            await self._session.execute(
                select(GuardrailModel)
                .where(
                    GuardrailModel.name == name,
                    # version 문자열로 정렬하면 '10' < '9' 가 된다.
                    GuardrailModel.version_number.is_not(None),
                )
                .order_by(GuardrailModel.version_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return GuardrailDetail.model_validate(row) if row is not None else None

    async def list_summaries(self) -> tuple[list[GuardrailSummary], int]:
        """One row per name.

        Pagination is not implemented yet, so ``total`` equals ``len(items)``. It
        is in the signature because the wire shape is ``Page[GuardrailSummary]``
        and adding the field later would be a breaking change.
        """
        rows = (
            await self._session.execute(
                select(
                    GuardrailModel.name,
                    GuardrailModel.version,
                    GuardrailModel.version_number,
                    GuardrailModel.description,
                    GuardrailModel.graph,
                    GuardrailModel.updated_at,
                )
                # 순서가 없으면 목록 화면이 요청마다 흔들린다.
                .order_by(GuardrailModel.name)
            )
        ).all()

        states: dict[str, _SummaryState] = {}
        for row in rows:
            state = states.get(row.name)
            if state is None:
                state = _SummaryState(
                    name=row.name,
                    description="",
                    latest_version_number=None,
                    has_draft=False,
                    updated_at=row.updated_at,
                    graph=None,
                )
                states[row.name] = state

            state.updated_at = max(state.updated_at, row.updated_at)
            if row.version == DRAFT_VERSION:
                state.has_draft = True
                if state.latest_version_number is None:
                    state.description = row.description
                    state.graph = row.graph
            if row.version_number is not None and (
                state.latest_version_number is None
                or row.version_number > state.latest_version_number
            ):
                state.latest_version_number = row.version_number
                state.description = row.description
                state.graph = row.graph

        items = []
        for state in states.values():
            checkpoints, actions, check_count, verdict_count = _project_graph(state.graph)
            items.append(
                GuardrailSummary(
                    name=state.name,
                    description=state.description,
                    latest_version_number=state.latest_version_number,
                    has_draft=state.has_draft,
                    updated_at=state.updated_at,
                    checkpoints=checkpoints,
                    actions=actions,
                    check_count=check_count,
                    verdict_count=verdict_count,
                )
            )
        return items, len(items)


def _project_graph(graph: object) -> tuple[list[str], list[str], int, int]:
    if not isinstance(graph, dict):
        return [], [], 0, 0
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return [], [], 0, 0

    checkpoints: set[str] = set()
    actions: set[str] = set()
    check_count = 0
    verdict_count = 0

    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        if node_type in _CHECK_NODE_TYPES:
            check_count += 1
        if node_type == NodeType.VERDICT.value:
            verdict_count += 1

        config = node.get("config")
        if not isinstance(config, dict):
            config = {}

        if node_type in _TOOL_CALL_NODE_TYPES:
            checkpoints.add("tool_call")
        elif config.get("checkpoint") in VALID_CHECKPOINTS:
            checkpoints.add(config["checkpoint"])

        action = config.get("action")
        if node_type == NodeType.VERDICT.value and action in _ACTION_ORDER:
            actions.add(action)

    return (
        [checkpoint for checkpoint in _CHECKPOINT_ORDER if checkpoint in checkpoints],
        [action for action in _ACTION_ORDER if action in actions],
        check_count,
        verdict_count,
    )
