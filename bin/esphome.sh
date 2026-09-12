#!/usr/bin/env bash
# ESPHome CLIラッパー。
#
# - 初回実行時に esphome/.venv を自動作成してesphomeをpipインストールし、
#   以降はそれを使い回す。
# - ESP-IDFは自前ダウンロードさせず、システムに既にインストール済みの
#   ESP-IDF (デフォルト: /opt/esp-idf5.5.1) を `IDF_PATH` として使う。
#   ESPHomeは IDF_PATH が環境変数で設定済みならそれをそのまま使い、
#   自前でのフレームワーク/ツールチェーンダウンロードをスキップする
#   (esphome/espidf/toolchain.py の _get_idf_path() 参照)。
#   別のESP-IDFを使いたい場合は `IDF_INSTALL_DIR=/opt/esp-idf` のように
#   環境変数で上書きできる。
# - PlatformIOの状態(Improv/noise-c/libsodium等、小さい依存ライブラリの
#   ダウンロード先)は esphome/.platformio 配下に閉じ込める
#   (ホームディレクトリを汚さない/$HOMEに書けない実行環境でも動くように)。
#
# 使い方:
#   bin/esphome.sh config irhub-node-c5.yaml
#   bin/esphome.sh compile irhub-node-c5.yaml
#   bin/esphome.sh run irhub-node-c6.yaml
#   bin/esphome.sh <esphomeへ渡す任意のサブコマンド...>
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ESPHOME_DIR="$ROOT_DIR/esphome"
VENV_DIR="$ESPHOME_DIR/.venv"

IDF_INSTALL_DIR="${IDF_INSTALL_DIR:-/opt/esp-idf5.5.1}"

if [ ! -x "$VENV_DIR/bin/esphome" ]; then
  echo "[bin/esphome.sh] esphome未インストール。venvを作成します: $VENV_DIR" >&2
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip -q
  "$VENV_DIR/bin/pip" install esphome -q
fi

if [ ! -f "$ESPHOME_DIR/secrets.yaml" ]; then
  echo "[bin/esphome.sh] esphome/secrets.yaml が見つかりません。" >&2
  echo "  cp esphome/secrets.yaml.example esphome/secrets.yaml として値を埋めてください。" >&2
  exit 1
fi

# システムインストール済みのESP-IDFをそのまま使う(自前DL防止)。
if [ -z "${IDF_PATH:-}" ]; then
  if [ -f "$IDF_INSTALL_DIR/export.sh" ]; then
    # shellcheck disable=SC1090
    source "$IDF_INSTALL_DIR/export.sh" >/dev/null
  else
    echo "[bin/esphome.sh] 警告: $IDF_INSTALL_DIR/export.sh が見つかりません。" >&2
    echo "  ESPHomeが独自にESP-IDFをダウンロードします。" >&2
    echo "  既存のESP-IDFを使いたい場合は IDF_INSTALL_DIR=/path/to/esp-idf を指定してください。" >&2
  fi
fi

# PlatformIOのstate/小依存ライブラリDL先をプロジェクト内に固定。
export PLATFORMIO_CORE_DIR="${PLATFORMIO_CORE_DIR:-$ESPHOME_DIR/.platformio}"
mkdir -p "$PLATFORMIO_CORE_DIR"

cd "$ESPHOME_DIR"
exec "$VENV_DIR/bin/esphome" "$@"
