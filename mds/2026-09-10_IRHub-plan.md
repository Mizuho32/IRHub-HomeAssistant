# IRHub 初期実装プラン（ESPHome + HA custom integration）

前提となる調査は [`2026-09-10_IRHub.md`](./2026-09-10_IRHub.md) を参照（ESPHome route採用の経緯、`remote`エンティティの実装方法、`external_components`/Thread/Matterの話）。
本ドキュメントはそれを踏まえた**初回プロトタイプの実装プラン**。

## 0. 前提・ゴール

- ハードウェアは「適当に繋ぐ」想定: IR受信モジュール1つ、IR LED(送信)1つ、ステータスLED1つをESP32の適当なGPIOへ接続。
- ゴールは「HA UI(`remote.learn_command`)からIRHubノードに向かって任意のリモコンを学習でき、学習データはHA側(`.storage/`)に保存され、`remote.send_command`で再生できる」を1台構成でEnd-to-Endで動かすこと。
- センサ追加・Thread対応は将来フェーズ（このプランのスコープ外）。

### アーキテクチャ選定（要点だけ再掲）

- 2026年時点でHA coreに追加された新しい `Infrared` プラットフォーム（`ir_rf_proxy`連携）は"機種別統合が既知コードを送受信するための土台"であり、"任意の信号を対話的に学習して保存する"汎用フローはまだ持っていない。かつ`ir_rf_proxy`自体がEXPERIMENTAL指定。
- そのため本プランのMVPでは、**ESPHomeの枯れた既存機能（`remote_receiver` / `remote_transmitter` / `api: services:` / `homeassistant.event:`）だけを使い、HA〜ESP32間のブリッジを自前で作る**方式を採用する。`ir_rf_proxy`／新Infraredプラットフォームへの乗り換えは、それらが安定してからの将来検討事項とする。
- ESP32チップは **ESP32-C5** を前提とする（[実装ノート](./2026-09-10_IRHub-impl-notes.md)参照。当初「C5は802.15.4を持たずThread不可」としていたが誤りで、C5はWiFi6デュアルバンド＋BLE＋802.15.4(Zigbee3.0/Thread1.4)を搭載しておりThread対応可能）。ビルドフレームワークは `esp-idf` 固定（OpenThreadはArduinoコアでは使えないため）。
- WiFi認証情報はファームウェアのバイナリに焼き込まない。`improv_serial`（USBシリアル経由のImprov標準プロビジョニング）を使い、資格情報はデバイス上のNVS(flashパーティション)へ実行時保存する。これによりWiFi変更のたびの再ビルドが不要になる（詳細は実装ノート参照）。

## 1. ディレクトリ構成

```
IRHub/
  mds/                         # 調査・設計ドキュメント
  modules/esp32-matter-light/  # 参考実装として保持（今回は直接使わない）
  esphome/                     # ★ ESP側の作業ディレクトリ
    irhub-node.yaml
    secrets.yaml.example
    secrets.yaml               # 各自作成、.gitignore対象
  ha/                           # ★ HA側の作業ディレクトリ
    custom_components/
      irhub/
        __init__.py
        manifest.json
        const.py
        config_flow.py
        remote.py
```

- `esphome/` はESPHome CLIの作業ディレクトリとしてそのまま使う想定（`esphome run irhub-node.yaml`等）。
- `ha/custom_components/irhub/` は、実機のHA configディレクトリの `custom_components/irhub` にシンボリックリンクするかコピーして使う（HACS配布物と同じ形）。

各ファイルの初期スケルトンは作成済み（後述、要調整・要検証）。

## 2. データフロー概要

```
[リモコン] --IR--> [IR受信モジュール]--(GPIO)--> [ESP32: remote_receiver]
                                                        |
                                                        | on_raw トリガ
                                                        v
                                          homeassistant.event:
                                          event: esphome.<slug>_ir_raw_received
                                          event_data.raw = "9000,-4500,560,..."
                                                        |
                                                        v (HAのイベントバス)
                                     custom_components/irhub (remote.async_learn_command)
                                                        |
                                                        v
                                        .storage/irhub_codes_<slug>  (学習データ永続化)


[HA UI: remote.send_command] --> custom_components/irhub
                                    | .storageから生タイミングを引く
                                    v
                           service call: esphome.<slug>_send_raw(data=[...])
                                    |
                                    v
                        [ESP32: api:services: send_raw -> remote_transmitter.transmit_raw]
                                    |
                                    v
                        [IR LED] --IR--> [家電]
```

ポイント:
- **ESP32側は完全にステートレス**（Wi-Fi/APIの認証情報以外は何も持たない）。学習データは全てHAの`.storage/`に保存される（当初要件どおり）。
- プロトコルデコード（NEC/AEHA等）は行わず、**生のタイミング配列(raw)をそのまま学習・送信**する。汎用性重視・実装コスト最小化のため（デコード対応は将来の最適化枠）。

