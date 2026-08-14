from enum import StrEnum


class Role(StrEnum):
    """ADMIN 은 사용자와 역할을 관리한다. 그 밖의 운영은 활성 사용자 전원이 한다."""

    ADMIN = "admin"
    USER = "user"


__all__ = ["Role"]
