"""Guardrail authoring use cases.

Writes go through the Repository (it speaks aggregates, which publishing needs)
and every response is re-read through the Dao. Reading back is deliberate: the
create/update/publish responses then have exactly the shape the list and detail
screens have, so there is one projection to keep correct rather than four (§5).
"""

import logging
from typing import Protocol

from ulid import ULID

from gateway.guardrail.definition.application.command.guardrail_command import (
    CreateGuardrail,
    UpdateDraft,
)
from gateway.guardrail.definition.application.dao.guardrail_dao import GuardrailDao
from gateway.guardrail.definition.application.repository.guardrail_repository import (
    GuardrailRepository,
)
from gateway.guardrail.definition.application.result.guardrail_result import (
    GuardrailDetail,
    GuardrailSummary,
)
from gateway.guardrail.domain.exceptions.guardrail_error import GuardrailError
from gateway.guardrail.domain.models.guardrail import DRAFT_VERSION, Guardrail, require_valid_name
from gateway.guardrail.plan.application.compiler import compile_guardrail
from shared_kernel.api import Page
from shared_kernel.database import UnitOfWork

logger = logging.getLogger(__name__)


class PlanRefresher(Protocol):
    """계획 레지스트리에서 서비스가 쓰는 부분만.

    전체 레지스트리를 의존하면 서비스가 컴파일러·실행기까지 끌고 온다.
    """

    async def refresh(self, name: str) -> object | None: ...


class GuardrailService:
    def __init__(
        self,
        *,
        guardrail_repository: GuardrailRepository,
        guardrail_dao: GuardrailDao,
        unit_of_work: UnitOfWork,
        plan_refresher: PlanRefresher | None = None,
    ) -> None:
        self._guardrail_repository = guardrail_repository
        self._guardrail_dao = guardrail_dao
        self._unit_of_work = unit_of_work
        self._plan_refresher = plan_refresher

    async def create(self, cmd: CreateGuardrail) -> GuardrailDetail:
        draft = Guardrail.draft(name=cmd.name, description=cmd.description, graph=cmd.graph)
        _validate(draft)
        # 유일 제약이 DB 에도 있지만, IntegrityError 를 409 로 번역하는 것보다
        # 여기서 먼저 확인하는 편이 오류 메시지가 정확하다.
        async with self._unit_of_work:
            if await self._guardrail_repository.exists(cmd.name):
                GuardrailError.NAME_TAKEN.raise_(details={"name": cmd.name})
            await self._guardrail_repository.add(draft, id=_new_id())
            # 블록 안(=커밋 전)에서 읽는다 — 같은 세션이라 방금 쓴 것이 보이고 트랜잭션이
            # 하나로 유지된다. 커밋 뒤에 읽으면 읽기 트랜잭션이 새로 열려 응답 뒤에야
            # 닫히고, 그 열린 트랜잭션이 DDL 을 막는다.
            detail = await self._detail(cmd.name, DRAFT_VERSION)
        return detail

    async def update_draft(self, name: str, cmd: UpdateDraft) -> GuardrailDetail:
        draft = Guardrail.draft(name=name, description=cmd.description, graph=cmd.graph)
        _validate(draft)
        async with self._unit_of_work:
            # draft 가 없으면 repository 가 GUARDRAIL-008 을 올린다.
            await self._guardrail_repository.replace_draft(draft)
            detail = await self._detail(name, DRAFT_VERSION)
        return detail

    async def publish(self, name: str) -> GuardrailDetail:
        require_valid_name(name)
        async with self._unit_of_work:
            draft = await self._guardrail_repository.find_draft(name)
            if draft is None:
                GuardrailError.NO_DRAFT.raise_(details={"name": name})

            # 쓰기 전에 검증한다 — 실패한 발행이 행을 남기면 버전 열에 구멍이 생기고,
            # 감사 추적에서 "3번은 어디 갔나"를 설명할 수 없게 된다. 번호 자체는
            # max()+1 로 유도되므로 호출만으로 소모되지는 않는다.
            _validate(draft)

            version_number = await self._guardrail_repository.next_version_number(name)
            await self._guardrail_repository.add(draft.published_as(version_number), id=_new_id())
            # draft 행은 그대로 남는다 — 발행 후에도 계속 편집할 수 있어야 한다 (§6).
            detail = await self._detail(name, str(version_number))
        # 블록을 나가면 커밋됐다. 재컴파일은 그 뒤 — 레지스트리는 새 세션을 열기 때문에
        # 커밋 전에 부르면 아직 보이지 않는 행 대신 이전 버전을 컴파일한다.
        await self._recompile(name)
        return detail

    async def get_draft(self, name: str) -> GuardrailDetail:
        require_valid_name(name)
        detail = await self._guardrail_dao.get_detail(name, DRAFT_VERSION)
        if detail is None:
            GuardrailError.NO_DRAFT.raise_(details={"name": name})
        return detail

    async def get_latest(self, name: str) -> GuardrailDetail:
        """The newest published version. A guardrail with only a draft is a 404."""
        require_valid_name(name)
        detail = await self._guardrail_dao.get_latest_detail(name)
        if detail is None:
            GuardrailError.NOT_FOUND.raise_(details={"name": name})
        return detail

    async def get_version(self, name: str, version_number: int) -> GuardrailDetail:
        require_valid_name(name)
        return await self._detail(name, str(version_number))

    async def list(self) -> Page[GuardrailSummary]:
        items, total = await self._guardrail_dao.list_summaries()
        return Page[GuardrailSummary](items=items, total=total)

    # -- helpers ------------------------------------------------------------

    async def _recompile(self, name: str) -> None:
        """Refresh the in-process plan after the publish is committed.

        커밋 뒤여야 한다 — 레지스트리는 새 세션을 열기 때문에, 커밋 전에 부르면 아직
        보이지 않는 행 대신 이전 버전을 컴파일한다.

        실패해도 응답을 막지 않는다. 발행은 이미 커밋됐고 폴러가 다음 주기에 집어간다.
        컴파일 가능성은 쓰기 전에 이미 확인했으므로(``_validate``) 여기서 실패하는
        것은 예상 밖의 일이다.
        """
        if self._plan_refresher is None:
            return
        try:
            await self._plan_refresher.refresh(name)
        except Exception:
            logger.exception("recompiling %r failed; the poller will retry", name)

    async def _detail(self, name: str, version: str) -> GuardrailDetail:
        detail = await self._guardrail_dao.get_detail(name, version)
        if detail is None:
            GuardrailError.NOT_FOUND.raise_(details={"name": name, "version": version})
        return detail


def _validate(draft: Guardrail) -> None:
    """Validate the graph *and* that it compiles.

    컴파일까지 여기서 해보는 이유: 컴파일러만 아는 규칙이 있다 — 체크포인트를 섞는
    판정(``GUARDRAIL-013``), 위치를 알 수 없는 마스킹(``GUARDRAIL-014``). 저작 시점에
    확인하지 않으면 발행이 200 을 돌려주고도 계획은 그대로 남아, 운영자는 정책이
    바뀐 줄 알지만 실제로는 아무것도 바뀌지 않는다. 로그만 남는 조용한 실패다.

    비용은 발행당 1회 컴파일(§11.11 실측 0.8 ms)이고 요청 경로가 아니다.
    """
    draft.validate()
    compile_guardrail(draft)


def _new_id() -> str:
    """ULID — time-ordered, so rows sort by creation without a second column."""
    return str(ULID())
