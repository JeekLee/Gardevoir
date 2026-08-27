"""Audit content setting tests."""

from gateway.settings import AuditSettings


def test_audit_excerpt_limit_has_a_default() -> None:
    """발췌 길이를 지정하지 않으면 증거를 남길 기본 상한을 쓴다."""
    settings = AuditSettings()

    assert settings.excerpt_max_chars == 256
