#!/usr/bin/env bash
# improv_serial経由でWiFi資格情報をデバイスに送る (Improv Wi-Fi over Serial)。
# ブラウザ(Web Serial API)を使わず、CLIだけで完結させるためのラッパー。
#
# 使い方:
#   bin/wifi_setup.sh                            # 自動検出ポート、対話入力
#   bin/wifi_setup.sh /dev/ttyACM0
#   bin/wifi_setup.sh --ssid MyWiFi --password xxxxx
#   bin/wifi_setup.sh --info                      # 現在の状態だけ確認
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/esphome/.venv"

if [ ! -x "$VENV_DIR/bin/python3" ]; then
  echo "[bin/wifi_setup.sh] esphome/.venvが見つかりません。先に bin/build.sh 等を一度実行してください。" >&2
  exit 1
fi

ARGS=()
# 第1引数が /dev/... っぽければ --device として扱う(素のポート指定を許容)。
if [ $# -gt 0 ] && [[ "$1" == /dev/* ]]; then
  ARGS+=(--device "$1")
  shift
fi
ARGS+=("$@")

exec "$VENV_DIR/bin/python3" "$ROOT_DIR/bin/improv_wifi.py" "${ARGS[@]}"
