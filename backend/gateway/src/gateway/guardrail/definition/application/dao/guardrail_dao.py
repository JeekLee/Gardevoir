"""Guardrail read interface."""

from typing import Protocol

from gateway.guardrail.definition.application.result.guardrail_result import (
    GuardrailDetail,
    GuardrailSummary,
)


class GuardrailDao(Protocol):
    async def get_detail(self, name: str, version: str) -> GuardrailDetail | None: ...

    async def get_latest_detail(self, name: str) -> GuardrailDetail | None:
        """최신 발행본. draft 만 있으면 ``None``."""
        ...

    async def list_summaries(self) -> tuple[list[GuardrailSummary], int]:
        """``(items, total)``. 한 이름당 한 행 — 행이 아니라 가드레일을 센다."""
        ...
