#!/usr/bin/env bash
set -euo pipefail

command -v docker >/dev/null 2>&1 || {
  echo "Docker is required for the per-slice smoke gate." >&2
  exit 1
}

image="agentic-loop-smoke:$(basename "$PWD" | tr -cs '[:alnum:]_.-' '-')"
docker build -f .agentic-loop/docker/Dockerfile -t "$image" .agentic-loop
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -e LOOP_IN_CONTAINER=1 \
  -v "$PWD:/workspace" \
  -w /workspace \
  "$image" \
  bash -lc "git config --global --add safe.directory /workspace && ./.agentic-loop/bin/verify.sh"
