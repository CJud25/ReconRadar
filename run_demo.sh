#!/usr/bin/env sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_ROOT="$PROJECT_ROOT/.venv"
VENV_PYTHON="$VENV_ROOT/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    python3 -m venv "$VENV_ROOT"
    "$VENV_PYTHON" -m pip install --disable-pip-version-check -r "$PROJECT_ROOT/requirements.txt"
fi

exec "$VENV_PYTHON" -m streamlit run "$PROJECT_ROOT/app.py"
