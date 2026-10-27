#!/usr/bin/env bash
# IRHub ESPHomeノードのビルド(コンパイルのみ、書き込みはしない)。
#
# 使い方:
#   bin/build.sh          # c5・c6両方(WiFi版)をビルド
#   bin/build.sh c5        # C5のみ(WiFi版)
#   bin/build.sh c6        # C6のみ(WiFi版)
#   bin/build.sh c5-thread # C5のみ(Thread版、実験。要secrets.yamlのthread_dataset_tlv)
#   bin/build.sh c6-thread # C6のみ(Thread版、実験)
#   bin/build.sh c6-desk   # C6卓上ノード(IRなし、BME280のみ)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-all}"

build_one() {
  local chip="$1"
  echo "=== Building irhub-node-${chip}.yaml ==="
  "$ROOT_DIR/bin/esphome.sh" compile "irhub-node-${chip}.yaml"
}

case "$TARGET" in
  c5|c6|c5-thread|c6-thread|c6-desk) build_one "$TARGET" ;;
  all)
    build_one c5
    build_one c6
    ;;
  *)
    echo "usage: $0 [c5|c6|c5-thread|c6-thread|c6-desk]" >&2
    exit 1
    ;;
esac
