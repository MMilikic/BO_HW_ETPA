"""The Python version is written down in three places, and they must agree.

- pyproject.toml says which Python versions the project accepts.
- .python-version tells uv which Python to use outside the container.
- The Dockerfile's FROM line chooses the Python inside the container.

If they drift apart, the tests run on one Python in the container and on another
outside it. None of the three files can read another, so the version cannot be
written once; this test is what keeps them together.
"""

import re
import tomllib
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


def version_in_pyproject() -> str:
    pyproject = tomllib.loads((PROJECT / "pyproject.toml").read_text())
    version_spec = pyproject["project"]["requires-python"].replace(" ", "")
    match = re.fullmatch(r">=(\d+)\.(\d+),<(\d+)\.(\d+)", version_spec)
    assert match, (
        f"requires-python is {version_spec!r}. It should pin exactly one minor "
        f"version, written like '>=3.14,<3.15'."
    )
    major, minor, upper_major, upper_minor = (int(part) for part in match.groups())
    assert (upper_major, upper_minor) == (major, minor + 1), (
        f"requires-python is {version_spec!r}, which allows more than one minor "
        f"version. It should be '>={major}.{minor},<{major}.{minor + 1}'."
    )
    return f"{major}.{minor}"


def version_in_python_version_file() -> str:
    return (PROJECT / ".python-version").read_text().strip()


def version_in_dockerfile() -> str:
    dockerfile = (PROJECT / "Dockerfile").read_text()
    match = re.search(r"^FROM python:(\d+\.\d+)-", dockerfile, re.MULTILINE)
    assert match, "The Dockerfile should start from an image like python:3.14-slim-…"
    return match.group(1)


def test_python_version_is_the_same_in_all_three_places() -> None:
    versions_by_place = {
        "pyproject.toml (requires-python)": version_in_pyproject(),
        ".python-version": version_in_python_version_file(),
        "Dockerfile (FROM line)": version_in_dockerfile(),
    }
    listing = "\n".join(
        f"  {place}: {version}" for place, version in versions_by_place.items()
    )
    assert len(set(versions_by_place.values())) == 1, (
        "The Python version differs between the files that declare it:\n"
        f"{listing}\n"
        "Change all three together."
    )
