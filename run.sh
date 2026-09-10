#!/usr/bin/env bash
# Start Voltscope locally. Creates the virtual environment and installs
# dependencies on first run, then launches the review app.
#
#   ./run.sh
#
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment and installing dependencies (first run only)..."
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip >/dev/null
  ./.venv/bin/pip install -r requirements.txt
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo "Starting Voltscope at http://127.0.0.1:8000  (Ctrl+C to stop)"
python -m voltscope.api
