"""Constants for the IRHub integration."""

DOMAIN = "irhub"

CONF_DEVICE_SLUG = "device_slug"

# ESPHome側 `on_raw` -> `homeassistant.event` で発火するイベントタイプの接尾辞。
# 実際のイベント名は f"esphome.{device_slug}{EVENT_IR_RAW_RECEIVED_SUFFIX}"
# (esphome/irhub-node.yaml の on_raw 参照)
EVENT_IR_RAW_RECEIVED_SUFFIX = "_ir_raw_received"

# ESPHome側 `api: services:` で公開しているIR送信サービス名の接尾辞。
# 実際のサービス名(HAから見た `esphome.<name>` ドメイン配下)は
# f"{device_slug}{SERVICE_SEND_RAW_SUFFIX}"
SERVICE_SEND_RAW_SUFFIX = "_send_raw"

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}_codes"

DEFAULT_LEARN_TIMEOUT = 10  # seconds
