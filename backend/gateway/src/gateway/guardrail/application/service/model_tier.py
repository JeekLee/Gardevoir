"""Resolve rule-tier pending verdicts through a policy-adaptive model."""

import logging
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import replace
from enum import StrEnum
from typing import Any

from gateway.guardrail.application.multimodal import extract_input_images
from gateway.guardrail.application.outcome import TIER_MODEL, Inspection
from gateway.guardrail.application.port.model_judge import (
    JudgeRequest,
    JudgeResult,
    ModelJudge,
)
from gateway.guardrail.domain.models.execution_plan import ExecutionPlan, ModelNodeSpec
from gateway.guardrail.domain.models.guardrail import VerdictAction
from gateway.guardrail.domain.models.mode import Mode

logger = logging.getLogger(__name__)

_SEVERITY = {
    VerdictAction.ALLOW: 0,
    VerdictAction.MASK: 1,
    VerdictAction.BLOCK: 2,
}


class FailMode(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class ModelTier:
    """Batch pending verdicts, map them to policy actions, and merge severity."""

    def __init__(
        self,
        *,
        model_judge: ModelJudge,
        model: str,
        deadline_ms: int,
        fail_modes: Mapping[str, FailMode],
        max_images: int,
        max_data_uri_bytes: int,
    ) -> None:
        self._model_judge = model_judge
        self._model = model
        self._deadline_ms = deadline_ms
        self._fail_modes = dict(fail_modes)
        self._max_images = max_images
        self._max_data_uri_bytes = max_data_uri_bytes

    async def evaluate(
        self,
        *,
        inspection: Inspection,
        plan: ExecutionPlan,
        text: str,
        mode: Mode,
        payload: Any,
    ) -> Inspection:
        """Resolve one checkpoint's pending verdicts and return an updated inspection."""
        pending = tuple(dict.fromkeys(inspection.pending_model))
        if not pending:
            return inspection

        extracted = extract_input_images(
            payload,
            max_images=self._max_images,
            max_data_uri_bytes=self._max_data_uri_bytes,
        )
        specs: dict[str, ModelNodeSpec] = {}
        requests: list[JudgeRequest] = []
        for verdict_id in pending:
            spec = plan.model_nodes.get(verdict_id)
            if spec is None:
                continue
            specs[verdict_id] = spec
            requests.append(
                JudgeRequest(
                    checkpoint=spec.checkpoint,
                    node_id=spec.node_id,
                    policy=spec.policy,
                    text=text,
                    strictness=spec.strictness,
                    deadline_ms=self._deadline_ms,
                    images=extracted.images,
                )
            )

        results = (
            tuple(
                JudgeResult(
                    node_id=request.node_id,
                    violated=None,
                    score=None,
                    raw_label=extracted.limit_error,
                )
                for request in requests
            )
            if extracted.limit_error
            else await self._judge(requests)
        )
        by_node: defaultdict[str, deque[JudgeResult]] = defaultdict(deque)
        for result in results:
            if isinstance(result, JudgeResult):
                by_node[result.node_id].append(result)

        candidates: list[VerdictAction] = []
        checks = list(inspection.checks_fired)
        judgements = list(inspection.model_judgements)
        for verdict_id in pending:
            spec = specs.get(verdict_id)
            result = (
                by_node[spec.node_id].popleft()
                if spec is not None and by_node[spec.node_id]
                else JudgeResult(
                    node_id=spec.node_id if spec is not None else "",
                    violated=None,
                    score=None,
                    raw_label="missing_result" if spec is not None else "missing_model_spec",
                )
            )
            candidate = self._candidate(
                result=result,
                spec=spec,
                verdict_id=verdict_id,
                plan=plan,
                text=text,
            )
            candidates.append(candidate)
            if result.violated is True:
                checks.append(verdict_id)
            judgements.append(
                {
                    "verdict": verdict_id,
                    "node": result.node_id,
                    "violated": result.violated,
                    "score": result.score,
                    "raw_label": result.raw_label,
                    "applied_action": str(candidate),
                }
            )

        existing = (
            VerdictAction.BLOCK
            if inspection.blocked
            else VerdictAction.MASK
            if inspection.masked
            else VerdictAction.ALLOW
        )
        target = self._strongest((existing, *candidates))
        checks_fired = tuple(dict.fromkeys(checks))

        if mode is Mode.DRY_RUN:
            dry_run_target = self._strongest((inspection.would_have or VerdictAction.ALLOW, target))
            return replace(
                inspection,
                action=VerdictAction.ALLOW,
                tier=TIER_MODEL,
                checks_fired=checks_fired,
                pending_model=(),
                would_have=(dry_run_target if dry_run_target is not VerdictAction.ALLOW else None),
                model=self._model,
                model_judgements=tuple(judgements),
            )

        return replace(
            inspection,
            action=(VerdictAction.BLOCK if target is VerdictAction.BLOCK else VerdictAction.ALLOW),
            tier=TIER_MODEL,
            checks_fired=checks_fired,
            pending_model=(),
            masked=inspection.masked or target is VerdictAction.MASK,
            model=self._model,
            model_judgements=tuple(judgements),
        )

    async def _judge(self, requests: Sequence[JudgeRequest]) -> Sequence[JudgeResult]:
        if not requests:
            return ()
        try:
            return await self._model_judge.judge(requests)
        except Exception:
            # 포트 구현이 계약을 어겨 예외를 내도 enabled 요청의 fail-mode가 사라지면
            # 안 된다. 원문·policy는 로그에 넣지 않는다.
            logger.exception("model judge batch failed")
            return ()

    def _candidate(
        self,
        *,
        result: JudgeResult,
        spec: ModelNodeSpec | None,
        verdict_id: str,
        plan: ExecutionPlan,
        text: str,
    ) -> VerdictAction:
        checkpoint = spec.checkpoint if spec is not None else "input"
        if result.violated is True and spec is not None:
            candidate = spec.action
        elif result.violated is False:
            candidate = VerdictAction.ALLOW
        else:
            candidate = (
                VerdictAction.BLOCK
                if self._fail_modes[checkpoint] is FailMode.CLOSED
                else VerdictAction.ALLOW
            )

        if candidate is VerdictAction.MASK and not self._has_mask_span(
            plan, checkpoint, verdict_id, text
        ):
            # 저작·컴파일 시점에 거부되므로 도달할 수 없다. 그래도 오래된 계획이나
            # 계약을 어긴 호출이 원문을 내보내지 않도록 BLOCK 방어선을 유지한다.
            logger.warning(
                "unreachable model MASK verdict %r in guardrail %r has no span at %s; "
                "applying BLOCK",
                verdict_id,
                plan.guardrail,
                checkpoint,
            )
            return VerdictAction.BLOCK
        return candidate

    @staticmethod
    def _has_mask_span(plan: ExecutionPlan, checkpoint: str, verdict_id: str, text: str) -> bool:
        program = plan.program_for(checkpoint)
        if program is None:
            return False
        slots = program.mask_slots.get(verdict_id, ())
        return any(
            pattern.search(text) is not None
            for slot, pattern in program.patterns_by_slot.items()
            if slot in slots
        )

    @staticmethod
    def _strongest(actions: Sequence[VerdictAction]) -> VerdictAction:
        return max(actions, key=_SEVERITY.__getitem__)


__all__ = ["FailMode", "ModelTier"]
