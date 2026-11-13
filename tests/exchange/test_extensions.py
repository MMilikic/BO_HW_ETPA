"""extensions.py: the extensions a student's `extensions.toml` enables."""

import re
from pathlib import Path

import pytest

from exchange.extensions import Extension, load_enabled_extensions


def test_the_extensions_named_are_enabled(tmp_path: Path) -> None:
    path = write_extensions_toml(tmp_path, 'enabled = ["fill_or_kill"]\n')

    assert load_enabled_extensions(path) == {Extension.FILL_OR_KILL}


def test_an_empty_list_enables_none(tmp_path: Path) -> None:
    path = write_extensions_toml(tmp_path, "enabled = []\n")

    assert load_enabled_extensions(path) == frozenset()


def test_a_name_that_is_not_an_extension_is_refused_naming_every_extension(
    tmp_path: Path,
) -> None:
    path = write_extensions_toml(tmp_path, 'enabled = ["fill_or_kil"]\n')
    # Not a literal: each lecture adds to the registry.
    every_name = ", ".join(extension.value for extension in Extension)

    with pytest.raises(
        ValueError,
        match=(
            "^"
            + re.escape(
                "extensions.toml: 'fill_or_kil' is not an extension; the extensions"
                f" are {every_name}"
            )
            + "$"
        ),
    ):
        load_enabled_extensions(path)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        pytest.param(
            'enabled = []\nenable = ["fill_or_kill"]\n',
            "extensions.toml: enable is not a key here; the one key is enabled",
            id="a key other than enabled",
        ),
        pytest.param(
            "",
            "extensions.toml: enabled is missing; enabled = [] enables none",
            id="no key named enabled",
        ),
        pytest.param(
            'enabled = "fill_or_kill"\n',
            "extensions.toml: enabled is a list of names in quotes, as enabled ="
            ' ["<name>", "<name>"]',
            id="a name, not a list",
        ),
        pytest.param(
            "enabled = [1]\n",
            "extensions.toml: enabled is a list of names in quotes, as enabled ="
            ' ["<name>", "<name>"]',
            id="a list of something else",
        ),
    ],
)
def test_a_file_of_the_wrong_shape_is_refused_saying_what_it_should_hold(
    tmp_path: Path, text: str, message: str
) -> None:
    path = write_extensions_toml(tmp_path, text)

    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        load_enabled_extensions(path)


def test_a_file_that_is_not_toml_is_refused_naming_the_file_and_the_place(
    tmp_path: Path,
) -> None:
    path = write_extensions_toml(tmp_path, "enabled = [fill_or_kill]\n")

    with pytest.raises(
        ValueError, match=r"^extensions\.toml: .* \(at line 1, column 12\)$"
    ):
        load_enabled_extensions(path)


def test_a_file_that_is_not_utf8_is_refused_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "extensions.toml"
    path.write_bytes(b"\xffenabled = []\n")

    with pytest.raises(
        ValueError, match=r"^extensions\.toml: 'utf-8' codec can't decode"
    ):
        load_enabled_extensions(path)


def write_extensions_toml(folder: Path, text: str) -> Path:
    path = folder / "extensions.toml"
    path.write_text(text)
    return path
