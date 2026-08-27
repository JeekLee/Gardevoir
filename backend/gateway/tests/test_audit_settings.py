"""Audit privacy setting tests."""

from gateway.settings import AuditSettings


def test_audit_body_storage_is_disabled_by_default() -> None:
    """설정 누락으로 원문 저장이 켜지지 않는다."""
    settings = AuditSettings()

    assert settings.store_bodies is False
    assert settings.excerpt_max_chars == 256
