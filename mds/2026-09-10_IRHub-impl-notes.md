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

### 2026-09-13頃: HA側UI改善 + マルチフレームリモコン対応

- **ダッシュボードUI改善**: `ha/dashboard-example.yaml`にDeveloper Tools不要の軽量UI(input_text + script + template select)を追加。経緯:
  - `remote.py`に`commands`属性(学習済みコマンド名一覧)を追加。
  - 対象デバイス・対象コマンドをハードコードせずドロップダウンから選べるように(`select.irhub_target_device`は`integration_entities('irhub')`、`select.irhub_known_command`は選択中デバイスの`commands`属性を選択肢にしたtemplate select)。将来IRHubノードを追加してもダッシュボード編集不要。
  - `irhub.delete_command`/`irhub.rename_command`をentity serviceとして追加(標準`remote`ドメインには無い機能)。
  - ハマりポイント: `input_text`/`script`はYAMLキーがそのままentity_idになるが、`template: select:`は`name:`からslugifyでentity_idを自動生成する。日本語名だとローマ字化が壊れて`対象デバイス`→`dui_xiang_tehaisu`のような文字列になり、ダッシュボードが参照するIDと不一致になった。`name:`を英語にして回避(既存分は手動でentity_idをリネームして解消)。
- **バグ⑤: マルチフレームリモコン(Daikin等)が正しく学習できない**。DAIKIN F28YTESのエアコンリモコンで発覚。1回のボタン押下で「短い前置きバースト＋長い本体フレーム×2」の**計3回**`on_raw`イベントが発火していた(各フレーム間のギャップが`remote_receiver`の`idle:`判定(既定10ms)より長く、ESPHomeが別々の信号として分割していた)。旧実装は最初の1フレーム(=一番短い前置きバーストのみ、11pulse程度)だけを学習・保存しており、本体の状態データを含む後続フレームを捨てていたため、送信しても家電が反応しなかった。
  - 対処: `remote.py`にマルチフレーム対応を実装。学習は`_collect_raw_frames`で最初のフレーム受信後、`FRAME_GATHER_WINDOW`(既定0.5秒)以内に届く後続フレームを`asyncio.Queue`で拾い続け、`list[str]`として保存するように変更(単一フレームのリモコンは要素数1のリストになるだけ)。送信は保存されたフレームを順番に(`FRAME_SEND_GAP`=0.03秒間隔で)送信。
  - 後方互換: 旧フォーマット(単一フレームの生文字列)がstorageに残っていても`_as_frames()`で`[str]`に正規化して送信できるようにしてある。

### 2026-09-12: I2C拡張基盤 + ADT7410温度センサ

- ADT7410(Analog Devices)を繋いで温度を取りたいとの要望。**注意**: ADT7410は温度専用ICで湿度は測れない(当初「湿度センサ機能も」という話が出たが、依頼者確認の上「温度センサの間違い」で決着)。
- ADT7410はESPHome標準コンポーネントに存在しない(2026.8.2確認)。`esphome/external_components/adt7410/`に自前実装(`sensor.py`+`adt7410.h/.cpp`、既存の`htu21d`/`bh1750`コンポーネントを参考に、`sensor::Sensor`を直接継承する単一値センサーのパターンで作成)。16bit解像度モード(Configレジスタ`0x03`にbit7=1を書き込み)に固定し、温度レジスタ`0x00`の16bit符号付き値を128で割って℃に変換。
- **I2C拡張基盤**: `irhub-common.yaml`に`i2c:`(SDA/SCLは`i2c_sda_pin`/`i2c_scl_pin`のsubstitutions、`scan: true`で起動時に接続デバイスのアドレス一覧をログ出力)を追加。IR/LED用ピンと同様、実際のピン番号はチップ別ファイル(`irhub-node-c5.yaml`: GPIO2/GPIO3、`irhub-node-c6.yaml`: GPIO19/GPIO20、いずれも非ストラッピングかつ既存ピンと非衝突)で上書き。XIAOのシルク印刷ピン番号(Dx)との対応は未確認なので実配線前に要確認、とコメントしてある。
- **拡張性の設計**: I2Cは1本のバス(2ピン)にアドレスが被らない限り何個でもデバイスを追加できるので、今後センサーを増やす場合は`irhub-common.yaml`の`sensor:`リストに項目を足すだけでよい。SPIデバイスを足したい場合はCLK/MOSI/MISOは共有できるがデバイスごとにCS(チップセレクト)ピンが1本ずつ必要、という制約もコメントで明記した。
- C5/C6両方で`esphome config`(バリデーション)・`bin/build.sh`(実ビルド)を実行し、コンパイル成功を確認済み。**実機確認済み**: `bin/monitor.sh`のログで`Temperature=26.99°C`のような妥当な値が60秒おきに出ることを確認(HA側にもESPHome統合経由でそのまま`sensor.`エンティティとして自動的に見える。IRHubの`custom_components`はremoteドメインのみ扱うので無関係)。
- **訂正: GPIO7(C5, status_led_pin/D3)はストラッピングピンでも実害なし**。ESP32-C5データシート上はストラッピングピン扱いだが、XIAOボード側のピン説明ではD3に特別な役割は無く、実機でも問題なく動作した。過去のC6での再起動ループはストラッピングピン競合が真因と考えていたが、実際は電源不足(USBハブ経由給電のブラウンアウト)が真因だった可能性が高い(いずれにせよ直接USB給電に変えて解消済み)。

