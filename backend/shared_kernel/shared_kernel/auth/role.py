from enum import StrEnum


class Role(StrEnum):
    """ADMIN 은 사용자와 역할을 관리한다. 그 밖의 운영은 활성 사용자 전원이 한다.

    인가 어휘라 여러 컨텍스트가 공유한다 — 발급측(User.role)과 검증측(require_role) 양쪽이
    쓴다. 그래서 도메인이 아니라 shared_kernel 에 산다 (서버가 쪼개져도 하류가 이 어휘를
    알아야 한다).
    """

    ADMIN = "admin"
    USER = "user"


__all__ = ["Role"]
