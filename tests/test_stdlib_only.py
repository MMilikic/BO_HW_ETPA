"""Code in src/ may import only the standard library, and itself.

pytest, ruff and mypy are installed for development, so an `import pytest` in src/
would work without complaint. This test is what catches it.

The rule is not austerity. Later in the course the exchange is profiled to find out
what makes it slow; a library written in C on the hot path would do the work invisibly,
and the honest answer to "why is this slow?" would become "it isn't, the library is".
"""

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


def top_level_imports(path: Path) -> set[str]:
    """Top-level names imported: `import a.b` and `from a.b import c` both give a."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def our_own_packages() -> set[str]:
    """Everything directly inside src/ is ours."""
    return {
        path.stem for path in SRC.iterdir() if path.is_dir() or path.suffix == ".py"
    }


def test_src_imports_only_the_standard_library() -> None:
    source_files = sorted(SRC.rglob("*.py")) if SRC.is_dir() else []
    if not source_files:
        pytest.skip("src/ has no Python files yet, so there is nothing to check")

    allowed_module_names = set(sys.stdlib_module_names) | our_own_packages()
    offenders = [
        f"  {path.relative_to(SRC.parent)} imports {name}"
        for path in source_files
        for name in sorted(top_level_imports(path))
        if name not in allowed_module_names
    ]
    assert not offenders, (
        "Code in src/ may import only the standard library and our own packages:\n"
        + "\n".join(offenders)
    )
