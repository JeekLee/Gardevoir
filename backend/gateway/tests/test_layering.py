"""의존 방향 계약.

domain 의 순수성은 test_api_key_domain / test_guardrail_domain 이 본다. 여기서는
그 바깥 두 층을 본다 — 파일이 늘어날 때 조용히 썩는 규칙이 이쪽이기 때문이다.
"""

import pathlib

import gateway.application
import gateway.composition
import gateway.presentation
from tests.layering import imports_of

_FRAMEWORKS = {"sqlalchemy", "fastapi", "clickhouse_connect", "starlette", "httpx", "psycopg"}

#: 조립 루트. 인프라 구현체와 fastapi.Depends 를 임포트해도 되는 유일한 파일들이다.
#: app.py 는 lifespan 에서 프로세스 수명 자원(엔진, ClickHouse 클라이언트, httpx
#: 클라이언트)을 만들므로 composition.py 와 같은 역할을 한다.
_WIRING_ROOTS = {"composition.py", "app.py"}


def _files(package) -> list[pathlib.Path]:
    files = sorted(pathlib.Path(package.__file__).parent.rglob("*.py"))
    assert files, f"{package.__name__} 에서 파일을 찾지 못했다"
    return files


def test_application_imports_no_framework_and_no_infrastructure():
    """application 은 포트만 안다. 어댑터는 infrastructure 가 구현한다."""
    violations = []
    for path in _files(gateway.application):
        for name in imports_of(path):
            if name.split(".")[0] in _FRAMEWORKS:
                violations.append(f"{path.name} -> {name}")
            if name.startswith(("gateway.infrastructure", "gateway.presentation")):
                violations.append(f"{path.name} -> {name}")
    assert violations == []


def test_routers_do_not_import_infrastructure():
    """라우터는 composition 에서 서비스만 가져간다."""
    violations = []
    for path in _files(gateway.presentation):
        if path.name in _WIRING_ROOTS:
            continue
        for name in imports_of(path):
            if name.startswith("gateway.infrastructure"):
                violations.append(f"{path.name} -> {name}")
    assert violations == []


def test_the_wiring_roots_still_exist():
    """면제 목록이 죽은 이름만 담고 있으면 위 테스트는 빈 단정이 된다."""
    names = {path.name for path in _files(gateway.presentation)}
    names.add(pathlib.Path(gateway.composition.__file__).name)
    assert _WIRING_ROOTS <= names


def test_infrastructure_is_reachable_only_through_composition():
    """서비스를 조립하는 곳이 하나여야 DI 를 한 곳에서 바꿀 수 있다."""
    names = imports_of(pathlib.Path(gateway.composition.__file__))
    assert any(name.startswith("gateway.infrastructure") for name in names)
    assert "fastapi" in names
