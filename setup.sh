#!/usr/bin/env bash
# Set up imap-mcp on macOS/Linux.
# Only requires Python 3.11+ installed (python3 on PATH).
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$root/.venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$root/.venv"
fi
echo "Installing dependencies..."
"$root/.venv/bin/python" -m pip install --quiet -r "$root/requirements.txt"

"$root/.venv/bin/python" "$root/install.py"
