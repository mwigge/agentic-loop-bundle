#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git -C "$TMP" init -q
git -C "$TMP" config user.name test
git -C "$TMP" config user.email test@example.com
printf '# Docker smoke fixture\n' > "$TMP/README.md"
git -C "$TMP" add README.md
git -C "$TMP" commit -qm initial

AGENTIC_LOOP_SOURCE_DIR="$ROOT" "$ROOT/install.sh" --github --target "$TMP"
cp -a "$ROOT/tests/fixtures/docker-smoke/." "$TMP/"
chmod +x "$TMP/scripts/verify.sh"
chmod +x "$TMP/scripts/test.sh"

(
  cd "$TMP"
  ./.agentic-loop/bin/verify.sh
)

echo "Docker slice smoke test passed"
