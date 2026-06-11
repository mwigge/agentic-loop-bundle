#!/usr/bin/env bash
set -euo pipefail

test "$(python3 app.py)" = "ok"
python3 - <<'PY'
from app import message
assert message() == "ok"
PY
