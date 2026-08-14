"""의존 방향 계약.

domain 의 순수성은 test_api_key_domain / test_guardrail_domain 이 본다. 여기서는
그 바깥 두 층을 본다 — 파일이 늘어날 때 조용히 썩는 규칙이 이쪽이기 때문이다.

**층을 이름으로 찾는다.** 바운디드 컨텍스트마다 자기 ``application``/``presentation``
을 갖기 때문이다. 패키지를 하나씩 적어두면 컨텍스트를 옮길 때마다 규칙이 조용히
줄어든다 — audit 을 옮겼을 때 실제로 그럴 뻔했다.
"""

import pathlib

import gateway
import gateway.composition
from tests.layering import imports_of

_FRAMEWORKS = {"sqlalchemy", "fastapi", "clickhouse_connect", "starlette", "httpx", "psycopg"}

#: 조립 루트. 인프라 구현체와 fastapi.Depends 를 임포트해도 되는 유일한 파일들이다.
#: app.py 는 lifespan 에서 프로세스 수명 자원(엔진, ClickHouse 클라이언트, httpx
#: 클라이언트)을 만들므로 composition.py 와 같은 역할을 한다.
_WIRING_ROOTS = {"composition.py", "app.py"}

#: 층 이름. 루트 직속으로 남아 있는 동안은 컨텍스트가 아니라 층으로 센다.
_LAYERS = {"domain", "application", "infrastructure", "presentation"}

_ROOT = pathlib.Path(gateway.__file__).parent


def _layer_files(layer: str) -> list[pathlib.Path]:
    """모든 컨텍스트에서 ``layer`` 라는 이름의 패키지 아래 파일을 모은다."""
    return sorted(
        path
        for path in _ROOT.rglob("*.py")
        if layer in path.relative_to(_ROOT).parts and "__pycache__" not in path.parts
    )


def _contexts_with(layer: str) -> set[str]:
    """그 층을 가진 컨텍스트 이름. 루트 직속이면 ``"(root)"``."""
    names = set()
    for path in _layer_files(layer):
        parts = path.relative_to(_ROOT).parts
        names.add("(root)" if parts[0] == layer else parts[0])
    return names


def test_application_imports_no_framework_and_no_infrastructure():
    """application 은 포트만 안다. 어댑터는 infrastructure 가 구현한다."""
    violations = []
    for path in _layer_files("application"):
        for name in imports_of(path):
            if name.split(".")[0] in _FRAMEWORKS:
                violations.append(f"{path.relative_to(_ROOT)} -> {name}")
            if ".infrastructure" in name or ".presentation" in name:
                violations.append(f"{path.relative_to(_ROOT)} -> {name}")
    assert violations == []


def test_routers_do_not_import_infrastructure():
    """라우터는 composition 에서 서비스만 가져간다."""
    violations = []
    for path in _layer_files("presentation"):
        if path.name in _WIRING_ROOTS:
            continue
        for name in imports_of(path):
            if ".infrastructure" in name:
                violations.append(f"{path.relative_to(_ROOT)} -> {name}")
    assert violations == []


def test_every_context_is_actually_scanned():
    """이름으로 찾는 규칙은 조용히 0개를 걷을 수 있다.

    컨텍스트를 옮기다 층 이름을 바꾸면 위 두 테스트가 빈 단정이 된다. 지금 있는
    컨텍스트가 실제로 스캔 대상에 들어왔는지 확인한다. 이동이 끝날 때까지는 층이
    루트 직속으로도 남아 있으므로 그쪽은 ``(root)`` 로 센다.
    """
    contexts = {
        path.name
        for path in _ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").exists() and path.name not in _LAYERS
    }
    scanned = _contexts_with("application") | _contexts_with("presentation")
    assert contexts <= scanned, (
        f"이 컨텍스트에 application/presentation 이 안 잡혔다: {contexts - scanned}"
    )
    assert len(_layer_files("application")) > 10, "application 층을 못 찾고 있다"


def test_the_wiring_roots_still_exist():
    """면제 목록이 죽은 이름만 담고 있으면 위 테스트는 빈 단정이 된다."""
    names = {path.name for path in _layer_files("presentation")}
    names.add(pathlib.Path(gateway.composition.__file__).name)
    assert _WIRING_ROOTS <= names


def test_infrastructure_is_reachable_only_through_composition():
    """서비스를 조립하는 곳이 하나여야 DI 를 한 곳에서 바꿀 수 있다."""
    names = imports_of(pathlib.Path(gateway.composition.__file__))
    assert any(".infrastructure" in name for name in names)
    assert "fastapi" in names