### 2026-09-12: Thread版ノード対応(別ドキュメントへ分離)

WiFi版と別バイナリになるThread(802.15.4)対応の実装ログ・プランは
[`2026-09-12_IRHub-thread-plan.md`](./2026-09-12_IRHub-thread-plan.md)/
[`2026-09-12_IRHub-thread-impl-notes.md`](./2026-09-12_IRHub-thread-impl-notes.md)
に分離した(このファイルはWiFi版本体のログに専念する)。`irhub-common.yaml`
からネットワーク層(`wifi:`/`improv_serial:`)を`irhub-network-wifi.yaml`に
切り出した点だけはWiFi版にも影響するので触れておく:内容は変えていない
(ロジック上は無変更、ファイル分割のみ)。

### 2026-09-13: BME280(温湿度気圧)追加、複数センサ共存の確認

- BME280はESPHome標準コンポーネント(`platform: bme280_i2c`、デフォルト
  アドレス0x77)なので、ADT7410と違い自前実装不要。`irhub-common.yaml`の
  `sensor:`にそのまま追記するだけで済んだ(拡張性の設計通り機能)。
- ADT7410(0x48)とBME280(0x76/0x77)はアドレスが元々被らないので、同じ
  I2Cバスにそのまま共存できる。実際に両方を`sensor:`に併記して
  `esphome config`/実ビルド成功を確認済み(実機接続はまだ)。
- **複数の気温センサーがHAにどう見えるか**: ESPHomeでは`sensor:`配下の
  各エントリ(sub-sensor含む)がそれぞれ独立したHAエンティティとして
  公開されるので、ADT7410とBME280を両方繋げば
  `sensor.irhub_..._adt7410_temperature`と
  `sensor.irhub_..._bme280_temperature`のように**別々のエンティティとして
  両方見える**(名前が同じだと紛らわしいので、ADT7410側の`name:`も
  「Temperature」から「ADT7410 Temperature」に変更し、BME280側は
  「BME280 Temperature」/「BME280 Humidity」/「BME280 Pressure」とした)。

## ディレクトリ/ファイル現況

```
esphome/
  irhub-common.yaml        # 共通設定(API/IR受信送信/ステータスLED/I2C+センサ等。ネットワーク層は含まない)
  irhub-network-wifi.yaml   # wifi:+improv_serial:(デフォルト)
  irhub-network-thread.yaml # network:+openthread:(実験版)
  irhub-node-c5.yaml        # C5向けWiFi版エントリポイント(board/framework + ピン上書き)
  irhub-node-c6.yaml        # C6向けWiFi版エントリポイント
  irhub-node-c5-thread.yaml # C5向けThread版エントリポイント(実験)
  irhub-node-c6-thread.yaml # C6向けThread版エントリポイント(実験)
  external_components/adt7410/  # ADT7410温度センサの自前コンポーネント
  secrets.yaml.example      # api_encryption_key, thread_dataset_tlv(Thread版のみ必要)
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
- [x] ADT7410温度センサの実機接続・実測値確認
- [ ] BME280(温湿度気圧)の実機接続・実測値確認(コンパイル確認のみ済み)

## オープンな issue / 今後の検討事項

- センサ類(人感・照度)の追加は未着手（[プラン](./2026-09-10_IRHub-plan.md) Phase 5参照）。I2C拡張基盤自体はADT7410対応時に整備済みなので、`irhub-common.yaml`の`sensor:`に追記していく形で足せる。
- Thread対応は着手済み(別ドキュメント)。[`2026-09-12_IRHub-thread-plan.md`](./2026-09-12_IRHub-thread-plan.md)/[`2026-09-12_IRHub-thread-impl-notes.md`](./2026-09-12_IRHub-thread-impl-notes.md)参照。
- IRプロトコルデコード(NEC等)は未対応、生タイミングのみ扱う設計のまま。
- `num_repeats`/`delay_secs`/`hold_secs`など`remote.send_command`の付加オプションは
  現状`custom_components/irhub`側で未対応(無視される)。必要になったら
  `remote.py`の`async_send_command`で実装する。
