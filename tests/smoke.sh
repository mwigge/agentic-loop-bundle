#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

assert_file() {
  [[ -f "$1" ]] || { echo "missing file: $1" >&2; exit 1; }
}

setup_repo() {
  local path="$1"
  mkdir -p "$path"
  git -C "$path" init -q
  git -C "$path" config user.name test
  git -C "$path" config user.email test@example.com
  printf '# fixture\n' > "$path/README.md"
  git -C "$path" add README.md
  git -C "$path" commit -qm initial
}

github="$TMP/github"
setup_repo "$github"
AGENTIC_LOOP_SOURCE_DIR="$ROOT" "$ROOT/install.sh" --github --target "$github" --with-signoz
AGENTIC_LOOP_SOURCE_DIR="$ROOT" "$ROOT/install.sh" --github --target "$github" --with-signoz

assert_file "$github/.github/workflows/agentic-loop.yml"
assert_file "$github/.github/ISSUE_TEMPLATE/agent-task.yml"
assert_file "$github/.agentic-loop/observability/signoz/signoz.sh"
assert_file "$github/.agentic-loop/install-manifest.txt"

cp "$ROOT/tests/fake-agent.sh" "$github/fake-agent.sh"
chmod +x "$github/fake-agent.sh"
mkdir -p "$github/tests"
printf 'def test_baseline():\n    assert True\n' > "$github/tests/test_baseline.py"
mkdir -p "$github/scripts"
cp "$ROOT/tests/fake-project-test.sh" "$github/scripts/test.sh"
chmod +x "$github/scripts/test.sh"
(
  cd "$github"
  export OPENSPEC_COMMAND="$ROOT/tests/fake-openspec.py"
  python3 - <<'PY'
import json
path = ".agentic-loop/loop.json"
config = json.load(open(path))
config["verification"]["command"] = "true"
open(path, "w").write(json.dumps(config, indent=2) + "\n")
PY
  LOOP_AGENT_COMMAND="./fake-agent.sh" ./loopctl doctor
  LOOP_AGENT_COMMAND="./fake-agent.sh" ./loopctl propose \
    --change fixture-change --task "Create the fixture result"
  run_id="$(LOOP_AGENT_COMMAND="./fake-agent.sh" \
    ./loopctl run --change fixture-change)"
  assert_file "result.txt"
  assert_file ".agentic-loop/runs/$run_id/state.json"
  assert_file ".agentic-loop/runs/$run_id/telemetry.jsonl"
  assert_file ".agentic-loop/runs/$run_id/verification.txt"
  grep -q '"status": "succeeded"' ".agentic-loop/runs/$run_id/state.json"
  grep -q '"name":"loop.run"' ".agentic-loop/runs/$run_id/telemetry.jsonl"
  test -z "$(git status --porcelain -- .agentic-loop/runs .agentic-loop/state.json)"
  sed -i '0,/- \[x\]/{s/- \[x\]/- [ ]/}' openspec/changes/fixture-change/tasks.md
  rm -f result.txt tests/test_result.py
  if FAKE_AGENT_TAMPER=1 LOOP_AGENT_COMMAND="./fake-agent.sh" \
    ./loopctl run --change fixture-change; then
    echo "runtime allowed protected loop policy to change" >&2
    exit 1
  fi
)

gitlab="$TMP/gitlab"
setup_repo "$gitlab"
AGENTIC_LOOP_SOURCE_DIR="$ROOT" "$ROOT/install.sh" --gitlab --target "$gitlab"
assert_file "$gitlab/.gitlab-ci.yml"
assert_file "$gitlab/.gitlab-ci.agentic-loop.yml"

conflict="$TMP/conflict"
setup_repo "$conflict"
mkdir -p "$conflict/.github/workflows"
printf 'custom\n' > "$conflict/.github/workflows/agentic-loop.yml"
if AGENTIC_LOOP_SOURCE_DIR="$ROOT" "$ROOT/install.sh" --github --target "$conflict" >/dev/null 2>&1; then
  echo "installer replaced a conflicting file without --force" >&2
  exit 1
fi

echo "smoke tests passed"
