"""How a request is to be handled.

와이어가 아니라 **도메인** 어휘다. dry-run 은 "검사는 전부 돌리되 아무것도 집행하지
않는다"이고, 그 판단은 검사기가 한다 — 헤더는 그것을 전달하는 수단일 뿐이다.
"""

from enum import StrEnum


class Mode(StrEnum):
    ENFORCE = "enforce"
    DRY_RUN = "dry-run"

    @classmethod
    def parse(cls, raw: str | None) -> Mode:
        """Unknown or missing values fall back to enforce — never fail open."""
        if not raw:
            return cls.ENFORCE
        try:
            return cls(raw.strip().lower())
        except ValueError:
            return cls.ENFORCE


__all__ = ["Mode"]
