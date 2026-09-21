#!/usr/bin/env bash
# Linux / macOS convenience wrapper. All the logic lives in setup.py.
set -euo pipefail
cd "$(dirname "$0")"

for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'; then
      exec "$candidate" setup.py "$@"
    fi
  fi
done

echo "No Python 3.11+ found on PATH. Install it and re-run ./setup.sh" >&2
exit 1
