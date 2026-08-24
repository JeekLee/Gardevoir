from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.identity.domain.enums.role import Role
from gateway.identity.domain.exceptions.user_error import UserError
from gateway.identity.domain.models.user import User
from gateway.identity.infrastructure.user_mapper import to_domain, to_model
from gateway.identity.infrastructure.user_model import UserModel


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_email(self, email: str) -> User | None:
        row = (
            await self._session.execute(select(UserModel).where(UserModel.email == email))
        ).scalar_one_or_none()
        return to_domain(row) if row is not None else None

    async def get(self, user_id: UUID) -> User | None:
        row = await self._session.get(UserModel, user_id)
        return to_domain(row) if row is not None else None

    async def add(self, user: User) -> None:
        self._session.add(to_model(user))
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # 서비스가 미리 확인하지만 확인과 제약 사이에 틈이 있다. 같은 이메일로 동시
            # 요청이 들어오면 지는 쪽이 500 이 아니라 409 를 받아야 한다. 번역이 여기
            # 있는 이유: IntegrityError 는 SQLAlchemy 타입이고 application 은 몰라야 한다.
            raise UserError.EMAIL_TAKEN.exception(details={"email": user.email}) from exc

    async def save(self, user: User) -> None:
        await self._session.execute(
            update(UserModel)
            .where(UserModel.id == user.id)
            .values(
                email=user.email,
                name=user.name,
                password_hash=user.password_hash.value,
                role=str(user.role),
                deactivated_at=user.deactivated_at,
            )
        )
        await self._session.flush()

    async def count_active_admins(self) -> int:
        return int(
            await self._session.scalar(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.role == str(Role.ADMIN), UserModel.deactivated_at.is_(None))
            )
            or 0
        )

    async def is_empty(self) -> bool:
        return not await self._session.scalar(select(select(UserModel.id).exists()))
