#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from app import message

assert message() == "ok"
PY
