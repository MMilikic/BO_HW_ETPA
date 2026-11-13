"""What a plain `pytest` runs, and how it counts what ran.

- **An extension's tests run when it is enabled.** A test in an `extensions/` folder
  is marked `extension`. Its file names the extension,
  `EXTENSION = Extension.FILL_OR_KILL`, and any earlier one it builds on,
  `BUILDS_ON = (...)`; it runs only when `extensions.toml` enables them all. Naming the
  file or folder on the command line runs it either way.
- **Each test is marked with its lecture**, `l1` to `l8`, from `tests/lectures.json`,
  so `pytest -m l3` runs one lecture's tests.
- **Earlier lectures' tests run first**, and each lecture's core before its
  extensions; otherwise in pytest's order, so a file's classes run as they are
  written. A lecture builds only on earlier ones, and an extension on the core, so the
  first failure is usually in what the others rely on.
- **The summary at the end counts each lecture apart**, its core and each extension
  separately, and counts any of its test files that could not be collected; a last
  line names the extensions not enabled whose tests were left out.
- **The code to add comes first.** Before anything is collected, the tests in
  `tests/code_to_add/` run on their own, and if one fails pytest stops there. Until the
  code to add is in place, the other tests cannot pass, and those that import a name it
  adds cannot even be collected; their errors would bury the one message that says what
  to add.
- **A test "waiting for your code" is one line.** A test that fails on the error raised
  by a function not yet written is listed under "waiting for your code", with the test
  and the function, and counted apart; every other failure shows as pytest shows it.
  When pytest is asked for a traceback, with a style (`pytest --tb=short`) or
  `--full-trace`, these tests show as pytest shows them too.

pytest finds this file by its name, which is why its hooks are here. Everything else
in the tests is plain functions, and the classes that group them.
"""

import ast
import json
import os
import re
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

from exchange.extensions import EXTENSIONS_PATH, Extension, load_enabled_extensions

CODEBASE = Path(__file__).resolve().parent
LECTURE_TABLE = CODEBASE / "tests" / "lectures.json"
LECTURE_PATTERN = re.compile(r"L(?P<number>[1-8])")
LECTURE_MARKS = [f"l{lecture_number}" for lecture_number in range(1, 9)]
EXTENSIONS_FOLDER = "extensions"
EXTENSION_CONSTANT = "EXTENSION"
BUILDS_ON_CONSTANT = "BUILDS_ON"
CORE_PART = "core"
UNNAMED_EXTENSION_PART = "extensions"
CODE_TO_ADD_TESTS_FOLDER = CODEBASE / "tests" / "code_to_add"
# Set for the pytest run that the check starts on tests/code_to_add/, so that this run
# does not start the check again.
CODE_TO_ADD_CHECK_OFF_ENVIRONMENT_VARIABLE = "HOMEWORK_CODE_TO_ADD_CHECK_OFF"

# The error that a function not yet written raises, in its exact words, so that no
# other NotImplementedError is taken for it.
STUB_MESSAGE_PATTERN = re.compile(
    r"L[1-8]: (?P<qualified_name>[A-Za-z_][A-Za-z0-9_.]*) is yours to write"
)
# The label a test gets when it fails on that error, in pytest's last line and in the
# summary. It is also the title of the section that lists those tests.
WAITING_FOR_YOUR_CODE = "waiting for your code"
# pytest's own traceback style, the one it uses when none is given.
DEFAULT_TRACEBACK_STYLE = "auto"
HOMEWORK_RUN_PLUGIN_NAME = "homework_run"

