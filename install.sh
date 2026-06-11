#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

VERSION="0.1.0"
REPOSITORY="${AGENTIC_LOOP_REPOSITORY:-mwigge/agentic-loop-bundle}"
REF="${AGENTIC_LOOP_REF:-main}"
PLATFORM=""
TARGET="$(pwd)"
WITH_SIGNOZ=0
FORCE=0
DRY_RUN=0
INSTALL_DEPS=0
CONFIGURE_REMOTE=0
SOURCE_DIR="${AGENTIC_LOOP_SOURCE_DIR:-}"
TEMP_DIR=""

usage() {
  cat <<'EOF'
Install an agent loop into an existing Git repository.

Usage:
  curl -fsSL https://raw.githubusercontent.com/mwigge/agentic-loop-bundle/main/install.sh \
    | bash -s -- --github [options]

Platforms:
  --github                  Install GitHub issue and Actions workflows
  --gitlab                  Install GitLab CI workflow

Options:
  --target DIR              Repository to configure (default: current directory)
  --with-signoz             Add the standalone SigNoz Docker Compose example
  --install-deps            Install OpenSpec, quality, and telemetry dependencies
  --configure-remote        Create lifecycle labels using gh or glab
  --ref REF                 Download a branch or tag (default: main)
  --force                   Back up and replace existing managed files
  --dry-run                 Print changes without writing files
  -h, --help                Show this help

Environment:
  AGENTIC_LOOP_SOURCE_DIR   Use a local bundle checkout instead of downloading
  AGENTIC_LOOP_REPOSITORY   Override GitHub owner/repository
  AGENTIC_LOOP_REF          Override the downloaded branch or tag
EOF
}

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --github|--gitlab)
      [[ -z "$PLATFORM" ]] || die "choose exactly one platform"
      PLATFORM="${1#--}"
      shift
      ;;
    --target)
      [[ $# -ge 2 ]] || die "--target requires a directory"
      TARGET="$2"
      shift 2
      ;;
    --with-signoz) WITH_SIGNOZ=1; shift ;;
    --install-deps) INSTALL_DEPS=1; shift ;;
    --configure-remote) CONFIGURE_REMOTE=1; shift ;;
    --force) FORCE=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --ref)
      [[ $# -ge 2 ]] || die "--ref requires a value"
      REF="$2"
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ -n "$PLATFORM" ]] || die "one of --github or --gitlab is required"
[[ -d "$TARGET" ]] || die "target does not exist: $TARGET"
TARGET="$(cd "$TARGET" && pwd)"
[[ -d "$TARGET/.git" ]] || die "target is not a Git repository: $TARGET"

