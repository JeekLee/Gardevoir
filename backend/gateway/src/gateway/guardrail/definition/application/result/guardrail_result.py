"""Guardrail read models.

``graph`` stays a plain dict. Modelling every node type in Pydantic would put a
second, drifting copy of the validation rules next to ``Node.validate()`` — and
the authoring API is not on the request path, so there is nothing to gain (§11.8).
"""

from datetime import datetime

from shared_kernel.api import CamelModel


class GuardrailSummary(CamelModel):
    name: str
    description: str
    latest_version_number: int | None
    has_draft: bool
    updated_at: datetime
    checkpoints: list[str]
    actions: list[str]
    check_count: int
    verdict_count: int


class GuardrailDetail(CamelModel):
    name: str
    version: str
    version_number: int | None
    description: str
    graph: dict
    created_at: datetime
    updated_at: datetime
