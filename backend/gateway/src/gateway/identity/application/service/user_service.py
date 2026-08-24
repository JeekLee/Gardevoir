"""사용자 관리. 생성은 관리자만 한다 — 공개 가입이 없다."""

import logging
from uuid import UUID

from gateway.identity.application.command.user_command import (
    ChangePassword,
    ChangeRole,
    CreateUser,
    UpdateUser,
)
from gateway.identity.application.dao.user_dao import UserDao
from gateway.identity.application.repository.refresh_session_repository import (
    RefreshSessionRepository,
)
from gateway.identity.application.repository.user_repository import UserRepository
from gateway.identity.application.result.user_result import UserSummary
from gateway.identity.domain.enums.role import Role
from gateway.identity.domain.exceptions.user_error import UserError
from gateway.identity.domain.models.user import User, normalise_email
from shared_kernel.api import Page
from shared_kernel.database import UnitOfWork

logger = logging.getLogger(__name__)


class UserService:
    def __init__(
        self,
        *,
        users: UserRepository,
        dao: UserDao,
        sessions: RefreshSessionRepository,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._dao = dao
        self._sessions = sessions
        self._uow = uow

    async def create(self, cmd: CreateUser) -> UserSummary:
        email = normalise_email(cmd.email)
        # 해싱은 트랜잭션 밖에서 — scrypt 는 무겁고 DB 를 건드리지 않는다.
        user = User.register(
            email=email,
            name=cmd.name,
            password=cmd.password.get_secret_value(),
            role=cmd.role,
        )
        async with self._uow:
            if await self._users.find_by_email(email) is not None:
                UserError.EMAIL_TAKEN.raise_(details={"email": email})
            await self._users.add(user)
            summary = await self._summary(user.id)
        logger.info("user %s created with role %s", user.email, user.role)
        return summary

    async def get(self, user_id: UUID) -> UserSummary:
        summary = await self._dao.get_summary(user_id)
        if summary is None:
            UserError.NOT_FOUND.raise_(details={"id": str(user_id)})
        return summary

    async def list(self) -> Page[UserSummary]:
        items, total = await self._dao.list_summaries()
        return Page(items=items, total=total)

    async def update(self, user_id: UUID, cmd: UpdateUser) -> UserSummary:
        user = await self._load(user_id)
        email = normalise_email(cmd.email)
        async with self._uow:
            if email != user.email and await self._users.find_by_email(email) is not None:
                UserError.EMAIL_TAKEN.raise_(details={"email": email})
            await self._users.save(user.update(email=email, name=cmd.name))
            return await self._summary(user_id)

    async def change_password(self, user_id: UUID, cmd: ChangePassword) -> None:
        """본인이 바꾼다. 성공하면 그 사용자의 세션을 전부 끊는다."""
        user = await self._load(user_id)
        if not user.password_hash.matches(cmd.current_password.get_secret_value()):
            UserError.WRONG_CURRENT_PASSWORD.raise_()
        async with self._uow:
            await self._users.save(user.set_password(cmd.new_password.get_secret_value()))
            # 회수는 커밋(블록 종료) 앞이다. 뒤집으면 비밀번호는 바뀌고 옛 세션이 살아있는
            # 창이 생긴다. Redis 는 트랜잭션에 못 드니 순서로 안전한 쪽에 떨어뜨린다.
            await self._sessions.remove_all_for_user(user_id)

    async def change_role(self, user_id: UUID, cmd: ChangeRole) -> UserSummary:
        user = await self._load(user_id)
        if user.role is Role.ADMIN and cmd.role is not Role.ADMIN:
            await self._reject_if_last_admin()
        async with self._uow:
            await self._users.save(user.change_role(cmd.role))
            return await self._summary(user_id)

    async def deactivate(self, user_id: UUID) -> UserSummary:
        user = await self._load(user_id)
        if user.role is Role.ADMIN:
            await self._reject_if_last_admin()
        async with self._uow:
            await self._users.save(user.deactivate())
            # change_password 와 같은 이유로 회수가 커밋 앞이다.
            await self._sessions.remove_all_for_user(user_id)
            return await self._summary(user_id)

    async def ensure_root(self, *, email: str, password: str) -> bool:
        """사용자가 하나도 없을 때만 루트 계정을 만든다."""
        if not await self._users.is_empty():
            return False
        user = User.register(
            email=normalise_email(email), name="root", password=password, role=Role.ADMIN
        )
        async with self._uow:
            await self._users.add(user)
        logger.warning("root account %s created from settings", user.email)
        return True

    async def _load(self, user_id: UUID) -> User:
        user = await self._users.get(user_id)
        if user is None:
            UserError.NOT_FOUND.raise_(details={"id": str(user_id)})
        return user

    async def _reject_if_last_admin(self) -> None:
        if await self._users.count_active_admins() <= 1:
            UserError.LAST_ADMIN.raise_()

    async def _summary(self, user_id: UUID) -> UserSummary:
        summary = await self._dao.get_summary(user_id)
        assert summary is not None
        return summary


__all__ = ["UserService"]
