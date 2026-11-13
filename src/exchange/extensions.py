"""The homework's extensions, and the file a student enables them in.

An extension is an optional part of a lecture's homework. The student enables it by
adding its name to `enabled` in `extensions.toml`, at the top of the package. That one
switch decides whether its tests run and whether the venue offers it. Where its lecture
has added the extension to the venue and the extension is not enabled, the venue either
refuses the requests that use it, or runs without it and says so at startup. Each
lecture adds its own extensions here.
"""

import tomllib
from enum import StrEnum
from pathlib import Path

# Found from this file rather than the working directory: pytest and the venue may each
# start in another folder.
_CODEBASE = Path(__file__).resolve().parents[2]
EXTENSIONS_PATH = _CODEBASE / "extensions.toml"

_ENABLED_KEY = "enabled"


class Extension(StrEnum):
    """An extension. Each member's value is its name in `extensions.toml`."""

    # An order that trades all of its quantity at once, or none of it.
    FILL_OR_KILL = "fill_or_kill"


def load_enabled_extensions(path: Path) -> frozenset[Extension]:
    """The extensions the file at `path` enables. Raises OSError if it cannot be read.
    Raises ValueError, naming the file, if it is not TOML, or does not hold exactly one
    key, `enabled`, whose value is a list of extensions' names. For an unknown name,
    the message lists every extension's name."""
    with path.open("rb") as file:
        try:
            document = tomllib.load(file)
        # UnicodeDecodeError: tomllib reads only UTF-8, and decodes before it parses.
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as error:
            raise ValueError(f"{path.name}: {error}") from error
    other_keys = sorted(document.keys() - {_ENABLED_KEY})
    if other_keys:
        raise ValueError(
            f"{path.name}: {other_keys[0]} is not a key here; the one key is"
            f" {_ENABLED_KEY}"
        )
    if _ENABLED_KEY not in document:
        raise ValueError(
            f"{path.name}: {_ENABLED_KEY} is missing; {_ENABLED_KEY} = [] enables none"
        )
    names = document[_ENABLED_KEY]
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError(
            f"{path.name}: {_ENABLED_KEY} is a list of names in quotes, as"
            f' {_ENABLED_KEY} = ["<name>", "<name>"]'
        )
    known_names = [extension.value for extension in Extension]
    for name in names:
        if name not in known_names:
            raise ValueError(
                f"{path.name}: {name!r} is not an extension; the extensions are"
                f" {', '.join(known_names)}"
            )
    return frozenset(Extension(name) for name in names)
