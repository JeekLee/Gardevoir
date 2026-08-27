"""Runtime-independent contract for policy-adaptive model judgement."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class JudgeRequest:
    checkpoint: str
    node_id: str
    policy: str
    text: str
    strictness: str
    deadline_ms: int


@dataclass(frozen=True, slots=True)
class JudgeResult:
    node_id: str
    violated: bool | None
    score: float | None
    raw_label: str


class ModelJudge(Protocol):
    async def judge(self, requests: Sequence[JudgeRequest]) -> Sequence[JudgeResult]: ...


__all__ = ["JudgeRequest", "JudgeResult", "ModelJudge"]
