"""Assertions whose failure shows what differs, for a ladder and a list of events."""

from collections.abc import Sequence
from dataclasses import fields, is_dataclass
from difflib import ndiff
from enum import Enum

from protocol.types import NO_CLIENT_ORDER_ID, NO_REQUEST_ID


def assert_ladder(actual: str, expected: str) -> None:
    """Fail unless `actual`, from any `render_state()`, is exactly the ladder
    `expected`. A failure shows the whole ladder with the differing lines marked.
    """
    # Tells pytest to leave this frame out of a failure, so a student sees the
    # test's line and our message, not our code.
    __tracebackhide__ = True
    if actual == expected:
        return
    if actual.splitlines() == expected.splitlines():
        raise AssertionError(
            "the ladders differ only in their final newline; every rendered state ends "
            "with one"
        )
    differences = [
        line
        for line in ndiff(expected.splitlines(), actual.splitlines())
        if not line.startswith("? ")
    ]
    raise AssertionError(
        "the rendered state is not the expected ladder (- expected, + actual):\n"
        + "\n".join(differences)
    )


def assert_events(actual: Sequence[object], expected: Sequence[object]) -> None:
    """Fail unless the two lists are equal, item for item, in order: events,
    commands or wire messages. A failure shows both, the first difference marked
    and its differing fields named.
    """
    __tracebackhide__ = True
    if list(actual) == list(expected):
        return
    first_differing_index = _first_differing_index(actual, expected)
    raise AssertionError(
        f"the lists first differ at item {first_differing_index} (marked >):\n"
        f"expected:\n{_numbered_lines(expected, first_differing_index)}\n"
        f"actual:\n{_numbered_lines(actual, first_differing_index)}"
        + _field_differences(actual, expected, first_differing_index)
    )


def _first_differing_index(actual: Sequence[object], expected: Sequence[object]) -> int:
    for index, (actual_item, expected_item) in enumerate(
        zip(actual, expected, strict=False)
    ):
        if actual_item != expected_item:
            return index
    return min(len(actual), len(expected))


def _field_differences(
    actual: Sequence[object], expected: Sequence[object], index: int
) -> str:
    """For two items of one type at `index`, a line per field that differs."""
    if index >= len(actual) or index >= len(expected):
        return ""
    actual_item = actual[index]
    expected_item = expected[index]
    if type(actual_item) is not type(expected_item) or not is_dataclass(actual_item):
        return ""
    lines = []
    for field in fields(actual_item):
        actual_value = getattr(actual_item, field.name)
        expected_value = getattr(expected_item, field.name)
        if actual_value != expected_value:
            expected_text = _format_field(field.name, expected_value)
            actual_text = _format_field(field.name, actual_value)
            lines.append(
                f"  {field.name}: expected {expected_text}, actual {actual_text}"
            )
    return "\ndiffering fields:\n" + "\n".join(lines)


def _numbered_lines(items: Sequence[object], marked_index: int) -> str:
    if not items:
        return "    (nothing)"
    lines = []
    for index, item in enumerate(items):
        marker = ">" if index == marked_index else " "
        lines.append(f"  {marker} {index}  {_format_item(item)}")
    return "\n".join(lines)


def _format_item(item: object) -> str:
    """One line for a command, event or message: its class and every field by name."""
    if not is_dataclass(item) or isinstance(item, type):
        return repr(item)
    parts = []
    for field in fields(item):
        value = getattr(item, field.name)
        parts.append(f"{field.name}={_format_field(field.name, value)}")
    return f"{type(item).__name__}({', '.join(parts)})"


def _format_field(field_name: str, value: object) -> str:
    """A client order id as its text, a sentinel id by the name of what it means, and
    an enum by name."""
    if field_name == "request_id" and value == NO_REQUEST_ID:
        return "NO_REQUEST_ID"
    if isinstance(value, bytes):
        if value == NO_CLIENT_ORDER_ID:
            return "NO_CLIENT_ORDER_ID"
        return repr(value.decode("ascii", errors="backslashreplace"))
    if isinstance(value, Enum):
        return value.name
    if is_dataclass(value) and not isinstance(value, type):
        return _format_item(value)
    return repr(value)
