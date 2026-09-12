# IRHub 実装ノート（あれこれ）

[`2026-09-10_IRHub.md`](./2026-09-10_IRHub.md)（初期調査）・[`2026-09-10_IRHub-plan.md`](./2026-09-10_IRHub-plan.md)（初期実装プラン）を前提に、実装を進める中での決定事項・修正・issue・TODOをここに随時追記していく。

## 決定事項・修正ログ

### 2026-09-10

- **ESP32チップをC6からC5に変更**。プランドキュメント初版では「C5は802.15.4無線を持たずThread化できない」としていたが誤り。実際にはESP32-C5は2.4/5GHzデュアルバンドWiFi6 + BLE5 + 802.15.4（Zigbee 3.0 / Thread 1.3〜1.4）を搭載しており、Thread対応可能。ユーザーが実機として[Switch Science扱いのESP32-C5HR8ボード](https://www.switch-science.com/products/10978)を保有しているため、これを前提に進める。
  - ESPHomeの`esp32:`設定は`board: esp32-c5-devkitc-1`、`framework: esp-idf`（C5もC6同様、OpenThreadはesp-idf限定でArduino不可）。
  - Seeed XIAO ESP32-C5含め、サードパーティ基板でも`esp32-c5-devkitc-1`のboard idで動作する例あり（要実機確認）。
- **WiFi資格情報をバイナリに焼き込まない方針に変更**。当初案は`wifi: ssid/password: !secret ...`でコンパイル時埋め込みだったが、「WiFi変更のたびに再ビルドしたくない」という要望のため、**`improv_serial`**（USBシリアル経由のImprov標準プロビジョニング）に変更。
  - `wifi:`ブロックからssid/passwordを削除し、空の`wifi:` + `improv_serial:`のみを記述。
  - 資格情報はコンパイル済みバイナリではなく、デバイス上のNVS（flashのパーティション）に実行時保存される。OTA更新（flash消去を伴わない）でも保持されるため、WiFiを変える度の再ビルド・再書き込みは不要。
  - `secrets.yaml`からも`wifi_ssid`/`wifi_password`を削除（`api_encryption_key`のみ残す）。
  - 初回プロビジョニング手順（未実施・要検証）: `esphome run irhub-node.yaml`で書き込み後、USBシリアル接続した状態で https://www.improv-wifi.com/serial/ （またはesphome CLIが出すプロンプト）からSSID/パスワードを送信する想定。

## ディレクトリ/ファイル現況

```
esphome/
  irhub-node.yaml       # C5 + improv_serial 反映済み。実機未検証。
  secrets.yaml.example  # api_encryption_keyのみ
  .gitignore
ha/custom_components/irhub/
  manifest.json / const.py / __init__.py / config_flow.py / remote.py
  .gitignore
```

## Phase 0 TODOチェックリスト（実機着手用）

- [ ] ESP32-C5実機にピン割り当てを決めて`irhub-node.yaml`の`substitutions`を実際の値に更新
  - [ ] `ir_receiver_pin`
  - [ ] `ir_transmitter_pin`
  - [ ] `status_led_pin`
- [ ] `secrets.yaml`を`secrets.yaml.example`からコピーして`api_encryption_key`を生成・設定
- [ ] `esphome run irhub-node.yaml`でビルド・書き込み（esp-idfフレームワークでのC5ビルドが通るか確認）
- [ ] `improv_serial`でのWiFiプロビジョニングを実施し、手順をここに追記
- [ ] HAでESPHomeデバイスが自動検出されるか確認
- [ ] `Status LED`エンティティのON/OFF操作を確認
- [ ] `remote_receiver`の`dump: raw`でシリアルログにIR受信の生タイミングが出るか確認

## オープンな issue / 気になっていること

（随時追記）
