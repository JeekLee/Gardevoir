"""Composition root.

인프라 구현체와 fastapi.Depends 를 임포트하는 유일한 곳이다. presentation 은
여기서 서비스만 가져간다 (skills/gardevoir-be).
"""

from typing import Annotated

from fastapi import Depends, Request

from gateway.application.service.authentication_service import AuthenticationService
from gateway.application.service.proxy_service import ProxyService


def provide_authentication_service(request: Request) -> AuthenticationService:
    # 캐시 리포지토리는 프로세스 수명 동안 유지되어야 하므로 app.state 가 소유한다.
    return AuthenticationService(keys=request.app.state.key_cache)


def provide_proxy_service(request: Request) -> ProxyService:
    return ProxyService(
        upstream=request.app.state.upstream,
        audit=request.app.state.audit_sink,
    )


AuthenticationServiceDep = Annotated[AuthenticationService, Depends(provide_authentication_service)]
ProxyServiceDep = Annotated[ProxyService, Depends(provide_proxy_service)]
