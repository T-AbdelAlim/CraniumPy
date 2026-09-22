#!/usr/bin/env bash
# One-shot setup for a fresh checkout on macOS/Linux: creates .venv, installs
# the pinned Python dependencies, and builds the frontend (frontend/dist
# isn't in git, and both the web and desktop app serve the built output).
#
#   bash setup.sh
#
# Needs Python 3.11+ (tested on 3.14) and Node.js 20+ on PATH.
set -euo pipefail
cd "$(dirname "$0")"

command -v python3 >/dev/null || { echo "python3 not found - install Python 3.11+"; exit 1; }
command -v npm >/dev/null || { echo "npm not found - install Node.js 20+"; exit 1; }

[ -d .venv ] || { echo "Creating .venv..."; python3 -m venv .venv; }
py=.venv/bin/python

echo "Installing Python dependencies..."
"$py" -m pip install --upgrade pip
"$py" -m pip install -r requirements.txt -e .

echo "Building the frontend..."
npm --prefix frontend ci
npm --prefix frontend run build

echo
echo "Done. Run the desktop app with:"
echo "  .venv/bin/python -m desktop.app"
