"""Redis 리프레시 세션 저장소.

    gardevoir:session:{token}          세션 하나. TTL 이 만료를 처리한다
    gardevoir:user-sessions:{user_id}  그 사용자의 토큰 집합

집합이 필요한 이유는 ``remove_all_for_user`` 다. 키 공간을 ``SCAN`` 하면 세션 수가 아니라
전체 키 수에 비례한다.
"""

from datetime import UTC, datetime
from uuid import UUID

import orjson
from redis.asyncio import Redis

from gateway.identity.domain.models.refresh_session import RefreshSession

_SESSION = "gardevoir:session:{}"
_USER_SESSIONS = "gardevoir:user-sessions:{}"


class RedisRefreshSessionRepository:
    def __init__(self, client: Redis) -> None:
        self._redis = client

    async def find_by_token(self, token: str) -> RefreshSession | None:
        raw = await self._redis.get(_SESSION.format(token))
        if raw is None:
            return None
        data = orjson.loads(raw)
        return RefreshSession(
            id=UUID(data["id"]),
            user_id=UUID(data["user_id"]),
            token=token,
            expires_at=datetime.fromisoformat(data["expires_at"]),
        )

    async def add(self, session: RefreshSession) -> None:
        ttl = int((session.expires_at - datetime.now(UTC)).total_seconds())
        if ttl <= 0:
            return
        index = _USER_SESSIONS.format(session.user_id)
        pipe = self._redis.pipeline()
        pipe.set(
            _SESSION.format(session.token),
            orjson.dumps(
                {
                    "id": str(session.id),
                    "user_id": str(session.user_id),
                    "expires_at": session.expires_at.isoformat(),
                }
            ),
            ex=ttl,
        )
        pipe.sadd(index, session.token)
        # 집합에도 TTL 을 걸어 둔다. 자연 만료된 멤버가 남더라도 집합 자체가 사라진다.
        pipe.expire(index, ttl, gt=True)
        await pipe.execute()

    async def remove(self, session: RefreshSession) -> None:
        pipe = self._redis.pipeline()
        pipe.delete(_SESSION.format(session.token))
        pipe.srem(_USER_SESSIONS.format(session.user_id), session.token)
        await pipe.execute()

    async def remove_all_for_user(self, user_id: UUID) -> None:
        index = _USER_SESSIONS.format(user_id)
        tokens = await self._redis.smembers(index)
        pipe = self._redis.pipeline()
        for token in tokens:
            pipe.delete(_SESSION.format(token))
        pipe.delete(index)
        await pipe.execute()
