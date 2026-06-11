#!/usr/bin/env bash
set -euo pipefail

python3 .agentic-loop/bin/quality_gate.py
./.agentic-loop/bin/test.sh

if [[ "${LOOP_IN_CONTAINER:-0}" != "1" ]]; then
  exec .agentic-loop/bin/smoke.sh
fi

if [[ -x ./scripts/verify.sh ]]; then
  exec ./scripts/verify.sh
fi
if [[ -f Makefile ]] && grep -Eq '^verify:' Makefile; then
  exec make verify
fi
if [[ -f package.json ]]; then
  if command -v npm >/dev/null 2>&1; then
    npm test
    npm run lint --if-present
    exit 0
  fi
fi
if [[ -f pyproject.toml || -f pytest.ini || -d tests ]]; then
  if command -v pytest >/dev/null 2>&1; then
    exec pytest
  fi
fi
if [[ -f go.mod ]]; then
  exec go test ./...
fi
if [[ -f Cargo.toml ]]; then
  exec cargo test --all-targets
fi

echo "Quality and container smoke checks passed; no additional project verifier was detected."
