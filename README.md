# IRHub

ESP32 (XIAO ESP32-C5/C6) を使った赤外線リモコン学習ハブ。ESPHome + Home
Assistantカスタム統合で構成し、学習データはESP32上ではなくHA側の
`.storage/`に保存する。

## ディレクトリ構成

```
mds/          調査・設計ドキュメント
esphome/      ESP32側(ESPHome YAML)。ビルド/書き込みもここで行う
ha/           HA側(custom_components/irhub)。HAとの接続手順は ha/README.md 参照
bin/          ビルド・書き込み・モニタ・WiFi設定用スクリプト
```

## セットアップの流れ

1. **ESPHomeノードのビルド・書き込み**
   ```sh
   bin/build.sh c5          # または c6。コンパイルのみ
   bin/flash.sh c5           # ビルド済みバイナリを書き込むだけ(pure flash)
   bin/monitor.sh c5         # シリアルログ監視(切断時は自動再接続)
   ```
   初回は `esphome/secrets.yaml.example` を `esphome/secrets.yaml` にコピーして
   `api_encryption_key` を設定しておくこと。

2. **WiFi設定 (Improv Serial)**
   ```sh
   bin/wifi_setup.sh --ssid "MyWiFi" --password "xxxxx"
   # または対話入力: bin/wifi_setup.sh
   # 状態確認だけ: bin/wifi_setup.sh --info
   ```
   WiFi資格情報はファームウェアのバイナリに焼き込まず、デバイス上のNVSに
   実行時保存される(詳細は `esphome/irhub-common.yaml` 冒頭のコメント参照)。

3. **Home Assistantとの接続**
   → [`ha/README.md`](ha/README.md) を参照。ESPHome統合の追加、
   `custom_components/irhub`の配置、学習・送信のテスト手順を記載。

## センサ拡張(I2C/SPI)

`esphome/irhub-common.yaml`に`i2c:`バスを用意済みで、ADT7410(高精度温度センサ、
`esphome/external_components/adt7410/`に自前実装、ESPHome標準未収録のため)を
実装例として繋いである。I2Cはアドレスさえ被らなければ1本のバスに何個でも
デバイスを追加できるので、他のI2Cセンサを足す場合は`irhub-common.yaml`の
`sensor:`リストに項目を追記するだけでよい。SPIデバイスを足す場合はCLK/MOSI/MISOは
共有できるが、デバイスごとにCS(チップセレクト)ピンが1本ずつ追加で必要になる。

## bin/ スクリプト一覧

| スクリプト | 内容 |
| --- | --- |
| `bin/esphome.sh` | ESPHome CLIラッパー。venv自動構築＋システムのESP-IDF(`/opt/esp-idf5.5.1`)を使う |
| `bin/build.sh <c5\|c6\|c5-thread\|c6-thread>` | コンパイルのみ |
| `bin/flash.sh <c5\|c6\|c5-thread\|c6-thread> [device]` | 書き込みのみ(pure flash、ビルドしない) |
| `bin/monitor.sh <c5\|c6\|c5-thread\|c6-thread> [device]` | シリアルログ監視。切断時に自動再接続、`esphome/monitor-<chip>.log`にも保存 |
| `bin/erase.sh [device]` | フラッシュ全消去(brownout等でのフラッシュ破損疑い時) |
| `bin/wifi_setup.sh` | Improv Serial経由でWiFi資格情報を送信(WiFi版ノードのみ) |

## Thread版ノード(実験)

`-thread`サフィックス付きのYAML(`irhub-node-c5-thread.yaml`等)はWiFiの代わりに
Thread(802.15.4)でHAに接続する実験版。WiFi版とはESPHome側の制約で同一
バイナリに共存できないため別ファイルになっている。使う場合は
`esphome/secrets.yaml`に`thread_dataset_tlv`(HAの`設定 > システム >
ネットワーク > Thread`タブに出ている`Active dataset TLVs: ...`をコピー)を
設定してからビルドする。詳細・調査経緯は
[`mds/2026-09-12_IRHub-thread-investigation.md`](mds/2026-09-12_IRHub-thread-investigation.md)参照。

## トラブルシューティング

- **リセットすると再起動を繰り返す/クラッシュする**: まず給電を疑う
  (USBハブ経由をやめてPC直結にする、ケーブルを変える)。ブラウンアウト
  検出でのリセットはWiFi起動時の電流スパイクに給電が耐えられないと起きる。
  フラッシュが壊れた疑いがあれば `bin/erase.sh` → `bin/build.sh` →
  `bin/flash.sh` でクリーンに焼き直す。
- センサーを追加する前に [`mds/2026-09-13_IRHub-esphome-tips.md`](mds/2026-09-13_IRHub-esphome-tips.md)
  (ESPHome/HA連携のハマりどころ集)に目を通しておくと事故が減る
  (特に「エンティティの`name:`を変えるとHA側で履歴が切れる」件)。
- その他の詳細な調査経緯・設計判断は [`mds/`](mds/) 以下のドキュメント
  ([`2026-09-10_IRHub.md`](mds/2026-09-10_IRHub.md)、
  [`2026-09-10_IRHub-plan.md`](mds/2026-09-10_IRHub-plan.md)、
  [`2026-09-10_IRHub-impl-notes.md`](mds/2026-09-10_IRHub-impl-notes.md))を参照。
