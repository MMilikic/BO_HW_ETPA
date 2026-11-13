# The homework exchange

A deliberately **simplified** exchange, built to be read. Over the course you write its
central parts yourself, a function at a time, and the tests tell you when they work.
This file is the same in every week's package; each week's homework is in
`doc/homework/`.

## Start here

- **You need Docker** 23 or later, or a runtime that runs the same commands. Nothing
  else is needed: Python and the tools come in the image.
- **Pick one way to work:** IntelliJ IDEA Ultimate or VS Code, each opening this folder
  in its development container, or a terminal. Each has its section below.
- **Most of this week's tests fail at first.** Those are your homework: each passes
  once the code it tests is written.
- **This week's homework** is the newest file in `doc/homework/`, in the first week
  `doc/homework/L01.md`: what to write, and where.
- **Each new week**, unzip its increment over this folder, from this folder:
  `unzip -o path/to/homework-exchange-L02-increment.zip`. Unzip each increment once, in
  order; for a week you missed, see "Each week's package".
- **Stuck?** Send me a Slack message, or ask for help in your group's Slack channel.

## What it is not

This exchange is written for teaching purposes and lacks many things not relevant to
the course:

- no authentication: whoever connects says who they are;
- no persistence: the venue records everything in its journal but never reads it back,
  so a restart starts with an empty book and overwrites the last run's journal;
- no security model, and no protocol versioning;
- one instrument and one order book.

None of this is how a real venue works. Each part the course does build is simplified
too, and the code says where.

## Your folder

- `src/`: the exchange. The files you write in are the ones `doc/homework/` lists.
- `tests/`: the tests.
- `doc/homework/`: one file per week, each week's arriving with it.
- `bin/`: the commands, below.
- `extensions.toml`: the optional parts of the homework you have switched on. Each
  week's description says how.

Everything but the files you write in is ours, and a later week's package may replace
it.

## In IntelliJ

IntelliJ IDEA Ultimate 2026.1 or later, which needs a licence, opens this folder in its
development container, `.devcontainer/`: the same image, with your folder mounted.
Once:

1. Remote Development, then Dev Containers: from a local project, with Docker, in
   IntelliJ IDEA, and open this folder's `.devcontainer/devcontainer.json`. The first
   time takes a few minutes.
2. Trust the project.

The run configuration `pytest` runs every test, and the icon beside each test runs that
one. Each file is formatted as you save it. IntelliJ's terminal runs inside the
container, where the commands below work by name. The settings in `.idea/` are yours
from then on.

If the project has no Python SDK named `homework-exchange`, add it: Project Structure,
Platform Settings, SDKs, add a Python SDK from disk, choose `/opt/venv/bin/python`, and
name it `homework-exchange`. Not the Python 3.14 that IntelliJ finds in
`/usr/local/bin`, which has none of the tools.

## In VS Code

VS Code, which is free, with Microsoft's Dev Containers extension, opens this folder in
its development container, `.devcontainer/`: the same image, with your folder mounted.
Once:

1. Open this folder in VS Code, and trust it.
2. Reopen in Container, when VS Code offers it, or from the Command Palette: Dev
   Containers: Reopen in Container. The first time takes a few minutes.

The tests are in the Testing view, the flask in the sidebar: the icon beside each test
runs or debugs that one, and the one at the top runs every test. Each file is formatted
as you save it. VS Code's terminal runs inside the container, where the commands below
work by name. The interpreter is `/opt/venv/bin/python`, not the Python 3.14 in
`/usr/local/bin`. To change a setting, set it in this folder's `.vscode/settings.json`.

## In a terminal

From this folder, build the image once, then run the tests:

```
docker build -t homework-exchange .
docker run --rm -it -v .:/work -w /work homework-exchange pytest
```

To run some tests only, add `-k` and part of their names after `pytest`: `pytest -k
empty_book` runs only those with `empty_book` in their names.
A test that reaches a function you have not written yet shows as one line, under
"waiting for your code"; `pytest --tb=short` shows its traceback instead.

- **Build once.** The image holds Python and the tools, never your code, so a new
  week's files need no rebuild. You build it yourself: there is nothing of ours to pull,
  and no login.
- **`-v .:/work` lends the container your folder.** You edit with your own editor on
  your own machine; the container runs what you wrote.

From L2 the venue runs too. Start it in one terminal, and in another open a client in
the same container:

```
docker run --rm -it --name exchange -v .:/work -w /work homework-exchange run_exchange
docker exec -it exchange order_console -p 1
```

`-p` says who you are: participant 1 or 2. A second client with `-p 2` trades with the
first. Ctrl-C stops the venue.

### The commands

Inside the container, the IDEs' terminals included, the programs in `bin/` run by name,
and Tab completes their options. In IntelliJ, `dev_check` and the programs from L2 on
have a run configuration too, named as the command is typed (`order_console -p 1`). A
program's run configuration arrives with the program.

- `dev_test` is `pytest`, from any folder.
- `dev_check` runs every check the code is held to: ruff (a linter), the formatting
  (`dev_format` fixes it), mypy (the type hints), then the tests. Nothing requires it;
  it says how your code stands.
- From L2, `run_exchange`, the venue; `order_prompt` and `order_console`, to send it
  orders; `print_journal`, to read what it recorded. From L3, the feed's:
  `print_incremental_channel`, `print_snapshot_channel`, `print_feed` and
  `feed_console`. Each tool's `--help` says what it takes.

### Without the container

Install uv and run `uv run pytest`; any command in `bin/` runs the same way, as `uv run
bin/dev_check`, and a few tests that need the container skip. In bash, `. bin/activate`
puts `bin/` on your path, with Tab completion, inside the environment uv makes (`.
.venv/bin/activate`); `deactivate_exchange` undoes it.

## Each week's package

Each lecture with homework comes as three zips, here L3's:

- **The increment**, `homework-exchange-L03-increment.zip`: this week's homework, for
  the folder you already have. From that folder, `unzip -o
  path/to/homework-exchange-L03-increment.zip`; do not double-click it, which unpacks it
  into a new folder instead. It never touches a file you wrote in during an earlier
  week. Unzip each increment once, in order: unzip any you missed before this week's.
  Unzipping one again overwrites that week's new files, your work in them included.
- **The fresh package**, `homework-exchange-L03.zip`: the whole project, every earlier
  week filled in and this week's left for you. It is the reset button: unzip it
  somewhere new.
- **The solution**, `homework-exchange-L03-solution.zip`, released with L4: L3's
  answers, for a week you skipped. If you skipped L3, unzip L3's increment if you never
  unzipped it, then L3's solution, then L4's increment, each the same way. The solution
  overwrites L3's files, and any earlier file of yours that L3 changes, so use it only
  for a week you skipped.

**When a later week needs something in your own files**, you add it: the week's
description gives it, under "Code to add to your own files" and "Changes to your own
code". `pytest` checks the code to add before anything else, and stops there until it
is in place.

**Git, if you use it**, is in the image too. Commit each increment on its own before
writing anything, and your own work before unzipping the next: a week's work is then one
diff, and an increment unzipped twice is undone with git. Run it on your own machine or
in the development container, not through `docker run`, where it runs as root: on Linux
git refuses your folder, and the fix it suggests leaves files in `.git` that only root
can change.

To push over SSH from the development container, your keys stay on your machine: the
editor lends the container your SSH agent (IntelliJ asks once: choose to forward it;
VS Code does not ask). The first connection may ask whether to trust the server's key:
answer `yes`, in the terminal.