OUTCOMES_IN_SUMMARY_ORDER = [
    "passed",
    "failed",
    WAITING_FOR_YOUR_CODE,
    "error",
    "skipped",
]


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "extension: a test of an optional part of a lecture's homework"
    )
    for lecture_mark in LECTURE_MARKS:
        config.addinivalue_line(
            "markers", f"{lecture_mark}: a test of {lecture_mark.upper()}'s homework"
        )
    try:
        enabled_extensions = load_enabled_extensions(EXTENSIONS_PATH)
    except (OSError, ValueError) as error:
        raise pytest.UsageError(str(error)) from error
    is_traceback_style_given = config.getoption("tbstyle") != DEFAULT_TRACEBACK_STYLE
    is_full_trace_asked_for: bool = config.getoption("fulltrace")
    is_traceback_asked_for = is_traceback_style_given or is_full_trace_asked_for
    config.pluginmanager.register(
        HomeworkRun(
            enabled_extensions=enabled_extensions,
            rootpath=config.rootpath,
            is_traceback_asked_for=is_traceback_asked_for,
        ),
        name=HOMEWORK_RUN_PLUGIN_NAME,
    )


# A wrapper, so that it sorts before anything chooses from the tests: what `--sw`
# leaves out is then what ran before its last failure. pytest's `--lf` and `--ff` wrap
# it in turn, and still put the failures first.
@pytest.hookimpl(wrapper=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> Generator[None]:
    homework_run = config.pluginmanager.get_plugin(HOMEWORK_RUN_PLUGIN_NAME)
    assert isinstance(homework_run, HomeworkRun)
    homework_run.sort_into_run_order(items)
    return (yield)


def pytest_sessionstart(session: pytest.Session) -> None:
    is_check_off = (
        os.environ.get(CODE_TO_ADD_CHECK_OFF_ENVIRONMENT_VARIABLE) is not None
    )
    has_code_to_add_tests = any(CODE_TO_ADD_TESTS_FOLDER.glob("test_*.py"))
    if is_check_off or not has_code_to_add_tests:
        return
    # Short tracebacks: the full one shows each test's call, the code to add in it,
    # above the message that already gives that code.
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "--tb=short",
            str(CODE_TO_ADD_TESTS_FOLDER),
        ],
        cwd=CODEBASE,
        env=os.environ | {CODE_TO_ADD_CHECK_OFF_ENVIRONMENT_VARIABLE: "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    # No tests collected passes too: when a later lecture asks for an earlier lecture's
    # code again, the earlier lecture's file in tests/code_to_add/ stays, with no tests
    # in it.
    has_passed = completed.returncode in (
        pytest.ExitCode.OK,
        pytest.ExitCode.NO_TESTS_COLLECTED,
    )
    if has_passed:
        return
    output = completed.stdout + completed.stderr
    terminal_reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if terminal_reporter is not None:
        terminal_reporter.write(output)
    else:
        sys.stdout.write(output)
    if completed.returncode == pytest.ExitCode.TESTS_FAILED:
        reason = (
            "stopped before the other tests: add the code the tests above ask for"
            " first. The week's description in doc/homework/ shows it, under"
            ' "Code to add to your own files".'
        )
    else:
        reason = (
            "stopped before the other tests: the tests in tests/code_to_add/ could"
            " not run, for the reason above."
        )
    pytest.exit(reason, returncode=pytest.ExitCode.TESTS_FAILED)


class HomeworkRun:
    """One run of the tests as the homework sees it: which lecture each test belongs
    to, which tests it leaves out, which are "waiting for your code", and how each
    lecture's tests did. pytest calls its methods by their names, as it calls the
    functions above."""

    def __init__(
        self,
        *,
        enabled_extensions: frozenset[Extension],
        rootpath: Path,
        is_traceback_asked_for: bool,
    ) -> None:
        self._enabled_extensions = enabled_extensions
        self._rootpath = rootpath
        self._is_traceback_asked_for = is_traceback_asked_for
        self._stub_message_by_test_id: dict[str, str] = {}
        self._extensions_needed_by_file_path: dict[str, tuple[Extension, ...]] = {}
        self._lecture_by_test_id = _lecture_table()
        self._lecture_part_by_test_id: dict[str, tuple[str, str]] = {}
        self._reports_by_test_id: dict[str, list[pytest.TestReport]] = {}
        self._uncollected_file_count_by_lecture_part: dict[tuple[str, str], int] = {}
        self._left_out_test_count_by_extension: dict[Extension, int] = {}

    def pytest_itemcollected(self, item: pytest.Item) -> None:
        # Marked as each test is collected, so `-m` can select by these marks.
        if _is_extension(item):
            item.add_marker("extension")
        lecture = _lecture_of(item.nodeid, self._lecture_by_test_id)
        if lecture is not None:
            item.add_marker(lecture.lower())

    def sort_into_run_order(self, items: list[pytest.Item]) -> None:
        """Put `items` in the order they run. The sort is stable: tests that share a
        place in the run keep pytest's own order."""
        items.sort(key=self._place_in_the_run)

    # Last, so that `-m` and `-k` have chosen first, and only extensions they chose
    # are counted as left out.
    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(
        self, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        named_extension_paths = _extension_paths_on_command_line(config)
        selected = []
        left_out = []
        for item in items:
            file_path = item.nodeid.split("::")[0]
            extensions_needed = self._extensions_needed(file_path)
            extensions_not_enabled = [
                extension
                for extension in extensions_needed
                if extension not in self._enabled_extensions
            ]
            is_named = any(
                item.path.resolve().is_relative_to(path)
                for path in named_extension_paths
            )
            if extensions_not_enabled and not is_named:
                left_out.append(item)
                extension_to_enable_first = extensions_not_enabled[0]
                left_out_count = self._left_out_test_count_by_extension.get(
                    extension_to_enable_first, 0
                )
                self._left_out_test_count_by_extension[extension_to_enable_first] = (
                    left_out_count + 1
                )
                continue
            selected.append(item)
            lecture = _lecture_of(item.nodeid, self._lecture_by_test_id)
            if lecture is not None:
                part = _part(file_path, extensions_needed)
                self._lecture_part_by_test_id[item.nodeid] = (lecture, part)
        if left_out:
            config.hook.pytest_deselected(items=left_out)
            # pytest runs the list it passed in, so it is changed in place.
            items[:] = selected

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        # A file that cannot be collected has no tests to report, so it is counted
        # itself: otherwise its lecture would read as if every test in it passed.
        if not report.failed:
            return
        file_path = report.nodeid.split("::")[0]
        lecture = _lecture_of(file_path, self._lecture_by_test_id)
        if lecture is None:
            return
        part = _part(file_path, self._extensions_needed(file_path))
        uncollected_file_count = self._uncollected_file_count_by_lecture_part.get(
            (lecture, part), 0
        )
        self._uncollected_file_count_by_lecture_part[(lecture, part)] = (
            uncollected_file_count + 1
        )

    # First, because the first implementation to return a report ends the hook. This
    # one returns nothing, so pytest still makes the report.
    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo[None]
    ) -> None:
        if self._is_traceback_asked_for or call.when != "call":
            return
        # A test's call can be reported more than once, a subtest's apart from the
        # test's own: each report says only what its own call failed on.
        self._stub_message_by_test_id.pop(item.nodeid, None)
        if call.excinfo is None or type(call.excinfo.value) is not NotImplementedError:
            return
        message = str(call.excinfo.value)
        if STUB_MESSAGE_PATTERN.fullmatch(message) is not None:
            self._stub_message_by_test_id[item.nodeid] = message

    def pytest_report_teststatus(
        self, report: pytest.TestReport | pytest.CollectReport
    ) -> tuple[str, str, str] | None:
        # Its own category takes the test out of pytest's failures and its short
        # summary; the test still fails, with the same letter and word.
        if self._is_waiting_for_code(report):
            return WAITING_FOR_YOUR_CODE, "F", "FAILED"
        return None

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.nodeid not in self._reports_by_test_id:
            self._reports_by_test_id[report.nodeid] = []
        self._reports_by_test_id[report.nodeid].append(report)

    def pytest_terminal_summary(
        self, terminalreporter: pytest.TerminalReporter
    ) -> None:
        self._write_tests_waiting_for_code(terminalreporter)
        counts_by_lecture_part_and_outcome: dict[tuple[str, str], dict[str, int]] = {}
        for test_id, reports in self._reports_by_test_id.items():
            if test_id not in self._lecture_part_by_test_id:
                continue
            lecture_part = self._lecture_part_by_test_id[test_id]
            if lecture_part not in counts_by_lecture_part_and_outcome:
                counts_by_lecture_part_and_outcome[lecture_part] = {
                    outcome: 0 for outcome in OUTCOMES_IN_SUMMARY_ORDER
                }
            outcome = (
                WAITING_FOR_YOUR_CODE
                if any(self._is_waiting_for_code(report) for report in reports)
                else _outcome(reports)
            )
            counts_by_lecture_part_and_outcome[lecture_part][outcome] += 1
        for lecture_part in self._uncollected_file_count_by_lecture_part:
            if lecture_part not in counts_by_lecture_part_and_outcome:
                counts_by_lecture_part_and_outcome[lecture_part] = {
                    outcome: 0 for outcome in OUTCOMES_IN_SUMMARY_ORDER
                }
        if counts_by_lecture_part_and_outcome:
            # write_sep, not section: it ends the line of test results first, which
            # section leaves to the next line written, as a blank line under the title.
            terminalreporter.write_sep("=", "lectures")
            lectures = sorted(
                {lecture for lecture, _ in counts_by_lecture_part_and_outcome}
            )
            for lecture in lectures:
                parts = sorted(
                    {
                        part
                        for part_lecture, part in counts_by_lecture_part_and_outcome
                        if part_lecture == lecture
                    },
                    key=lambda part: (part != CORE_PART, part),
                )
                descriptions = [
                    f"{part} "
                    + _counts_in_words(
                        counts_by_lecture_part_and_outcome[(lecture, part)],
                        uncollected_file_count=self._uncollected_file_count_by_lecture_part.get(
                            (lecture, part), 0
                        ),
                    )
                    for part in parts
                ]
                terminalreporter.write_line(f"{lecture}: {'; '.join(descriptions)}")
        if self._left_out_test_count_by_extension:
            descriptions = [
                f"{extension} ({_tests_in_words(count)})"
                for extension, count in sorted(
                    self._left_out_test_count_by_extension.items()
                )
            ]
            terminalreporter.write_line(
                f"Not enabled, so not run: {', '.join(descriptions)}. Enable one by"
                f" adding its name to enabled in {EXTENSIONS_PATH.name}."
            )

    def _write_tests_waiting_for_code(
        self, terminalreporter: pytest.TerminalReporter
    ) -> None:
        """Write a section listing each test "waiting for your code", in the order
        they ran, with its id and the error it failed on. Then write how many tests wait
        for each function, most first."""
        lines = []
        test_count_by_qualified_name: dict[str, int] = {}
        for test_id, reports in self._reports_by_test_id.items():
            if not any(self._is_waiting_for_code(report) for report in reports):
                continue
            stub_message = self._stub_message_by_test_id[test_id]
            lines.append(f"{test_id} - {stub_message}")
            qualified_name = _qualified_name_in(stub_message)
            test_count = test_count_by_qualified_name.get(qualified_name, 0)
            test_count_by_qualified_name[qualified_name] = test_count + 1
        if not lines:
            return
        terminalreporter.write_sep("=", WAITING_FOR_YOUR_CODE)
        for line in lines:
            terminalreporter.write_line(line)
        # Most first: writing the function more tests wait for lets more of them run.
        most_first = sorted(
            test_count_by_qualified_name.items(),
            key=lambda name_and_count: (-name_and_count[1], name_and_count[0]),
        )
        descriptions = [
            f"{qualified_name} ({_tests_in_words(test_count)})"
            for qualified_name, test_count in most_first
        ]
        terminalreporter.write_line(
            f"Waiting for your code in: {', '.join(descriptions)}"
        )

    def _is_waiting_for_code(
        self, report: pytest.TestReport | pytest.CollectReport
    ) -> bool:
        """Whether the report is of a test that failed on the NotImplementedError that a
        function not yet written raises. A test marked to fail, `xfail`, that reaches
        the error is not: it did not fail."""
        return (
            report.when == "call"
            and report.failed
            and report.nodeid in self._stub_message_by_test_id
        )

    def _extensions_needed(self, file_path: str) -> tuple[Extension, ...]:
        """`_extensions_named_in` for `file_path`, read once."""
        if file_path not in self._extensions_needed_by_file_path:
            self._extensions_needed_by_file_path[file_path] = _extensions_named_in(
                self._rootpath / file_path, file_path=file_path
            )
        return self._extensions_needed_by_file_path[file_path]

    def _place_in_the_run(self, item: pytest.Item) -> tuple[int, bool]:
        """Where `item` runs: by its lecture's number, 0 without one, then the core
        before the extensions."""
        lecture = _lecture_of(item.nodeid, self._lecture_by_test_id)
        lecture_number = 0 if lecture is None else int(lecture.removeprefix("L"))
        return (lecture_number, _is_extension(item))


def _lecture_table() -> dict[str, str]:
    """The lecture of each test, keyed by its id or its file's path, as in
    `{"tests/exchange/engine/test_book.py": "L1"}`. Empty where there is no table, as
    in the course's own repository."""
    if not LECTURE_TABLE.exists():
        return {}
    try:
        lecture_by_test_id: dict[str, str] = json.loads(LECTURE_TABLE.read_text())
    except json.JSONDecodeError as error:
        raise pytest.UsageError(f"{LECTURE_TABLE} is not JSON: {error}") from error
    for test_id, lecture in lecture_by_test_id.items():
        if LECTURE_PATTERN.fullmatch(lecture) is None:
            raise pytest.UsageError(
                f"{LECTURE_TABLE} gives {test_id} the lecture {lecture!r}, which is"
                " not one of L1 to L8"
            )
    return lecture_by_test_id


def _is_extension(item: pytest.Item) -> bool:
    return _is_in_an_extensions_folder(item.nodeid.split("::")[0])


def _is_in_an_extensions_folder(file_path: str) -> bool:
    return EXTENSIONS_FOLDER in Path(file_path).parts


def _extensions_named_in(path: Path, *, file_path: str) -> tuple[Extension, ...]:
    """The extensions the test file at `path` needs enabled: its `EXTENSION`, then each
    of its `BUILDS_ON`. Empty if the file names none, does not parse, or names an
    extension that does not exist (its collection reports that). `file_path` is how an
    error names the file. Raises pytest.UsageError for `BUILDS_ON` without
    `EXTENSION`, for `EXTENSION` outside an extensions folder, and for a value not
    written `Extension.<NAME>`."""
    try:
        module = ast.parse(path.read_text(encoding="utf-8"))
    except OSError, SyntaxError, UnicodeDecodeError:
        return ()
    values_by_name = {}
    for statement in module.body:
        # `EXTENSION = ...`, or `EXTENSION: Extension = ...` with its type.
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id in (
            EXTENSION_CONSTANT,
            BUILDS_ON_CONSTANT,
        ):
            values_by_name[target.id] = value
    if EXTENSION_CONSTANT not in values_by_name:
        if BUILDS_ON_CONSTANT in values_by_name:
            raise pytest.UsageError(
                f"{file_path} says what it builds on, {BUILDS_ON_CONSTANT}, but not"
                f" whose test it is: {EXTENSION_CONSTANT} = Extension.<NAME>"
            )
        return ()
    if not _is_in_an_extensions_folder(file_path):
        raise pytest.UsageError(
            f"{file_path} names an extension, but is not in an {EXTENSIONS_FOLDER}/"
            " folder: an extension's tests never share a file with the core's"
        )
    builds_on = values_by_name.get(BUILDS_ON_CONSTANT, ast.Tuple(elts=[]))
    if not isinstance(builds_on, ast.Tuple):
        raise pytest.UsageError(
            f"{file_path}: {BUILDS_ON_CONSTANT} is a tuple, as"
            f" {BUILDS_ON_CONSTANT} = (Extension.<NAME>,)"
        )
    names = [
        _extension_name_written(value, file_path=file_path)
        for value in [values_by_name[EXTENSION_CONSTANT], *builds_on.elts]
    ]
    if any(name not in Extension.__members__ for name in names):
        return ()
    return tuple(Extension[name] for name in names)


def _extension_name_written(value: ast.expr, *, file_path: str) -> str:
    """The name `Extension.X` gives, `X`. Raises pytest.UsageError for anything
    else."""
    if not (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == Extension.__name__
    ):
        raise pytest.UsageError(
            f"{file_path}: an extension is written Extension.<NAME>, as"
            f" {EXTENSION_CONSTANT} = Extension.<NAME>"
        )
    return value.attr


def _part(file_path: str, extensions_needed: tuple[Extension, ...]) -> str:
    """The part of its lecture a test file counts under: the core, its extension, or,
    for an extension's file that names none yet, the extensions."""
    if extensions_needed:
        return extensions_needed[0].value
    if _is_in_an_extensions_folder(file_path):
        return UNNAMED_EXTENSION_PART
    return CORE_PART


def _lecture_of(test_id: str, lecture_by_test_id: dict[str, str]) -> str | None:
    """The test's lecture: the table's entry for the test itself, else for the test
    without its parameters, else for its file; None if the table has none."""
    test_id_without_parameters = test_id.split("[")[0]
    file_path = test_id.split("::")[0]
    for key in [test_id, test_id_without_parameters, file_path]:
        if key in lecture_by_test_id:
            return lecture_by_test_id[key]
    return None


def _extension_paths_on_command_line(config: pytest.Config) -> list[Path]:
    """The files and folders inside an extensions folder that the command line
    names."""
    named_paths = []
    for argument in config.args:
        path = (config.invocation_params.dir / argument.split("::")[0]).resolve()
        root = config.rootpath.resolve()
        if not path.is_relative_to(root):
            continue
        if EXTENSIONS_FOLDER in path.relative_to(root).parts:
            named_paths.append(path)
    return named_paths


def _qualified_name_in(stub_message: str) -> str:
    """The function a stub's message names, as `Book.get_best_order`."""
    stub_message_match = STUB_MESSAGE_PATTERN.fullmatch(stub_message)
    assert stub_message_match is not None, f"not a stub's message: {stub_message!r}"
    return stub_message_match["qualified_name"]


def _tests_in_words(count: int) -> str:
    return "1 test" if count == 1 else f"{count} tests"


def _outcome(reports: list[pytest.TestReport]) -> str:
    """What one test came to, from its reports: failed if the test itself failed, an
    error if setting it up or tearing it down did, skipped, or passed."""
    if any(report.failed and report.when == "call" for report in reports):
        return "failed"
    if any(report.failed for report in reports):
        return "error"
    if any(report.skipped for report in reports):
        return "skipped"
    return "passed"


def _counts_in_words(counts: dict[str, int], *, uncollected_file_count: int) -> str:
    """`3 passed, 1 failed, 1 file not collected`: the outcomes that happened, in
    pytest's words, then the files that could not be collected."""
    descriptions = []
    for outcome in OUTCOMES_IN_SUMMARY_ORDER:
        count = counts[outcome]
        if count == 0:
            continue
        word = "errors" if outcome == "error" and count > 1 else outcome
        descriptions.append(f"{count} {word}")
    if uncollected_file_count == 1:
        descriptions.append("1 file not collected")
    elif uncollected_file_count > 1:
        descriptions.append(f"{uncollected_file_count} files not collected")
    return ", ".join(descriptions)
