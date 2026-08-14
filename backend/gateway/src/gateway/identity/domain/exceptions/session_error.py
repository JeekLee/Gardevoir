from shared_kernel.exception import ErrorCatalog, UnauthorizedError


class SessionError(ErrorCatalog):
    """회수·만료·미존재를 구분하지 않는다. 클라이언트가 할 일은 어느 쪽이든 재로그인이다."""

    INVALID = ("SESSION-001", "the refresh token is not valid", UnauthorizedError)