cleanup() {
  [[ -z "$TEMP_DIR" ]] || rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

if [[ -z "$SOURCE_DIR" ]]; then
  command -v curl >/dev/null 2>&1 || die "curl is required"
  command -v tar >/dev/null 2>&1 || die "tar is required"
  TEMP_DIR="$(mktemp -d)"
  archive="$TEMP_DIR/bundle.tar.gz"
  url="https://github.com/$REPOSITORY/archive/refs/heads/$REF.tar.gz"
  if [[ "$REF" == v* || "$REF" =~ ^[0-9]+\.[0-9]+ ]]; then
    url="https://github.com/$REPOSITORY/archive/refs/tags/$REF.tar.gz"
  fi
  printf 'Downloading %s at %s...\n' "$REPOSITORY" "$REF"
  curl -fsSL "$url" -o "$archive"
  mkdir -p "$TEMP_DIR/source"
  tar -xzf "$archive" -C "$TEMP_DIR/source" --strip-components=1
  SOURCE_DIR="$TEMP_DIR/source"
else
  SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
fi

[[ -f "$SOURCE_DIR/runtime/loopctl.py" ]] || die "invalid bundle source: $SOURCE_DIR"

BACKUP_DIR="$TARGET/.agentic-loop/backups/$(date -u +%Y%m%dT%H%M%SZ)"
MANIFEST="$TARGET/.agentic-loop/install-manifest.txt"
declare -a INSTALLED=()

install_file() {
  local source="$1"
  local relative="$2"
  local mode="${3:-0644}"
  local destination="$TARGET/$relative"
  if [[ -f "$destination" ]] && cmp -s "$source" "$destination"; then
    printf '  current %s\n' "$relative"
    [[ "$DRY_RUN" -eq 1 ]] || INSTALLED+=("$relative")
    return 0
  fi
  if [[ -e "$destination" && "$FORCE" -ne 1 ]]; then
    die "$relative already exists with local changes; re-run with --force to back it up and replace it"
  fi
  printf '  install %s\n' "$relative"
  [[ "$DRY_RUN" -eq 1 ]] && return 0
  if [[ -e "$destination" ]]; then
    mkdir -p "$BACKUP_DIR/$(dirname "$relative")"
    cp -a "$destination" "$BACKUP_DIR/$relative"
  fi
  mkdir -p "$(dirname "$destination")"
  cp "$source" "$destination"
  chmod "$mode" "$destination"
  INSTALLED+=("$relative")
}

install_tree() {
  local source_root="$1" relative_root="$2"
  local source relative mode
  while IFS= read -r -d '' source; do
    relative="${source#"$source_root"/}"
    mode="0644"
    [[ -x "$source" || "$relative" == *.sh || "$relative" == *.py ]] && mode="0755"
    install_file "$source" "$relative_root/$relative" "$mode"
  done < <(find "$source_root" -type f ! -path '*/.runtime/*' -print0 | sort -z)
}

printf 'Installing agentic-loop-bundle %s for %s into %s\n' "$VERSION" "$PLATFORM" "$TARGET"
install_tree "$SOURCE_DIR/templates/common/.agentic-loop" ".agentic-loop"
install_file "$SOURCE_DIR/runtime/loopctl.py" ".agentic-loop/bin/loopctl.py" "0755"
install_file "$SOURCE_DIR/runtime/quality_gate.py" ".agentic-loop/bin/quality_gate.py" "0755"
install_file "$SOURCE_DIR/templates/common/loopctl" "loopctl" "0755"

if [[ "$PLATFORM" == "github" ]]; then
  install_tree "$SOURCE_DIR/templates/github/.github" ".github"
else
  install_file "$SOURCE_DIR/templates/gitlab/.gitlab-ci.agentic-loop.yml" ".gitlab-ci.agentic-loop.yml"
  if [[ ! -e "$TARGET/.gitlab-ci.yml" ]]; then
    install_file "$SOURCE_DIR/templates/gitlab/.gitlab-ci.yml" ".gitlab-ci.yml"
  else
    printf '  note: add `include: local: .gitlab-ci.agentic-loop.yml` to the existing .gitlab-ci.yml\n'
  fi
fi

if [[ "$WITH_SIGNOZ" -eq 1 ]]; then
  install_tree "$SOURCE_DIR/examples/signoz" ".agentic-loop/observability/signoz"
fi

if [[ "$DRY_RUN" -eq 0 ]]; then
  {
    printf '# agentic-loop-bundle %s (%s)\n' "$VERSION" "$PLATFORM"
    printf '%s\n' "${INSTALLED[@]}"
  } > "$MANIFEST"
fi

if [[ "$INSTALL_DEPS" -eq 1 && "$DRY_RUN" -eq 0 ]]; then
  command -v python3 >/dev/null 2>&1 || die "python3 is required"
  command -v npm >/dev/null 2>&1 || die "npm is required to install OpenSpec"
  npm install --prefix "$TARGET/.agentic-loop/tools" @fission-ai/openspec@1.4.1
  python3 -m venv "$TARGET/.agentic-loop/python"
  "$TARGET/.agentic-loop/python/bin/pip" install \
    -r "$TARGET/.agentic-loop/quality-requirements.txt" \
    -r "$TARGET/.agentic-loop/requirements.txt"
fi

if [[ "$CONFIGURE_REMOTE" -eq 1 && "$DRY_RUN" -eq 0 ]]; then
  "$SOURCE_DIR/scripts/configure-remote.sh" "$PLATFORM" "$TARGET"
fi

cat <<EOF

Installation complete.

  Check:   ./loopctl doctor
  Test:    ./loopctl telemetry-test
  Propose: ./loopctl propose --change my-change --task "Describe the outcome"
  Run:     ./loopctl run --change my-change
EOF
if [[ "$WITH_SIGNOZ" -eq 1 ]]; then
  cat <<'EOF'
  Observe: ./.agentic-loop/observability/signoz/signoz.sh up
           export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
EOF
fi
