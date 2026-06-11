#!/usr/bin/env bash
set -uo pipefail

run_test() {
  if "$@"; then
    exit 0
  fi
  exit 1
}

if [[ -x ./scripts/test.sh ]]; then
  run_test ./scripts/test.sh
fi
if [[ -f package.json ]]; then
  run_test npm test
fi
if [[ -f pyproject.toml || -f pytest.ini || -d tests ]]; then
  command -v pytest >/dev/null 2>&1 || {
    echo "pytest is required" >&2
    exit 2
  }
  run_test pytest
fi
if [[ -f go.mod ]]; then
  run_test go test ./...
fi
if [[ -f Cargo.toml ]]; then
  run_test cargo test --all-targets
fi

echo "No test command was detected. Add scripts/test.sh." >&2
exit 2
