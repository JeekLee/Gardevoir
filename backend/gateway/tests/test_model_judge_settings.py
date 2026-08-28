"""Model judgement configuration gate tests."""

import pytest
from pydantic import ValidationError

from gateway.settings import ModelJudgeSettings


def test_model_judge_is_disabled_and_input_fail_closed_by_default() -> None:
    """미설정 배포는 모델을 호출하지 않고, enabled 실패 기본만 closed다."""
    settings = ModelJudgeSettings()

    assert settings.enabled is False
    assert settings.endpoint == ""
    assert settings.fail_mode.input == "closed"
    assert settings.max_images == 4
    assert settings.max_data_uri_bytes == 5_242_880


def test_enabled_model_judge_requires_an_http_endpoint() -> None:
    """enabled 배선은 빈 endpoint나 비 HTTP 주소를 조용히 받지 않는다."""
    with pytest.raises(ValidationError):
        ModelJudgeSettings(enabled=True)
    with pytest.raises(ValidationError):
        ModelJudgeSettings(enabled=True, endpoint="judge.local")
    with pytest.raises(ValidationError):
        ModelJudgeSettings(enabled=True, endpoint="   ")


def test_enabled_model_judge_accepts_explicit_endpoint() -> None:
    """명시한 Shieldstral chat completions endpoint로만 활성화된다."""
    settings = ModelJudgeSettings(
        enabled=True,
        endpoint="http://judge.local/v1/chat/completions",
        revision="revision",
    )

    assert settings.enabled is True
    assert settings.revision == "revision"
