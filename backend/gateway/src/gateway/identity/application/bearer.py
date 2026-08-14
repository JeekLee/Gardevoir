"""Authorization 헤더 파싱. ``"Bearer "`` 는 RFC 6750 의 형식이다."""


def parse_bearer(header: str | None) -> str | None:
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


__all__ = ["parse_bearer"]
