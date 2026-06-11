#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
import pathlib
import runpy

for path in sorted(pathlib.Path("tests").glob("test_*.py")):
    namespace = runpy.run_path(str(path))
    for name, value in namespace.items():
        if name.startswith("test_") and callable(value):
            value()
PY
