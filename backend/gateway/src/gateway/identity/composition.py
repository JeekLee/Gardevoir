"""Identity 의 요청 수명 배선.

**조립 루트는 여기가 아니라 ``app.py`` 다.** 프로세스 수명 객체 그래프(엔진, 캐시,
싱크, 레지스트리)는 lifespan 이 만들고, 이 파일은 그것을 요청 하나에 맞춰 꺼내 쓴다 —
모든 함수가 ``Request`` 를 받는 것이 그 증거다.

``presentation/`` 이 아니라 여기 있는 이유: 자기 컨텍스트의 ``SqlAlchemy*`` 를
임포트해야 한다. presentation 에 두면 "라우터는 infrastructure 를 임포트하지 않는다"
규칙에 예외가 생기고, 예외는 곧 사각지대가 된다.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request

from gateway.identity.application.api_key_service import ApiKeyService
from gateway.identity.application.authentication_service import AuthenticationService
from gateway.identity.domain.api_key import Scope
from gateway.identity.infrastructure.api_key_dao import SqlAlchemyApiKeyDao
from gateway.identity.infrastructure.api_key_repository import SqlAlchemyApiKeyRepository


def provide_authentication_service(request: Request) -> AuthenticationService:
    # 캐시 리포지토리는 프로세스 수명 동안 유지되어야 하므로 app.state 가 소유한다.
    return AuthenticationService(keys=request.app.state.key_cache)


async def provide_api_key_service(request: Request) -> AsyncIterator[ApiKeyService]:
    """One session per request, committed only on the success path.

    라우트가 예외를 올리면 FastAPI 가 그 예외를 yield 지점으로 다시 던지므로 commit 에
    도달하지 않고, ``async with`` 가 세션을 닫으면서 롤백된다. 관리 API 는 요청 경로가
    아니므로 요청마다 세션을 열어도 된다 (§6 은 프록시 경로에만 적용된다).
    """
    async with request.app.state.session_factory() as session:
        yield ApiKeyService(
            keys=SqlAlchemyApiKeyRepository(session),
            dao=SqlAlchemyApiKeyDao(session),
            # 발급·회수는 응답 전에 커밋돼야 한다. 정리 코드에 맡기면 FastAPI 가
            # 응답을 보낸 뒤에 커밋한다.
            transaction=session,
        )
        await session.commit()


AuthenticationServiceDep = Annotated[AuthenticationService, Depends(provide_authentication_service)]
ApiKeyServiceDep = Annotated[ApiKeyService, Depends(provide_api_key_service)]


async def require_admin_scope(request: Request, auth_service: AuthenticationServiceDep) -> None:
    """Demand the admin scope before a handler runs.

    스코프 검사는 identity 의 일이므로 여기 있다. 다른 컨텍스트의 admin 라우터가 이것을
    임포트하면 "그 API 는 identity 의 스코프 검사로 보호된다"가 코드에 드러난다.

    라우터 레벨 의존성이어야 한다. 핸들러 첫 줄에 두면 FastAPI 가 그 전에 본문을
    검증하므로, 크레덴셜이 없는 호출자가 401 대신 422 를 받고 스키마를 알아낸다.
    라우트마다 반복하는 한 줄이 아니라 라우터에 한 번 걸어야 새 라우트가 빠뜨릴 수도 없다.

    가드레일을 해석하지 않는다 — 관리 API 에는 해석할 가드레일이 없다.
    """
    await auth_service.authorise(
        authorization=request.headers.get("authorization"), require=Scope.ADMIN
    )


#: 라우터의 ``dependencies=`` 에 넣는다. ``Depends`` 는 composition 밖으로 나가지 않는다.
AdminScopeDep = Depends(require_admin_scope)
