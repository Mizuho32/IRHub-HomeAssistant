#!/usr/bin/env bash
# フラッシュを全消去する (esptool erase_flash)。
#
# ブラウンアウト等でフラッシュ書き込み中にリセットがかかり、
# アプリパーティションやNVSが破損した疑いがあるときに使う。
# 全消去後は bin/build.sh && bin/flash.sh で焼き直すこと
# (WiFi資格情報もNVSごと消えるので、improv_serialで再プロビジョニングが必要)。
#
# 使い方:
#   bin/erase.sh                 # 自動検出されたシリアルポート
#   bin/erase.sh /dev/ttyACM0    # ポートを明示指定
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/esphome/.venv"
DEVICE="${1:-}"

if [ ! -x "$VENV_DIR/bin/python3" ]; then
  echo "[bin/erase.sh] esphome/.venvが見つかりません。先に bin/build.sh 等を一度実行してください。" >&2
  exit 1
fi

ARGS=(-m esptool)
if [ -n "$DEVICE" ]; then
  ARGS+=(--port "$DEVICE")
fi
ARGS+=(erase_flash)

echo "[bin/erase.sh] フラッシュを全消去します(WiFi資格情報も消えます)..." >&2
exec "$VENV_DIR/bin/python3" "${ARGS[@]}"
