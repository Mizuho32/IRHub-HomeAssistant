#!/usr/bin/env bash
# IRHub ESPHomeノードのビルド(コンパイルのみ、書き込みはしない)。
#
# 使い方:
#   bin/build.sh          # c5・c6両方をビルド
#   bin/build.sh c5        # C5のみ
#   bin/build.sh c6        # C6のみ
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-all}"

build_one() {
  local chip="$1"
  echo "=== Building irhub-node-${chip}.yaml ==="
  "$ROOT_DIR/bin/esphome.sh" compile "irhub-node-${chip}.yaml"
}

case "$TARGET" in
  c5) build_one c5 ;;
  c6) build_one c6 ;;
  all)
    build_one c5
    build_one c6
    ;;
  *)
    echo "usage: $0 [c5|c6]" >&2
    exit 1
    ;;
esac
