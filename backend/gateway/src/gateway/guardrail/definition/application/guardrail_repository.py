"""Guardrail write interface.

Repository speaks in domain aggregates because publishing needs the graph's
behaviour — ``validate()`` and ``published_as()`` — not a flat projection. The
read side is ``application/dao/guardrail_dao.py`` and returns Result DTOs (§5).
"""

from typing import Protocol

from gateway.guardrail.domain.guardrail import Guardrail


class GuardrailRepository(Protocol):
    async def add(self, guardrail: Guardrail, *, id: str) -> None: ...

    async def exists(self, name: str) -> bool: ...

    async def find_draft(self, name: str) -> Guardrail | None: ...

    async def find_published(
        self, name: str, version_number: int | None = None
    ) -> Guardrail | None:
        """``version_number=None`` 이면 최신 발행본."""
        ...

    async def replace_draft(self, guardrail: Guardrail) -> None: ...

    async def next_version_number(self, name: str) -> int: ...
