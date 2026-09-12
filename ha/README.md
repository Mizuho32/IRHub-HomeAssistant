# IRHub と Home Assistant の接続手順

前提: ESPHomeノード(`esphome/irhub-node-c5.yaml` 等)は書き込み済み・WiFi接続済みで、
`bin/monitor.sh`のログに `[I][remote.raw:035]: Received Raw: ...` のような
IR受信ログが出ている状態(=IR受信自体は動いている)。

`[W][api:442]: Home Assistant event '...' dropped; no client connected` という
警告が出るのは、**まだHA側で何も設定していないので当然**。以下の手順で
2つのものをHAに追加すると解消する。

## 全体像

```
[ESP32: ESPHomeノード] <--(1)HAが自動検出して接続--- [HA: ESPHome統合(標準)]
        |                                                    |
        | (2') カスタムAPIサービス送信                        | (2) カスタム統合を配置
        |      esphome.<slug>_send_raw                        v
        `----------------------------------------- [HA: custom_components/irhub]
                                                          (remote.irhub_<slug> エンティティ)
```

- ESP32はHAのIPアドレスを一切知らなくてよい。**HAがmDNSでESP32を見つけて接続しにいく**
  (逆方向)。ESPHomeは`api:`を設定すると自動的にmDNS(`_esphomelib._tcp`)で
  自分自身を広告するので、ESP32側で何か設定する必要はない。
- 一度HA→ESP32の接続(TCP)が確立すれば、そのコネクション上でイベント通知
  (ESP32→HA)とサービス呼び出し(HA→ESP32)が双方向にやり取りされる。

## 手順

### 1. ESPHome統合を追加する(標準機能、まずこれが必須)

1. HAの `設定 > デバイスとサービス` を開く。
   - 同じネットワーク内にいれば、自動検出のカードに `irhub-node-c5` のような
     名前のESPHomeデバイスが出ているはず。「設定」を押すだけでOK。
   - 出てこない場合は `+ 統合を追加` → `ESPHome` を選び、IPアドレスを手入力する
     (ESP32のIPは `bin/monitor.sh` のログ、またはルーターのDHCPクライアント
     一覧、あるいは `esphome/secrets.yaml` のある端末から
     `ping irhub-node-c5.local` などで調べられる)。
   - 暗号化キーを聞かれたら `esphome/secrets.yaml` の `api_encryption_key` を入力。
2. 追加できると、そのESP32が単体のデバイスとしてHAに登録される
   (Status LightなどYAMLで定義したエンティティが見える)。
   同時に `esphome.<device>_send_raw` サービスが呼べるようになる
   (`開発者ツール > アクション` で `esphome.` と打つと候補に出てくるはずなので、
   ここで一度確認しておくとよい)。

### 2. IRHubカスタム統合を配置する

このリポジトリの `ha/custom_components/irhub/` を、HAの設定ディレクトリ
(`configuration.yaml` と同じ階層)の `custom_components/irhub/` に配置する。

- HA OS/Supervised (Samba/SSHアドオン等でファイルアクセスしている場合):
  `ha/custom_components/irhub` フォルダごと `config/custom_components/irhub` に
  コピーする。
- HA Core/Container を自前運用していて、このリポジトリと同じマシン上にいる場合:
  シンボリックリンクで運用すると以降の更新が楽:
  ```sh
  ln -s /path/to/IRHub/ha/custom_components/irhub \
        /path/to/homeassistant/config/custom_components/irhub
  ```
- 配置後、**HAを再起動**する(custom_componentsの読み込みは起動時のみ)。

### 3. IRHub統合をHAに追加する

1. `設定 > デバイスとサービス > + 統合を追加` で `IRHub` を検索。
2. `device_slug` を聞かれるので、ESPHomeのYAML上の名前をそのまま入れる
   (例: `irhub-node-c5`。`esphome/irhub-node-c5.yaml` の
   `substitutions: name:` の値)。
3. 追加できると `remote.irhub_irhub-node-c5` のような`remote`エンティティが
   1つ作られる。

### 4. 学習・送信をテストする

`開発者ツール > アクション` から:

- **学習**: アクション `remote.learn_command` を選び、
  `entity_id: remote.irhub_irhub-node-c5`, `command: ["tv_power"]` のように
  指定して実行。10秒以内(デフォルトタイムアウト)にリモコンのボタンを
  ESP32のIR受信モジュールに向けて押す。
  → 成功すると `.storage/irhub_codes_irhub-node-c5` にコードが保存される。
- **送信**: アクション `remote.send_command` で同じ `entity_id` と
  `command: ["tv_power"]` を指定して実行。IR LEDが光り、家電が反応するか確認。

## トラブルシューティング

- `Home Assistant event '...' dropped; no client connected` が出続ける
  → 上記手順1(ESPHome統合の追加)がまだ。これが無いとHA側にAPI接続自体が
  無いので、ESP32がイベントを送ろうとしても宛先がない。
- `remote.send_command` を呼んでも反応がない
  → `esphome.<slug>_send_raw` サービスが本当にその名前で存在するか
  `開発者ツール > アクション` で確認する。ESP32のデバイス名にハイフンが
  含まれる場合、HA側はサービス名生成時にハイフンをアンダースコアに
  変換する(例: `irhub-node-c5` → `esphome.irhub_node_c5_send_raw`)。
  `custom_components/irhub/remote.py` はこれを考慮済みだが、実際の
  サービス名とズレていたらそちらが正。
- `remote.learn_command` がタイムアウトする
  → `bin/monitor.sh` で `[I][remote.raw:035]: Received Raw: ...` が
  出ているか確認(出ていればESP32側の受信は正常、HA側イベント配送の
  問題を疑う)。出ていなければIR受信モジュールの配線/向きを確認。

## 既知の制約(現状のスケルトンでの前提)

- 生タイミング配列(raw)をそのまま学習・送信する(プロトコルデコードはしない)。
- 1 config entry = 1 ESPHomeノード(remoteエンティティ1個)。複数ノードを
  使う場合はIRHub統合をノードの数だけ追加する。
- 詳しい設計は [`../mds/2026-09-10_IRHub-plan.md`](../mds/2026-09-10_IRHub-plan.md) を参照。
