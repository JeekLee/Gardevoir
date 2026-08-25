"""Guardrail test command."""

from pydantic import Field

from gateway.guardrail.domain.models.guardrail import DRAFT_VERSION
from gateway.guardrail.domain.models.mode import Mode
from shared_kernel.api import CamelModel


class TestGuardrail(CamelModel):
    model: str = Field(min_length=1)
    messages: list[dict] = Field(min_length=1)
    version: str = DRAFT_VERSION
    mode: Mode = Mode.ENFORCE
