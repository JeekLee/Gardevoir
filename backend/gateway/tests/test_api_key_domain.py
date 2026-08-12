import ast
import dataclasses
import pathlib

import pytest

import gateway.domain
from gateway.domain.exception.api_key_error import ApiKeyError
from gateway.domain.models.api_key import (
    KEY_PREFIX,
    ApiKey,
    generate_key,
    hash_key,
    parse_bearer,
)
from shared_kernel.exception import ConflictError, ForbiddenError, UnauthorizedError


def _key(allowed=("base", "doc-agent"), default="base", **kw) -> ApiKey:
    fields: dict = {
        "id": "k1",
        "name": "app",
        "key_hash": "deadbeef",
        "upstream_base_url": "https://api.openai.com/v1",
        "upstream_api_key": "sk-upstream",
        "allowed_guardrails": allowed,
        "default_guardrail": default,
        "disabled": False,
    }
    fields.update(kw)
    return ApiKey(**fields)


def test_generate_key_has_prefix_and_entropy():
    k1, k2 = generate_key(), generate_key()
    assert k1.startswith(KEY_PREFIX)
    assert k1 != k2
    assert len(k1) > 40


def test_hash_key_is_stable_and_hides_the_key():
    raw = "gdv_live_abc"
    assert hash_key(raw) == hash_key(raw)
    assert hash_key(raw) != hash_key("gdv_live_abd")
    assert raw not in hash_key(raw)
    assert len(hash_key(raw)) == 64  # sha256 hex


def test_parse_bearer():
    assert parse_bearer("Bearer gdv_live_x") == "gdv_live_x"
    assert parse_bearer("bearer gdv_live_x") == "gdv_live_x"
    assert parse_bearer("Bearer   gdv_live_x  ") == "gdv_live_x"
    assert parse_bearer(None) is None
    assert parse_bearer("") is None
    assert parse_bearer("Basic abc") is None
    assert parse_bearer("Bearer") is None
    assert parse_bearer("Bearer ") is None


def test_resolve_guardrail_uses_default_when_absent():
    assert _key().resolve_guardrail(None) == "base"
    assert _key().resolve_guardrail("") == "base"


def test_resolve_guardrail_accepts_allowed():
    assert _key().resolve_guardrail("doc-agent") == "doc-agent"


def test_resolve_guardrail_rejects_unallowed():
    """앱이 허용 집합을 벗어날 수 없어야 한다 — 그래서 가드레일 선택이 키에 묶인다."""
    with pytest.raises(ForbiddenError) as info:
        _key().resolve_guardrail("internal-analytics")
    assert info.value.code == "APIKEY-002"
    assert info.value.details == {
        "requested": "internal-analytics",
        "allowed": ["base", "doc-agent"],
    }


def test_resolve_guardrail_falls_back_to_first_allowed_without_default():
    assert _key(default=None).resolve_guardrail(None) == "base"


def test_resolve_guardrail_fails_when_nothing_is_configured():
    with pytest.raises(ForbiddenError) as info:
        _key(allowed=(), default=None).resolve_guardrail(None)
    assert info.value.code == "APIKEY-003"


def test_api_key_is_immutable():
    """도메인 모델이 뒤에서 바뀌면 캐시된 인스턴스가 오염된다."""
    key = _key()
    with pytest.raises(dataclasses.FrozenInstanceError):
        key.name = "changed"  # type: ignore[misc]


def test_catalog_maps_each_error_to_its_category():
    assert isinstance(ApiKeyError.INVALID_KEY.exception(), UnauthorizedError)
    assert isinstance(ApiKeyError.GUARDRAIL_NOT_ALLOWED.exception(), ForbiddenError)
    assert isinstance(ApiKeyError.NO_GUARDRAIL_CONFIGURED.exception(), ForbiddenError)
    assert isinstance(ApiKeyError.DUPLICATE_NAME.exception(), ConflictError)


def test_catalog_codes_are_stable():
    """감사 로그와 클라이언트 처리에 쓰이므로 코드는 계약이다."""
    assert ApiKeyError.INVALID_KEY.code == "APIKEY-001"
    assert ApiKeyError.GUARDRAIL_NOT_ALLOWED.code == "APIKEY-002"
    assert ApiKeyError.NO_GUARDRAIL_CONFIGURED.code == "APIKEY-003"
    assert ApiKeyError.DUPLICATE_NAME.code == "APIKEY-004"


#: domain은 이들을 임포트할 수 없다. 위반은 리뷰가 아니라 테스트가 잡아야 한다.
_FORBIDDEN_TOP_LEVEL = {
    "sqlalchemy",
    "fastapi",
    "httpx",
    "clickhouse_connect",
    "starlette",
}
_FORBIDDEN_GATEWAY = {
    "gateway.application",
    "gateway.infrastructure",
    "gateway.presentation",
}


def _imports_of(path: pathlib.Path) -> set[str]:
    """Collect imported module names from a file's AST.

    독스트링·주석에 모듈 이름이 등장할 수 있으므로 텍스트가 아니라 임포트 구문을
    본다. 소스 문자열 매칭은 자기 문서에 걸려 오탐을 낸다.
    """
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_domain_imports_nothing_from_outer_layers():
    """domain은 순수해야 한다 (skills/gardevoir-be).

    임포트 부재는 실행으로 관측할 수 없으므로 AST를 본다 — 검증 대상이 코드의
    동작이 아니라 의존 방향이라는 아키텍처 계약이다.
    """
    domain_root = pathlib.Path(gateway.domain.__file__).parent
    files = sorted(domain_root.rglob("*.py"))
    assert files, "domain 패키지에서 파일을 찾지 못했다"

    violations: list[str] = []
    for path in files:
        for name in _imports_of(path):
            top = name.split(".")[0]
            if top in _FORBIDDEN_TOP_LEVEL:
                violations.append(f"{path.name} -> {name}")
            if any(name.startswith(prefix) for prefix in _FORBIDDEN_GATEWAY):
                violations.append(f"{path.name} -> {name}")
    assert violations == []


def test_the_layering_check_actually_detects_a_violation(tmp_path):
    """검사 자체가 위반을 잡을 수 있는지 확인한다.

    이 확인이 없으면 위 테스트가 항상 통과하는 빈 단정일 수 있다.
    """
    bad = tmp_path / "bad.py"
    bad.write_text("import sqlalchemy\nfrom gateway.infrastructure import x\n")
    names = _imports_of(bad)
    assert "sqlalchemy" in names
    assert "gateway.infrastructure" in names
