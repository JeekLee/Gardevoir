"""Shared helper for architecture tests.

Import direction is not observable at runtime, so we read the AST. Source-string
matching is wrong: a module's own docstring can mention the very packages it must
not import, which produces false positives.
"""

import ast
import pathlib


def imports_of(path: pathlib.Path) -> set[str]:
    """Collect imported module names from a file's AST."""
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names
