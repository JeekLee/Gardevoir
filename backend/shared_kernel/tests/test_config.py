import os

import pytest
from pydantic import ValidationError

from shared_kernel.config import BaseAppSettings, ClickHouseSettings, DatabaseSettings, LogSettings


class AppSettings(BaseAppSettings):
    """A BC subclasses BaseAppSettings and adds its own fields."""

    upstream_timeout_s: float = 120.0


def _env(monkeypatch, **extra):
    """Give the test a clean, hermetic environment.

    개발자 셸의 GARDEVOIR_* 변수나 패키지에 놓인 .env 파일이 남아 있으면
    기본값 단정이 조용히 깨진다. 두 경로를 모두 차단한다.
    """
    for name in [k for k in os.environ if k.startswith("GARDEVOIR_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GARDEVOIR_APP_NAME", "gateway")
    monkeypatch.setenv("GARDEVOIR_DATABASE__DSN", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("GARDEVOIR_CLICKHOUSE__HOST", "ch.local")
    for k, v in extra.items():
        monkeypatch.setenv(k, v)


def _settings(**kwargs) -> AppSettings:
    """Build settings without reading any .env file from the working directory."""
    return AppSettings(_env_file=None, **kwargs)


def test_nested_settings_use_double_underscore(monkeypatch):
    _env(monkeypatch)
    s = _settings()
    assert s.app_name == "gateway"
    assert s.database.dsn == "postgresql+psycopg://u:p@h:5432/d"
    assert s.clickhouse.host == "ch.local"


def test_partial_nested_env_keeps_sibling_defaults(monkeypatch):
    """GARDEVOIR_CLICKHOUSE__HOST 하나만 줘도 나머지 필드는 기본값을 유지해야 한다."""
    _env(monkeypatch)
    s = _settings()
    assert s.clickhouse.host == "ch.local"
    assert s.clickhouse.port == 8123
    assert s.clickhouse.user == "gardevoir"


def test_defaults(monkeypatch):
    _env(monkeypatch)
    s = _settings()
    assert s.debug is False
    assert s.database.echo is False
    assert s.clickhouse.port == 8123
    assert s.clickhouse.user == "gardevoir"
    assert s.clickhouse.database == "gardevoir"
    assert s.log.level == "INFO"
    assert s.log.json_output is True
    assert s.upstream_timeout_s == 120.0


def test_subclass_field_reads_prefixed_env(monkeypatch):
    _env(monkeypatch, GARDEVOIR_UPSTREAM_TIMEOUT_S="7.5")
    assert _settings().upstream_timeout_s == 7.5


def test_missing_required_dsn_fails_loudly(monkeypatch):
    _env(monkeypatch)
    monkeypatch.delenv("GARDEVOIR_DATABASE__DSN", raising=False)
    with pytest.raises(ValidationError):
        _settings()


def test_log_level_is_validated_at_load_not_at_use(monkeypatch):
    """오타가 configure_logging의 'Unknown level'이 아니라 설정 로드에서 잡혀야 한다."""
    _env(monkeypatch, GARDEVOIR_LOG__LEVEL="verbose")
    with pytest.raises(ValidationError) as info:
        _settings()
    assert "level" in str(info.value)


def test_log_level_accepts_lowercase(monkeypatch):
    _env(monkeypatch, GARDEVOIR_LOG__LEVEL="debug")
    assert _settings().log.level == "DEBUG"


def test_unknown_env_is_ignored(monkeypatch):
    _env(monkeypatch, GARDEVOIR_TOTALLY_UNKNOWN="x")
    _settings()  # 예외가 나면 실패


def test_nested_models_are_usable_standalone():
    db = DatabaseSettings(dsn="postgresql+psycopg://u:p@h:5432/d")
    ch = ClickHouseSettings(host="h")
    log = LogSettings()
    assert db.echo is False
    assert ch.port == 8123
    assert log.level == "INFO"
