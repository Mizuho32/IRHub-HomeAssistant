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

### 5. (任意) Developer Toolsを使わない軽量ダッシュボード

信号を追加するたびに開発者ツールを開くのが面倒な場合、
[`dashboard-example.yaml`](./dashboard-example.yaml) にテキスト入力欄＋
「学習する」「送信する」「リネームする」「削除する」ボタンだけの
最小ダッシュボード例を用意した。学習済みコマンド一覧は`remote`エンティティの
`commands`属性(`custom_components/irhub`が公開)をMarkdownカードで表示している。
ファイル内のコメントに沿って`configuration.yaml`とダッシュボードYAMLに
それぞれ該当部分を貼り付け、entity_idを実際の値に置き換えて使う。

削除・リネームは標準の`remote`ドメインには無い機能なので、
`custom_components/irhub`がカスタムサービス`irhub.delete_command` /
`irhub.rename_command`として追加している(`services.yaml`参照。
Developer Tools > アクションからも直接呼べる)。

対象デバイス(entity_id)はscriptにハードコードせず、`select.irhub_target_device`
というドロップダウンから選ぶ方式にしてある。選択肢はHAのJinja関数
`integration_entities('irhub')`でIRHub統合に属する全remoteエンティティを
自動列挙しているだけなので、**IRHubノードを複数追加してもダッシュボード・
スクリプト側は編集不要**(ドロップダウンに自動的に出てくる)。

同様に、送信・削除・リネーム対象のコマンド名も直接入力せず
`select.irhub_known_command`ドロップダウン(選択中デバイスの`commands`
属性が選択肢)から選べる。選ぶと「コマンド名」欄に自動で入る。
新規学習したい場合はこのドロップダウンは使わず、直接手入力する。

`input_text:`/`script:`部分は`configuration.yaml`に追記すればよいが、
`views:`以下(Lovelace)はHAのUIから貼り付ける必要がある。手順:

**新規ダッシュボードをYAMLモードで作る場合(推奨)**

1. `設定 > ダッシュボード` → `+ ダッシュボードを追加`
2. 「新規ダッシュボードを作成」→「一から始める」(名前は何でもよい、例: `IRHub`)
3. 作成したダッシュボードを開き、右上の `︙`(三点メニュー) → `ダッシュボードを編集`
4. 編集モードでもう一度 `︙` → **`YAMLで編集`**(Raw configuration editor)を選ぶ
5. エディタが開く(中身はほぼ空のはず)ので、`dashboard-example.yaml`の
   `views:`という行から最後までを丸ごと貼り付ける
6. 保存

これで「IRHub」というタブ(ビュー)ができ、入力欄＋学習/送信ボタン＋
学習済み一覧のMarkdownカードが表示される。

**既存のダッシュボードに追加したい場合**

同じ手順(該当ダッシュボードで`編集`→`YAMLで編集`)でよいが、その場合は
エディタに**今の全ビューがまとめて表示される**ので、上書きせず
`views:`リストの中に新しいビュー(`- title: IRHub ...`のブロック)を
追記する形にすること。

**YAMLを一切使いたくない場合(GUIのみ)**

1. `ダッシュボードを編集` → `+ カードを追加` → `エンティティ`カードを選択
2. `input_text.irhub_command_name`と2つのscriptエンティティ
   (`script.irhub_learn_command` / `script.irhub_send_command`)を追加
3. 別途`+ カードを追加` → `Markdown`カードを選択し、そのカードの
   `︙` → `YAMLで編集`で`content:`部分だけ貼り付ける

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
- 学習はできる(タイムアウトしない)のに送信しても家電が反応しない
  (特にエアコンのリモコン)
  → **マルチフレームリモコンの可能性が高い**。Daikin等のエアコンリモコンは
  1回のボタン押下で複数の赤外線バーストを、ESPHomeの`remote_receiver`の
  `idle:`判定(既定10ms)より長いギャップを挟んで送ってくることがある。
  `bin/monitor.sh`でボタンを1回押したときに`Received Raw:`が
  **複数回**出ていないか確認する。複数回出ているのにコードの以前のバージョン
  (最初の1フレームだけ学習する実装)で学習していた場合、短い先頭フレーム
  だけが保存されて本体の状態データが欠けている。現在の実装
  (`remote.py`の`_collect_raw_frames`)は短時間(既定0.5秒)以内に届いた
  複数フレームをまとめて1コマンドとして学習・送信するようになっているので、
  該当コマンドを一度削除して学習し直せば直る。
- 同じ物理ESP32に**別の`name:`で再書き込み**した(例:
  WiFi版`irhub-node-c5`⇄Thread版`irhub-node-c5-thread`を行き来した)後、
  `remote.send_command`が`Not connected to <古い方の名前>`で失敗する
  → ESPHome統合はMACアドレスで同一デバイスと認識して繋ぎ直しにいくが、
  `esphome.<旧slug>_send_raw`のような**古いサービス登録がキャッシュされた
  まま残ることがある**(entity_id・`input_text`等HA UI上の見た目は正しく
  新しい方を指していても、内部のサービス登録だけ古いままというケースを
  実際に確認した)。統合の再読み込み(reload)では直らず、**HA Coreの
  完全な再起動**で解消する。`開発者ツール > アクション`で`esphome`と
  検索し、古い名前のサービス(例: `esphome.irhub_node_c5_thread_send_raw`)
  がまだ候補に出てくるかで切り分けられる。

## 既知の制約(現状のスケルトンでの前提)

- 生タイミング配列(raw)をそのまま学習・送信する(プロトコルデコードはしない)。
- 1 config entry = 1 ESPHomeノード(remoteエンティティ1個)。複数ノードを
  使う場合はIRHub統合をノードの数だけ追加する。
- マルチフレームリモコン(Daikin等)は、フレーム間ギャップが
  `FRAME_GATHER_WINDOW`(既定0.5秒、`remote.py`)より長い機種だと
  正しく1コマンドにまとまらない可能性がある。その場合は定数を調整する。
- 詳しい設計は [`../mds/2026-09-10_IRHub-plan.md`](../mds/2026-09-10_IRHub-plan.md) を参照。
