#!/usr/bin/env bash
set -euo pipefail
prompt="$(cat)"
current_task="$(printf '%s\n' "$prompt" | awk '/Current (OpenSpec )?task slice:/{getline; getline; print; exit}')"

case "${AGENTIC_LOOP_STAGE:-}" in
  propose)
    change="$(find openspec/changes -mindepth 1 -maxdepth 1 -type d ! -name archive -printf '%f\n' | head -1)"
    mkdir -p "openspec/changes/$change/specs/fixture"
    printf '## Why\n\nSmoke test.\n\n## What Changes\n\n- Add fixture behavior.\n\n## Capabilities\n\n### New Capabilities\n- `fixture`: Test fixture.\n\n### Modified Capabilities\n\n## Impact\n\nTests only.\n' > "openspec/changes/$change/proposal.md"
    printf '## Context\n\nSmoke fixture.\n\n## Goals / Non-Goals\n\n**Goals:** verify loops.\n\n## Decisions\n\nUse a text file.\n' > "openspec/changes/$change/design.md"
    printf '## ADDED Requirements\n\n### Requirement: Fixture output\nThe system SHALL create the fixture output.\n\n#### Scenario: Successful loop\n- **WHEN** the loop runs\n- **THEN** result.txt exists\n' > "openspec/changes/$change/specs/fixture/spec.md"
    printf '## 1. Implementation\n\n- [ ] 1.1 Create result.txt\n- [ ] 1.2 Run verification\n' > "openspec/changes/$change/tasks.md"
    echo "Created apply-ready OpenSpec artifacts."
    ;;
  test)
    mkdir -p tests
    if [[ "$current_task" == *"1.1 Create result.txt"* ]]; then
      cat > tests/test_result.py <<'PY'
from pathlib import Path


def test_result_exists() -> None:
    assert Path("result.txt").read_text() == "implemented by the fake agent\n"
PY
    else
      cat > tests/test_second_slice.py <<'PY'
from pathlib import Path


def test_second_slice_exists() -> None:
    assert Path("second-slice.txt").read_text() == "done\n"
PY
    fi
    echo "Added a failing test."
    ;;
  implement)
    if [[ "$current_task" == *"1.1 Create result.txt"* ]]; then
      printf 'implemented by the fake agent\n' > result.txt
    else
      printf 'done\n' > second-slice.txt
    fi
    sed -i '0,/- \[ \]/{s/- \[ \]/- [x]/}' openspec/changes/*/tasks.md
    if [[ "${FAKE_AGENT_TAMPER:-0}" == "1" ]]; then
      printf '#!/usr/bin/env bash\nexit 0\n' > .agentic-loop/bin/verify.sh
    fi
    echo "Created result.txt"
    ;;
  review)
    echo "No blocking findings."
    ;;
  *)
    echo "Unexpected stage: ${AGENTIC_LOOP_STAGE:-unset}" >&2
    exit 2
    ;;
esac
