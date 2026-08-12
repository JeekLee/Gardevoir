import os

import pytest
from pydantic import ValidationError

from gateway.settings import GatewaySettings, get_settings


def _env(monkeypatch, **extra):
    """Give the test a clean, hermetic environment.

    개발자 셸의 GARDEVOIR_* 변수나 패키지에 놓인 .env 파일이 남아 있으면
    기본값 단정이 조용히 깨진다. 두 경로를 모두 차단한다.
    """
    for name in [k for k in os.environ if k.startswith("GARDEVOIR_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GARDEVOIR_APP_NAME", "gateway")
    monkeypatch.setenv("GARDEVOIR_DATABASE__DSN", "postgresql+psycopg://u:p@h:5432/d")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def _settings(**kwargs) -> GatewaySettings:
    return GatewaySettings(_env_file=None, **kwargs)


def test_gateway_defaults(monkeypatch):
    _env(monkeypatch)
    s = _settings()
    assert s.app_name == "gateway"
    assert s.upstream_timeout_s == 120.0
    assert s.key_cache_ttl_s == 30.0
    assert s.audit_batch_size == 100
    assert s.audit_flush_interval_s == 1.0
    assert s.audit_queue_maxsize == 10_000
    assert s.stream_holdback_tokens == 32


def test_inherits_shared_kernel_nested_settings(monkeypatch):
    _env(monkeypatch, GARDEVOIR_CLICKHOUSE__PORT="21020")
    s = _settings()
    assert s.clickhouse.port == 21020
    assert s.clickhouse.host == "localhost"
    assert s.log.level == "INFO"


def test_gateway_field_reads_prefixed_env(monkeypatch):
    _env(monkeypatch, GARDEVOIR_KEY_CACHE_TTL_S="5.5")
    assert _settings().key_cache_ttl_s == 5.5


def test_negative_holdback_is_rejected(monkeypatch):
    """홀드백이 음수면 스트리밍 방출 계산이 조용히 망가진다."""
    _env(monkeypatch, GARDEVOIR_STREAM_HOLDBACK_TOKENS="-1")
    with pytest.raises(ValidationError):
        _settings()


def test_zero_holdback_is_allowed(monkeypatch):
    """0은 즉시 방출(사후 검출) 모드로 유효한 설정이다 (§9)."""
    _env(monkeypatch, GARDEVOIR_STREAM_HOLDBACK_TOKENS="0")
    assert _settings().stream_holdback_tokens == 0


def test_non_positive_timeout_is_rejected(monkeypatch):
    _env(monkeypatch, GARDEVOIR_UPSTREAM_TIMEOUT_S="0")
    with pytest.raises(ValidationError):
        _settings()


def test_get_settings_is_cached(monkeypatch):
    _env(monkeypatch)
    assert get_settings() is get_settings()
