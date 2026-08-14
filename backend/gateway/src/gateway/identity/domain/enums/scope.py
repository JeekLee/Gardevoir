"""What a credential is allowed to reach.

⚠️ **ApiKey 의 관심사가 아니다.** 이 키는 "프록시를 호출할 수 있나"만 답하고, admin
표면의 인가는 회원 설계에서 별도 크레덴셜로 정한다 (§14). 그때까지만 여기 있다.
"""

from enum import StrEnum


class Scope(StrEnum):
    PROXY = "proxy"
    ADMIN = "admin"


__all__ = ["Scope"]
