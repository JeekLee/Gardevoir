from enum import StrEnum


class Scope(StrEnum):
    PROXY = "proxy"
    ADMIN = "admin"


__all__ = ["Scope"]
