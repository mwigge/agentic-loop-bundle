#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="v0.128.0"
RUNTIME="$HERE/.runtime/$VERSION"
ARCHIVE="$HERE/.runtime/signoz-$VERSION.tar.gz"

download() {
  command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 1; }
  mkdir -p "$HERE/.runtime"
  if [[ ! -f "$RUNTIME/deploy/docker/docker-compose.yaml" ]]; then
    echo "Downloading the pinned SigNoz $VERSION standalone Compose bundle..."
    rm -rf "$RUNTIME"
    mkdir -p "$RUNTIME"
    curl -fsSL "https://github.com/SigNoz/signoz/archive/refs/tags/$VERSION.tar.gz" -o "$ARCHIVE"
    tar -xzf "$ARCHIVE" -C "$RUNTIME" --strip-components=1
  fi
}

compose() {
  download
  docker compose -f "$HERE/docker-compose.yml" "$@"
}

case "${1:-}" in
  up)
    compose up -d --remove-orphans
    cat <<'EOF'
SigNoz is starting.
  UI:        http://localhost:8080
  OTLP HTTP: http://localhost:4318
  OTLP gRPC: http://localhost:4317

Export traces from this shell with:
  export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
EOF
    ;;
  down) compose down ;;
  status) compose ps ;;
  logs) compose logs --tail=200 "${@:2}" ;;
  pull) compose pull ;;
  *)
    echo "Usage: $0 up|down|status|logs|pull" >&2
    exit 2
    ;;
esac
