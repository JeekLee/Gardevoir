"""User error catalog."""

from shared_kernel.exception import (
    ConflictError,
    ErrorCatalog,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


class UserError(ErrorCatalog):
    #: 로그인 실패는 **한 가지 코드**로만 답한다. "없는 이메일"과 "틀린 비밀번호"를
    #: 구분해 주면 이메일 존재 여부를 탐색할 수 있다 (계정 열거).
    INVALID_CREDENTIALS = ("USER-001", "email or password is incorrect", UnauthorizedError)
    DEACTIVATED = ("USER-002", "this account has been deactivated", UnauthorizedError)
    EMAIL_TAKEN = ("USER-003", "an account with this email already exists", ConflictError)
    WEAK_PASSWORD = ("USER-004", "the password is too short", ValidationError)
    NOT_ADMIN = ("USER-005", "this action requires the admin role", ForbiddenError)
    NOT_FOUND = ("USER-009", "no such user", NotFoundError)
    INVALID_TOKEN = ("USER-006", "the access token is not valid", UnauthorizedError)
    LAST_ADMIN = (
        "USER-007",
        "the last active admin cannot be demoted or deactivated",
        ConflictError,
    )
    WRONG_CURRENT_PASSWORD = ("USER-008", "the current password is incorrect", UnauthorizedError)
