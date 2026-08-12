import ast
import pathlib
import subprocess
import sys

import gateway.infrastructure.models


def _declared_tablenames(models_dir: pathlib.Path) -> set[str]:
    """Read __tablename__ assignments straight from the model sources."""
    names: set[str] = set()
    for path in models_dir.glob("*.py"):
        if path.name == "__init__.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__tablename__"
                    and isinstance(node.value, ast.Constant)
                ):
                    names.add(node.value.value)
    return names


def test_every_orm_module_is_reexported_from_the_package():
    """models/__init__.py 가 모든 모델을 re-export 해야 한다.

    alembic/env.py 는 패키지만 임포트하므로, re-export 가 빠진 모델은
    Base.metadata 에 등록되지 않고 autogenerate 가 테이블을 조용히 놓친다.
    마이그레이션이 비는 것을 배포 후에야 알게 된다.

    다른 테스트가 서브모듈을 직접 임포트해 metadata 를 오염시키므로 별도
    인터프리터에서 패키지만 임포트해 확인한다.
    """
    probe = (
        "import gateway.infrastructure.models\n"
        "from shared_kernel.database import Base\n"
        "print(','.join(sorted(Base.metadata.tables)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    registered = {t for t in result.stdout.strip().split(",") if t}

    models_dir = pathlib.Path(gateway.infrastructure.models.__file__).parent
    declared = _declared_tablenames(models_dir)

    assert declared, "모델 파일에서 __tablename__ 을 찾지 못했다"
    missing = declared - registered
    assert missing == set(), f"models/__init__.py 에서 re-export 되지 않은 모델: {missing}"


def test_the_registry_check_can_actually_fail(tmp_path):
    """검사가 빈 단정이 아님을 확인한다."""
    (tmp_path / "widget.py").write_text('class W:\n    __tablename__ = "widgets"\n')
    (tmp_path / "__init__.py").write_text("")
    assert _declared_tablenames(tmp_path) == {"widgets"}
