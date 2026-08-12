import logging

import pytest

from shared_kernel.exception import (
    AppError,
    ConflictError,
    ErrorCatalog,
    ErrorCode,
    ErrorResponse,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)


class ApiKeyError(ErrorCatalog):
    """A BC's catalog: one line per error, no class per error."""

    INVALID_KEY = ("APIKEY-001", "the provided API key is not valid", UnauthorizedError)
    GUARDRAIL_NOT_ALLOWED = ("APIKEY-002", "guardrail not allowed for this key", ForbiddenError)
    DUPLICATE_NAME = ("APIKEY-003", "an API key with this name already exists", ConflictError)


def test_category_defaults():
    assert ValidationError().http_status == 422
    assert NotFoundError().http_status == 404
    assert UnauthorizedError().http_status == 401
    assert ForbiddenError().http_status == 403
    assert ConflictError().http_status == 409
    assert AppError().http_status == 500
    assert AppError().code is ErrorCode.INTERNAL


def test_client_errors_log_at_warning_not_error():
    """4xx는 우리 잘못이 아니다. ERROR로 남기면 알람이 무의미해진다."""
    assert ValidationError().log_level == logging.WARNING
    assert NotFoundError().log_level == logging.WARNING
    assert UnauthorizedError().log_level == logging.WARNING
    assert ForbiddenError().log_level == logging.WARNING
    assert ConflictError().log_level == logging.WARNING
    assert AppError().log_level == logging.ERROR


def test_catalog_member_builds_its_error():
    exc = ApiKeyError.INVALID_KEY.exception()
    assert isinstance(exc, UnauthorizedError)
    assert exc.code == "APIKEY-001"
    assert exc.message == "the provided API key is not valid"
    assert exc.http_status == 401
    assert exc.details is None


def test_catalog_member_accepts_override_and_details():
    exc = ApiKeyError.GUARDRAIL_NOT_ALLOWED.exception(
        "guardrail 'x' is not allowed", details={"requested": "x", "allowed": ["base"]}
    )
    assert isinstance(exc, ForbiddenError)
    assert exc.message == "guardrail 'x' is not allowed"
    assert exc.details == {"requested": "x", "allowed": ["base"]}


def test_catalog_raise_helper():
    with pytest.raises(ConflictError) as info:
        ApiKeyError.DUPLICATE_NAME.raise_()
    assert info.value.code == "APIKEY-003"


def test_catalog_exposes_code_and_category():
    assert ApiKeyError.INVALID_KEY.code == "APIKEY-001"
    assert ApiKeyError.INVALID_KEY.category is UnauthorizedError
    assert ApiKeyError.INVALID_KEY.default_message


def test_catalog_code_does_not_leak_between_members():
    """인스턴스 오버라이드가 클래스 속성을 오염시키면 안 된다."""
    ApiKeyError.INVALID_KEY.exception()
    assert UnauthorizedError().code is ErrorCode.UNAUTHORIZED
    assert UnauthorizedError.code is ErrorCode.UNAUTHORIZED


def test_error_response_serialises_camel_case():
    body = ErrorResponse(
        code="APIKEY-001", message="nope", details={"a": 1}, request_id="req_1"
    ).model_dump(by_alias=True)
    assert body == {
        "code": "APIKEY-001",
        "message": "nope",
        "details": {"a": 1},
        "requestId": "req_1",
    }


def test_error_response_omits_absent_optional_fields():
    body = ErrorResponse(code="X", message="m").model_dump(by_alias=True, exclude_none=True)
    assert body == {"code": "X", "message": "m"}
