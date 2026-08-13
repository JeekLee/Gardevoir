"""Guardrail authoring use cases.

Writes go through the Repository (it speaks aggregates, which publishing needs)
and every response is re-read through the Dao. Reading back is deliberate: the
create/update/publish responses then have exactly the shape the list and detail
screens have, so there is one projection to keep correct rather than four (§5).
"""

from ulid import ULID

from gateway.application.command.guardrail_command import CreateGuardrail, UpdateDraft
from gateway.application.dao.guardrail_dao import GuardrailDao
from gateway.application.repository.guardrail_repository import GuardrailRepository
from gateway.application.result.guardrail_result import GuardrailDetail, GuardrailSummary
from gateway.domain.exception.guardrail_error import GuardrailError
from gateway.domain.models.guardrail import DRAFT_VERSION, Guardrail
from shared_kernel.api import Page


class GuardrailService:
    def __init__(self, *, guardrails: GuardrailRepository, dao: GuardrailDao) -> None:
        self._guardrails = guardrails
        self._dao = dao

    async def create(self, cmd: CreateGuardrail) -> GuardrailDetail:
        draft = Guardrail.draft(cmd.name, cmd.graph)
        draft.validate()
        # 유일 제약이 DB 에도 있지만, IntegrityError 를 409 로 번역하는 것보다
        # 여기서 먼저 확인하는 편이 오류 메시지가 정확하다.
        if await self._guardrails.exists(cmd.name):
            GuardrailError.NAME_TAKEN.raise_(details={"name": cmd.name})
        await self._guardrails.add(draft, id=_new_id())
        return await self._detail(cmd.name, DRAFT_VERSION)

    async def update_draft(self, name: str, cmd: UpdateDraft) -> GuardrailDetail:
        draft = Guardrail.draft(name, cmd.graph)
        draft.validate()
        # draft 가 없으면 repository 가 GUARDRAIL-008 을 올린다.
        await self._guardrails.replace_draft(draft)
        return await self._detail(name, DRAFT_VERSION)

    async def publish(self, name: str) -> GuardrailDetail:
        draft = await self._guardrails.find_draft(name)
        if draft is None:
            GuardrailError.NO_DRAFT.raise_(details={"name": name})

        # 번호를 배정하기 전에 검증한다. 검증 실패가 번호를 소모하면 버전 열에
        # 구멍이 생기고, 감사 추적에서 "3번은 어디 갔나"를 설명할 수 없게 된다.
        draft.validate()

        version_number = await self._guardrails.next_version_number(name)
        await self._guardrails.add(draft.published_as(version_number), id=_new_id())
        # draft 행은 그대로 남는다 — 발행 후에도 계속 편집할 수 있어야 한다 (§6).
        return await self._detail(name, str(version_number))

    async def get_draft(self, name: str) -> GuardrailDetail:
        detail = await self._dao.get_detail(name, DRAFT_VERSION)
        if detail is None:
            GuardrailError.NO_DRAFT.raise_(details={"name": name})
        return detail

    async def get_latest(self, name: str) -> GuardrailDetail:
        """The newest published version. A guardrail with only a draft is a 404."""
        detail = await self._dao.get_latest_detail(name)
        if detail is None:
            GuardrailError.NOT_FOUND.raise_(details={"name": name})
        return detail

    async def get_version(self, name: str, version_number: int) -> GuardrailDetail:
        return await self._detail(name, str(version_number))

    async def list(self) -> Page[GuardrailSummary]:
        items, total = await self._dao.list_summaries()
        return Page[GuardrailSummary](items=items, total=total)

    # -- helpers ------------------------------------------------------------

    async def _detail(self, name: str, version: str) -> GuardrailDetail:
        detail = await self._dao.get_detail(name, version)
        if detail is None:
            GuardrailError.NOT_FOUND.raise_(details={"name": name, "version": version})
        return detail


def _new_id() -> str:
    """ULID — time-ordered, so rows sort by creation without a second column."""
    return str(ULID())
