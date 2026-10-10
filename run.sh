#!/usr/bin/env bash
# Start Network Test Tool on Linux, creating a local virtual environment on first run.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python main.py "$@"
