#!/usr/bin/env bash
set -euo pipefail

platform="${1:?platform is required}"
target="${2:?target is required}"
cd "$target"

labels=(
  "agent:queued|6f42c1|Task proposed for an agent loop"
  "agent:ready|0e8a16|Approved by a maintainer"
  "agent:running|1d76db|Agent loop is active"
  "agent:review|bf8700|Loop completed; human review required"
  "agent:failed|d73a4a|Loop needs human attention"
)

if [[ "$platform" == "github" ]]; then
  command -v gh >/dev/null 2>&1 || { echo "gh is required" >&2; exit 1; }
  for item in "${labels[@]}"; do
    IFS='|' read -r name color description <<<"$item"
    gh label create "$name" --color "$color" --description "$description" --force
  done
else
  command -v glab >/dev/null 2>&1 || { echo "glab is required" >&2; exit 1; }
  for item in "${labels[@]}"; do
    IFS='|' read -r name color description <<<"$item"
    glab label create "$name" --color "#$color" --description "$description" 2>/dev/null || true
  done
fi
