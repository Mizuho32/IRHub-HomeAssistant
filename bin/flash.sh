#!/usr/bin/env bash
# 書き込みのみ (esphome upload)。ビルドはしない、pure flash。
# `esphome run` と違い write_cpp/compile を一切呼ばず、既存のビルド成果物
# (.esphome/build/<name>/build/*.bin) をそのまま書き込むだけ。
# 事前に `bin/build.sh <c5|c6>` でビルド済みであること。
#
# 使い方:
#   bin/flash.sh c5                 # 自動検出されたシリアルポートに書き込み
#   bin/flash.sh c5 /dev/ttyACM0    # ポートを明示指定
#   bin/flash.sh c5-thread          # Thread版(実験)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHIP="${1:?usage: $0 <c5|c6|c5-thread|c6-thread|c6-desk|c6-calib> [device]}"
DEVICE="${2:-}"

case "$CHIP" in
  c5|c6|c5-thread|c6-thread|c6-desk|c6-calib) ;;
  *)
    echo "error: 第1引数はチップ種別 'c5'/'c6'/'c5-thread'/'c6-thread'/'c6-desk'/'c6-calib' を指定してください(渡された値: '$CHIP')" >&2
    echo "usage: $0 <c5|c6|c5-thread|c6-thread|c6-desk|c6-calib> [device]" >&2
    echo "  例: $0 c5 /dev/ttyACM0" >&2
    exit 1
    ;;
esac

ARGS=(upload "irhub-node-${CHIP}.yaml")
if [ -n "$DEVICE" ]; then
  ARGS+=(--device "$DEVICE")
fi

exec "$ROOT_DIR/bin/esphome.sh" "${ARGS[@]}"
