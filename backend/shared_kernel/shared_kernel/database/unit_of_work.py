"""Unit of work — the atomic boundary of one use case.

애플리케이션은 ``async with uow:`` 로 **경계만 선언한다.** 정상적으로 나가면 지속되고, 예외로
나가면 되돌아간다. ``commit``·``rollback`` 이라는 단어는 어댑터에만 있다 — 그것이 RDBMS 개념이고
애플리케이션이 알 필요가 없기 때문이다.

경계가 왜 애플리케이션에 있어야 하는가: 무엇이 함께 원자적이어야 하는지, 커밋 뒤에 무엇이 와야
하는지(발행 후 재컴파일), 어떤 부수 효과가 커밋 앞이어야 하는지(세션 회수)는 유스케이스만 안다.

여는 것은 여기가 아니다 — SQLAlchemy 가 첫 SQL 에서 autobegin 하고, 세션을 닫는 것은 이 객체를
만들어 넘긴 쪽(조립 루트의 ``async with session_factory()``)이다. 이 객체는 결과(커밋/롤백)만
정한다.
"""

from types import TracebackType
from typing import Protocol, Self

from sqlalchemy.ext.asyncio import AsyncSession


class UnitOfWork(Protocol):
    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class SqlAlchemyUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            await self._session.commit()
        else:
            await self._session.rollback()


__all__ = ["SqlAlchemyUnitOfWork", "UnitOfWork"]
