#!/usr/bin/env bash
# Run a command with every tool, cache and temporary file kept inside the project.
#
# Usage: scripts/env.sh <command> [args...]
#
# Nothing here writes to the home directory: uv, pip, Python installs, XDG caches and
# temporary files all resolve to .tools/ and .tmp/ (both git-ignored).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/.tools"

# uv: cache, managed Python builds and their executables stay in .tools/.
export UV_CACHE_DIR="$TOOLS/cache/uv"
export UV_PYTHON_INSTALL_DIR="$TOOLS/python"
export UV_PYTHON_BIN_DIR="$TOOLS/bin"
export UV_TOOL_DIR="$TOOLS/uv-tools"
export UV_TOOL_BIN_DIR="$TOOLS/bin"
# Only the Python installed into .tools/python is used; nothing is downloaded implicitly.
export UV_PYTHON_PREFERENCE="only-managed"
export UV_PYTHON_DOWNLOADS="manual"

# pip and Python user paths, in case any tool falls back to them.
export PIP_CACHE_DIR="$TOOLS/cache/pip"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PYTHONUSERBASE="$TOOLS/userbase"

# Generic XDG locations used by many tools.
export XDG_CACHE_HOME="$TOOLS/cache"
export XDG_DATA_HOME="$TOOLS/data"
export XDG_CONFIG_HOME="$TOOLS/config"

export TMPDIR="$ROOT/.tmp"
# The pinned uv in .tools/bootstrap comes first: Home Assistant installs its own uv into .venv.
export PATH="$TOOLS/bootstrap/bin:$ROOT/.venv/bin:$TOOLS/bin:$PATH"

mkdir -p "$TMPDIR"

if [ "$#" -eq 0 ]; then
    echo "usage: scripts/env.sh <command> [args...]" >&2
    exit 2
fi

exec "$@"
