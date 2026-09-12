# IRHub 実装ノート（あれこれ）

[`2026-09-10_IRHub.md`](./2026-09-10_IRHub.md)（初期調査）・[`2026-09-10_IRHub-plan.md`](./2026-09-10_IRHub-plan.md)（初期実装プラン）を前提に、実装を進める中での決定事項・修正・issue・TODOをここに随時追記していく。

## 決定事項・修正ログ

### 2026-09-10

- **ESP32チップをC6からC5に変更**。プランドキュメント初版では「C5は802.15.4無線を持たずThread化できない」としていたが誤り。実際にはESP32-C5は2.4/5GHzデュアルバンドWiFi6 + BLE5 + 802.15.4（Zigbee 3.0 / Thread 1.3〜1.4）を搭載しており、Thread対応可能。ユーザーが実機として[Switch Science扱いのESP32-C5HR8ボード](https://www.switch-science.com/products/10978)を保有しているため、これを前提に進める。最終的には**XIAO ESP32-C5/C6の両対応**にした（後述）。
- **WiFi資格情報をバイナリに焼き込まない方針に変更**。`improv_serial`（USBシリアル経由のImprov標準プロビジョニング）を採用。資格情報はコンパイル済みバイナリではなく、デバイス上のNVSに実行時保存される。`secrets.yaml`には`api_encryption_key`のみ残す。

### 2026-09-11〜12: 実機デバッグ一式

- **ビルド環境**: システムに既存の`/opt/esp-idf5.5.1`をそのまま`IDF_PATH`として使う方式にし、ESPHomeによる独自ダウンロードを回避（`bin/esphome.sh`参照）。ローカルで`bin/build.sh c5`/`c6`が実際にビルド成功することを確認済み。
- **XIAO ESP32-C5/C6両対応化**: `esphome/irhub-node.yaml`を`irhub-common.yaml`（共通設定）＋`irhub-node-c5.yaml`/`irhub-node-c6.yaml`（ボード別）に分割。board idはそれぞれ`seeed_xiao_esp32c5`/`seeed_xiao_esp32c6`。
- **バグ①: `homeassistant.event:`のペイロードキー誤り**。`event_data:`ではなく`data:`が正しい(`esphome config`で発覚)。
- **バグ②: ステータスLEDのプラットフォーム誤り**。`light: platform: monochromatic`はFloatOutput必須で、単純なGPIO ON/OFF出力とは合わない。`platform: binary`に修正。
- **ハードウェア: ストラッピングピン問題によるリセット後の再起動ループ**。仮ピン`GPIO4/5/8`がXIAO ESP32-**C6**のストラッピングピン（GPIO4,5,8,9,15、ブートモード決定に関与）と丸被りしていた。C5は別セット（GPIO7,25,26,27,28,MTMS,MTDI）。チップ別にXIAOの安全なD-pinへ変更:
  - C6: `ir_receiver=GPIO0(D0)`, `ir_transmitter=GPIO1(D1)`, `status_led=GPIO2(D2)`
  - C5: `ir_receiver=GPIO1(D0)`, `ir_transmitter=GPIO0(D1)`, `status_led=GPIO23(D4)`
- **デバッグ用ツール整備**: `bin/monitor.sh`（当初`esphome logs`ベースだったが、ポート切断時に再接続しない/外側ループでも毎回CLIプロセスを起動し直し遅すぎたため、プロセス起動なしで高速リトライする`bin/raw_monitor.py`(pyserial直叩き)に置き換え）、`bin/erase.sh`（フラッシュ全消去）、`bin/wifi_setup.sh`+`bin/improv_wifi.py`（Improv Serialプロトコルを自前実装したCLI、ブラウザのWeb Serial不要）。
- **根本原因: 電源不足によるブラウンアウト再起動ループ**。`bin/raw_monitor.py`で捕まえたログから、WiFiスキャン開始直後に毎回クラッシュ→`E BOD: Brownout detector was triggered`（ブラウンアウト検出）→さらにフラッシュ書き込み中の電源断で**アプリパーティション/NVSが破損**し`Guru Meditation Error (Load access fault)`が起動直後に発生する二次被害、という流れだった。原因は**USBハブ経由の給電不足**（WiFi送受信時の電流スパイクに耐えられなかった）。PC直結USBに変更、`bin/erase.sh`でフラッシュ全消去してから焼き直しで解消。
- **Status LED状態の揮発**: 2つの原因が重なっていた。
  1. `light:`の`restore_mode`がデフォルト`ALWAYS_OFF`だった→`RESTORE_DEFAULT_OFF`に変更。
  2. ESPHomeの`preferences:`（flashへの状態保存）はデフォルト60秒間隔のバッチ書き込みで、トグル直後にハードリセット(RST=EN直落とし)すると未フラッシュの変更が消える→`preferences: flash_write_interval: 0s`（即時書き込み）に変更。書き込み頻度が低い用途なのでflash摩耗リスクは無視できる。
- **バグ③: IR送信にキャリア周波数(38kHz)を指定しておらず復調されない**。`remote_transmitter.transmit_raw`の`carrier_frequency`はデフォルト0Hz(=無変調のON/OFF)。`remote_receiver`は受信時に既に復調済みの包絡線だけを記録しているので、送信時に改めて38kHzで変調し直す必要があった。`carrier_frequency: 38kHz`を追加して解消。
- **バグ④: HA側のサービス名生成でハイフン考慮漏れ**。`custom_components/irhub/remote.py`が`esphome.<device_slug>_send_raw`を呼ぶ際、HA側は`esphome`統合のサービス名生成でデバイス名のハイフンをアンダースコアに変換する（例: `irhub-node-c5` → `esphome.irhub_node_c5_send_raw`）。`device_slug.replace('-', '_')`で対応。
- **切り分けの過程で判明**: ESP32-C5/C6はRMT実装(`remote_transmitter_rmt.cpp`)が使われるため、C3/S3以前で使われるビットバン実装(`remote_transmitter.cpp`)にある`ESP_LOGD(TAG, "Sending remote code")`が出ない。これは仕様であり異常ではない。
- **✅ End-to-Endで動作確認完了**: HA UIから`remote.learn_command`で学習→`.storage/irhub_codes_irhub-node-c5`に保存→`remote.send_command`でIR送信→実機の家電(扇風機)の電源ON まで確認。

## ディレクトリ/ファイル現況

```
esphome/
  irhub-common.yaml        # 共通設定(WiFi/API/IR受信送信/ステータスLED等)
  irhub-node-c5.yaml        # C5向けエントリポイント(board/framework + ピン上書き)
  irhub-node-c6.yaml        # C6向けエントリポイント
  secrets.yaml.example      # api_encryption_keyのみ
  .gitignore
ha/custom_components/irhub/
  manifest.json / const.py / __init__.py / config_flow.py / remote.py
  .gitignore
ha/README.md                # HA接続手順(ESPHome統合追加→irhub配置→learn/sendテスト)
bin/
  esphome.sh   # venv自動構築 + システムのESP-IDFを使うCLIラッパー
  build.sh     # コンパイルのみ
  flash.sh     # 書き込みのみ(pure flash、ビルドしない)
  monitor.sh   # シリアルログ監視、自動再接続、ファイルにも保存
  raw_monitor.py # monitor.shの実体(pyserial直叩き、高速リトライ)
  erase.sh     # フラッシュ全消去
  wifi_setup.sh / improv_wifi.py # Improv Serial経由のWiFiプロビジョニングCLI
README.md      # プロジェクト全体のトップレベル案内
```

## 動作確認チェックリスト

- [x] ESP32-C5/C6実機ビルド成功(`bin/build.sh c5`/`c6`)
- [x] `improv_serial`でのWiFiプロビジョニング(`bin/wifi_setup.sh`)
- [x] HAでESPHomeデバイスの自動検出・接続
- [x] Status LEDエンティティのON/OFF操作・状態の永続化
- [x] `remote_receiver`でのIR受信(`Received Raw`ログ)
- [x] `remote.learn_command`での学習・`.storage`への保存
- [x] `remote.send_command`でのIR送信・実機家電のON確認

## オープンな issue / 今後の検討事項

- センサ類(人感・照度)の追加は未着手（[プラン](./2026-09-10_IRHub-plan.md) Phase 5参照）。
- Thread対応は未着手。
- IRプロトコルデコード(NEC等)は未対応、生タイミングのみ扱う設計のまま。
- `num_repeats`/`delay_secs`/`hold_secs`など`remote.send_command`の付加オプションは
  現状`custom_components/irhub`側で未対応(無視される)。必要になったら
  `remote.py`の`async_send_command`で実装する。