## 3. 実装フェーズ

### Phase 0: ESPHome土台の疎通確認
- `esphome/irhub-node.yaml` をベースに実機ピン番号を確定し、`esphome run` で書き込み。
- 初回書き込み後、`improv_serial`でUSBシリアル経由のWiFiプロビジョニングを実施（SSID/パスワードはNVSに実行時保存、バイナリには含まれない）。
- WiFi接続・HAでのESPHomeデバイス自動検出・`Status LED`エンティティのON/OFF操作を確認。
- `remote_receiver`の`dump: raw`で、シリアルログにIR受信の生タイミングが出ることを確認（適当なリモコンを受光させる）。

### Phase 1: IR送信の疎通確認
- ESPHomeの`Developer Tools`等から`esphome.<slug>_send_raw`サービスを直接呼び、Phase 0でログに出た生タイミング配列を手入力して投げてみる。
- IR LEDの発光をスマホカメラ等で確認し、対象家電（学習元のリモコンと同じ製品）が反応するか確認。
- ここまでで「HA→ESP32への生データ送信」「ESP32でのIR送信」の経路が動くことを検証（`custom_components/irhub`はまだ関与しない）。

### Phase 2: `on_raw` → `homeassistant.event` の疎通確認
- `esphome/irhub-node.yaml`の`on_raw`ブロックを有効化し、HAの`開発者ツール > イベント`で`esphome.<slug>_ir_raw_received`をリッスンして、リモコン受光のたびにイベントが飛んでくることを確認。
- `event_data.raw`がカンマ区切り文字列として期待通り出るか確認（ESPHomeの`homeassistant.event:`の`event_data`値のテンプレート仕様に依存するため、ここは実機での検証が必要）。

### Phase 3: `custom_components/irhub` を有効化
- `ha/custom_components/irhub`をHAの`custom_components/`へ配置、HA再起動。
- 設定 > 統合 からIRHubを追加、`device_slug`（ESPHome YAMLの`name`）を入力してconfig entryを作成 → `remote.irhub_<slug>`エンティティが生成されることを確認。
- `remote.learn_command`（`entity_id: remote.irhub_<slug>`, `command: "tv_power"`等）を呼び、タイムアウト以内にリモコンを送信 → `.storage/irhub_codes_<slug>`に保存されることを確認。
- `remote.send_command`で同じ`command`を送り、家電が反応するか確認（Phase 1で確認した経路をEnd-to-Endで再現）。

### Phase 4: 動作確認・簡易自動化
- ダッシュボードに`remote`エンティティのカードを置き、UIから学習・送信ができることを確認。
- 簡単な自動化例（例: 特定時刻に照明ONのIRコードを送る）を1つ組んで実運用に近い形で通しで確認。

### Phase 5（将来・本プランのスコープ外）
- `ir_rf_proxy`／HA core `Infrared`プラットフォームが成熟したら、自前ブリッジからの移行を検討。
- モーション・照度センサの追加（ESPHomeの`binary_sensor`/`sensor`をYAML追記するだけで対応できる見込み、[`2026-09-10_IRHub.md`](./2026-09-10_IRHub.md) Q1参照）。
- Thread対応（`openthread:`コンポーネント導入、HA側Thread/Matter連携の検討）。
- IRプロトコルデコード対応（生データだけでなくNEC等の意味づけをして可読性向上）。
- `config_flow`の改善（ESPHome統合済みデバイスからの自動サジェスト等）、複数ノード対応の整理。

## 4. 未検証・要確認事項（実機着手前に潰す）

- `api: services:` の`int[]`引数と`remote_transmitter.transmit_raw`の`code:`が期待通りの型で繋がるか（コンパイルが通るか）。
- `homeassistant.event:`の`event_data`配下でlambdaが返す`std::string`が、HA側イベントの`event.data["raw"]`として素直に文字列で届くか。
- IR受信モジュールの極性（`inverted: true`が正しいか）、動作電圧・プルアップ要否。
- `remote_receiver`の`on_raw`が想定より高頻度で発火しないか（1回のボタン押下で複数回イベントが飛ぶ可能性、要デバウンス検討）。
- 学習データサイズの上限（生タイミング配列が長いリモコン、例えばエアコンのフルステート送信タイプへの対応可否）。
- `improv_serial`によるプロビジョニング手順そのもの（実機未実施）。

これらはPhase 0〜2で実機を使いながら潰していく想定。

## 5. 作成済みスケルトン

- `esphome/irhub-node.yaml`, `esphome/secrets.yaml.example`, `esphome/.gitignore`
- `ha/custom_components/irhub/{manifest.json, const.py, __init__.py, config_flow.py, remote.py}`, `ha/custom_components/irhub/.gitignore`

いずれもコンパイル・動作未検証の初期スケルトン。Phase 0から順に実機で通しながら調整していく。
