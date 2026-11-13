# The development environment: the tools, never your code, which you mount at /work.
# How to build and run it: README.md.

# Python 3.14. The same version is in .python-version and pyproject.toml, and
# tests/test_version_pin.py checks that all three agree. The base image is not pinned
# to one build, so you get today's, with its security fixes.
FROM python:3.14-slim-trixie

# bash-completion finds each command's file in share/bash-completion/completions,
# beside bin/ on the path. Git and the SSH client are for the development container,
# which lends them your machine's SSH agent, so your keys never enter the image. Under
# a plain `docker run`, as root, git stops with "detected dubious ownership"; leave it
# so, since a commit as root would leave files in your .git that only root can change.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends bash-completion git openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && echo ". /usr/share/bash-completion/bash_completion" >> /etc/bash.bashrc

COPY --from=ghcr.io/astral-sh/uv:0.12.18 /uv /bin/uv

# --locked fails the build if uv.lock is out of date.
WORKDIR /opt/homework
COPY pyproject.toml uv.lock ./
RUN UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1 \
    uv sync --locked

# The development container's user. UID 1000 is the first user on most Linux machines.
RUN useradd --uid 1000 --user-group --create-home --shell /bin/bash dev

# The tools, and the commands in your bin/, by name: `pytest`, `dev_check`.
ENV PATH="/work/bin:/opt/venv/bin:$PATH"

# pytest finds src through pyproject.toml; everything else through this.
ENV PYTHONPATH=/work/src

# A promise: inside this container, real UDP multicast between processes works.
# tests/system/test_multicast.py only runs where this is set.
ENV HOMEWORK_MULTICAST=1

# A plain `docker run` runs as root, and on Linux what it writes into /work is root's
# on your machine: so no tool's cache goes there.
ENV PYTHONPYCACHEPREFIX=/tmp/pycache
ENV PYTEST_ADDOPTS="-o cache_dir=/tmp/pytest_cache"
ENV MYPY_CACHE_DIR=/tmp/mypy_cache
ENV RUFF_CACHE_DIR=/tmp/ruff_cache

WORKDIR /work
CMD ["pytest"]
