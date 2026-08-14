"""ClickHouse client lifecycle.

``database/engine.py`` 와 같은 모양이다 — 설정을 기술하는 것(``ClickHouseSettings``)이
shared_kernel 에 있으므로 연결을 여는 것도 여기 있어야 한다. 조립 루트가 드라이버를
직접 임포트하고 설정을 필드별로 풀어 쓰면, 저장소 둘이 같은 자리에서 다른 모양이 된다.

**동기 드라이버다.** 이벤트 루프에서 부르면 안 된다 — 100행 삽입이 5~20 ms 동안 진행
중인 모든 요청을 막는다 (§10). 호출자가 ``asyncio.to_thread`` 로 감싼다.
"""

import clickhouse_connect
from clickhouse_connect.driver.client import Client

from shared_kernel.config import ClickHouseSettings

#: 열어둔 클라이언트. ``lru_cache`` 는 값을 꺼내주지 않으므로 따로 들고 있는다 —
#: engine.py 와 같은 이유다.
_clients: list[Client] = []


def get_clickhouse_client(settings: ClickHouseSettings) -> Client:
    client = clickhouse_connect.get_client(
        host=settings.host,
        port=settings.port,
        username=settings.user,
        password=settings.password,
        database=settings.database,
    )
    _clients.append(client)
    return client


def dispose_clickhouse() -> None:
    """열어둔 클라이언트를 전부 닫는다.

    ``dispose_engine`` 과 짝이다. 닫지 않으면 HTTP 커넥션 풀이 남는다 — 프로세스가
    그대로 죽는 배포에서는 티가 안 나지만, ``create_app()`` 을 반복하면 그대로 샌다.
    """
    while _clients:
        _clients.pop().close()


__all__ = ["dispose_clickhouse", "get_clickhouse_client"]
