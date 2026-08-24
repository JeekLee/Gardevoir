"""Authorization error catalog.

토큰 검증·역할 검사 실패는 인가 관심사라 여기 산다 — 사용자 관리 에러(UserError)와 다르다.
서버가 쪼개지면 검증측(가드)이 이 카탈로그를 쓴다.
"""

from shared_kernel.exception import ErrorCatalog, ForbiddenError, UnauthorizedError


class AuthError(ErrorCatalog):
    INVALID_TOKEN = ("AUTH-001", "the access token is not valid", UnauthorizedError)
    ROLE_REQUIRED = ("AUTH-002", "this action requires a different role", ForbiddenError)


__all__ = ["AuthError"]
