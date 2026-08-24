"""로그인 · 갱신 · 로그아웃."""

import logging
from datetime import timedelta

from gateway.identity.application.command.user_command import Login, Refresh
from gateway.identity.application.dao.user_dao import UserDao
from gateway.identity.application.port.access_token_issuer import AccessTokenIssuer
from gateway.identity.application.repository.refresh_session_repository import (
    RefreshSessionRepository,
)
from gateway.identity.application.repository.user_repository import UserRepository
from gateway.identity.application.result.user_result import LoginResult, TokenPair
from gateway.identity.domain.exceptions.session_error import SessionError
from gateway.identity.domain.exceptions.user_error import UserError
from gateway.identity.domain.models.refresh_session import RefreshSession
from gateway.identity.domain.models.user import User, normalise_email
from shared_kernel.database import UnitOfWork

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        user_dao: UserDao,
        refresh_session_repository: RefreshSessionRepository,
        access_token_issuer: AccessTokenIssuer,
        refresh_ttl: timedelta,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._user_repository = user_repository
        self._user_dao = user_dao
        self._refresh_session_repository = refresh_session_repository
        self._access_token_issuer = access_token_issuer
        self._refresh_ttl = refresh_ttl
        self._unit_of_work = unit_of_work

    async def login(self, cmd: Login) -> LoginResult:
        user = await self._user_repository.find_by_email(normalise_email(cmd.email))
        if user is None:
            UserError.INVALID_CREDENTIALS.raise_()
        user.authenticate(cmd.password.get_secret_value())

        async with self._unit_of_work:
            pair = await self._issue(user)
            summary = await self._user_dao.get_summary(user.id)
        assert summary is not None
        logger.info("user %s logged in", user.email)
        return LoginResult(tokens=pair, user=summary)

    async def refresh(self, cmd: Refresh) -> TokenPair:
        """회전한다 — 옛 세션을 회수하고 새로 발급한다.

        회전하지 않으면 탈취된 리프레시 토큰을 만료까지 계속 쓸 수 있다.
        """
        session = await self._refresh_session_repository.find_by_token(cmd.refresh_token)
        if session is None:
            SessionError.INVALID.raise_()
        session.ensure_active()

        async with self._unit_of_work:
            user = await self._user_repository.get(session.user_id)
            if user is None:
                SessionError.INVALID.raise_()
            user.ensure_active()
            await self._refresh_session_repository.remove(session)
            pair = await self._issue(user)
        return pair

    async def logout(self, refresh_token: str) -> None:
        # 순수 Redis 다 — Postgres 를 건드리지 않으므로 커밋 경계가 없다.
        session = await self._refresh_session_repository.find_by_token(refresh_token)
        if session is not None:
            await self._refresh_session_repository.remove(session)

    async def _issue(self, user: User) -> TokenPair:
        session = RefreshSession.issue(user_id=user.id, ttl=self._refresh_ttl)
        await self._refresh_session_repository.add(session)
        return TokenPair(
            access_token=self._access_token_issuer.encode(
                user_id=user.id, email=user.email, role=user.role
            ),
            refresh_token=session.token,
            expires_in=self._access_token_issuer.ttl_seconds,
        )


__all__ = ["AuthService"]
