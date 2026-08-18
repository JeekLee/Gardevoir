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
from shared_kernel.database import Commit

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
        guardrails: GuardrailRepository,
        dao: GuardrailDao,
        commit: Commit,
        plans: PlanRefresher | None = None,
    ) -> None:
        self._guardrails = guardrails
        self._dao = dao
        self._commit = commit
        self._plans = plans

    async def create(self, cmd: CreateGuardrail) -> GuardrailDetail:
        draft = Guardrail.draft(cmd.name, cmd.graph)
        _validate(draft)
        # 유일 제약이 DB 에도 있지만, IntegrityError 를 409 로 번역하는 것보다
        # 여기서 먼저 확인하는 편이 오류 메시지가 정확하다.
        if await self._guardrails.exists(cmd.name):
            GuardrailError.NAME_TAKEN.raise_(details={"name": cmd.name})
        await self._guardrails.add(draft, id=_new_id())
        # 커밋 전에 읽는다 — 같은 세션이므로 방금 쓴 것이 보이고, 트랜잭션이 하나로
        # 유지된다. 커밋 뒤에 읽으면 읽기 트랜잭션이 새로 열려서 응답이 나간 뒤에야
        # 닫힌다 (조립 루트의 정리 코드에서). 그 열린 트랜잭션이 DDL 을 막는다.
        detail = await self._detail(cmd.name, DRAFT_VERSION)
        await self._commit()
        return detail

    async def update_draft(self, name: str, cmd: UpdateDraft) -> GuardrailDetail:
        draft = Guardrail.draft(name, cmd.graph)
        _validate(draft)
        # draft 가 없으면 repository 가 GUARDRAIL-008 을 올린다.
        await self._guardrails.replace_draft(draft)
        detail = await self._detail(name, DRAFT_VERSION)
        await self._commit()
        return detail

    async def publish(self, name: str) -> GuardrailDetail:
        require_valid_name(name)
        draft = await self._guardrails.find_draft(name)
        if draft is None:
            GuardrailError.NO_DRAFT.raise_(details={"name": name})

        # 쓰기 전에 검증한다 — 실패한 발행이 행을 남기면 버전 열에 구멍이 생기고,
        # 감사 추적에서 "3번은 어디 갔나"를 설명할 수 없게 된다. 번호 자체는
        # max()+1 로 유도되므로 호출만으로 소모되지는 않는다.
        _validate(draft)

        version_number = await self._guardrails.next_version_number(name)
        await self._guardrails.add(draft.published_as(version_number), id=_new_id())
        # draft 행은 그대로 남는다 — 발행 후에도 계속 편집할 수 있어야 한다 (§6).
        detail = await self._detail(name, str(version_number))
        await self._commit()
        # 커밋 뒤에 재컴파일한다 — 레지스트리는 새 세션을 열기 때문에 커밋 전에
        # 부르면 아직 보이지 않는 행 대신 이전 버전을 컴파일한다.
        await self._recompile(name)
        return detail

    async def get_draft(self, name: str) -> GuardrailDetail:
        require_valid_name(name)
        detail = await self._dao.get_detail(name, DRAFT_VERSION)
        if detail is None:
            GuardrailError.NO_DRAFT.raise_(details={"name": name})
        return detail

    async def get_latest(self, name: str) -> GuardrailDetail:
        """The newest published version. A guardrail with only a draft is a 404."""
        require_valid_name(name)
        detail = await self._dao.get_latest_detail(name)
        if detail is None:
            GuardrailError.NOT_FOUND.raise_(details={"name": name})
        return detail

    async def get_version(self, name: str, version_number: int) -> GuardrailDetail:
        require_valid_name(name)
        return await self._detail(name, str(version_number))

    async def list(self) -> Page[GuardrailSummary]:
        items, total = await self._dao.list_summaries()
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
        if self._plans is None:
            return
        try:
            await self._plans.refresh(name)
        except Exception:
            logger.exception("recompiling %r failed; the poller will retry", name)

    async def _detail(self, name: str, version: str) -> GuardrailDetail:
        detail = await self._dao.get_detail(name, version)
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
