#!/usr/bin/env bash
# 書き込みはせず、シリアルログだけを監視する。
#
# `esphome logs` は接続が切れると再接続しない上、外側でループさせても
# 毎回ESPHomeのCLIプロセスを丸ごと起動し直すため、再起動ループの周期が
# 短いボードでは何も見えない。代わりに bin/raw_monitor.py
# (プロセス起動しっぱなしで、ポートのopen/closeだけを高速リトライする)
# を使う。ログは esphome/monitor-<chip>.log にも追記される。Ctrl+Cで終了。
#
# 使い方:
#   bin/monitor.sh c5                 # 自動検出されたシリアルポートを監視
#   bin/monitor.sh c5 /dev/ttyACM0    # ポートを明示指定
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ESPHOME_DIR="$ROOT_DIR/esphome"
VENV_DIR="$ESPHOME_DIR/.venv"
CHIP="${1:?usage: $0 <c5|c6> [device]}"
DEVICE="${2:-}"

case "$CHIP" in
  c5|c6) ;;
  *)
    echo "error: 第1引数はチップ種別 'c5' か 'c6' を指定してください(渡された値: '$CHIP')" >&2
    echo "usage: $0 <c5|c6> [device]" >&2
    echo "  例: $0 c5 /dev/ttyACM0" >&2
    exit 1
    ;;
esac

if [ ! -x "$VENV_DIR/bin/python3" ]; then
  echo "[bin/monitor.sh] esphome/.venvが見つかりません。先に bin/build.sh 等を一度実行してください。" >&2
  exit 1
fi

LOG_FILE="$ESPHOME_DIR/monitor-${CHIP}.log"

ARGS=("$VENV_DIR/bin/python3" "$ROOT_DIR/bin/raw_monitor.py" --log "$LOG_FILE")
if [ -n "$DEVICE" ]; then
  ARGS+=("$DEVICE")
fi

exec "${ARGS[@]}"
