# IRHub Thread(802.15.4)対応 実装ノート(あれこれ)

[`2026-09-12_IRHub-thread-investigation.md`](./2026-09-12_IRHub-thread-investigation.md)(調査)・[`2026-09-12_IRHub-thread-plan.md`](./2026-09-12_IRHub-thread-plan.md)(実装プラン)を前提に、Thread対応の実装を進める中での決定事項・修正・issueをここに随時追記していく。WiFi版本体の実装ログは[`2026-09-10_IRHub-impl-notes.md`](./2026-09-10_IRHub-impl-notes.md)参照(こちらは無改造で維持、Thread関連の記述はこちらに集約)。

## 決定事項・修正ログ

### 2026-09-12: ネットワーク層の分離 + Thread版ノード追加

- `irhub-common.yaml`から`wifi:`/`improv_serial:`を分離し、
  `irhub-network-wifi.yaml`(既存のWiFi+improv_serial)と
  `irhub-network-thread.yaml`(新規、`network: enable_ipv6: true` +
  `openthread: device_type: FTD, tlv: !secret thread_dataset_tlv`)の
  2ファイルに分割。各ノードYAMLの`packages:`でどちらか一方をincludeする形にした
  (ESPHome側の`CONFLICTS_WITH = ["wifi"]`制約により、WiFiとThreadは同一
  バイナリに共存できないため)。
- `irhub-node-c5-thread.yaml`/`irhub-node-c6-thread.yaml`を新設。ピン配置は
  対応するWiFi版と同一(IR/LED/I2Cの配線は変えていない、ネットワーク層のみ差し替え)。
  `name:`はWiFi版と衝突しないよう`irhub-node-c5-thread`のように別名にした。
- Thread認証情報(Operational Dataset)はimprov_serial相当の実行時プロビジョニング
  手段が無いため、`secrets.yaml`の`thread_dataset_tlv`にコンパイル時埋め込み。
  値はHAの`設定 > システム > ネットワーク > Thread`タブに出ている
  `Active dataset TLVs: ...`をそのままコピーするだけで取得できた
  (SSH/docker exec/Proxmoxコンソール一切不要だった)。
- `bin/build.sh`/`flash.sh`/`monitor.sh`のチップ種別バリデーションに
  `c5-thread`/`c6-thread`を追加。
- C5/C6のWiFi版・Thread版、計4パターン全て`esphome config`のバリデーションと
  実ビルド(`bin/build.sh`)に成功(secrets.yamlはダミーTLV値。実機書き込み・
  Thread実接続の確認はまだ)。
- 検討の結果**やらなかったこと**: 「Matterとして振る舞ってQRでThread参加
  してから自由に使う」案(過去の`SleepBtn`プロジェクトでMatter over Thread
  の実績あり)。ESPHomeを完全に手放すことになり、IR送受信・OTA・HA連携を
  全部手書きC++で再実装するコストが見合わないと判断し不採用
  (詳細はinvestigation.mdの補足セクション参照)。

### 2026-09-12: 鍵のUARTアップロード方式の検討(結論: 保留)

`/home/mizuho/media/nas/prjs/HomeAssistant/Wireless_USBHID/bin/upload_wifi_credentials.py`
(別プロジェクト、WiFi資格情報を自前の`wifi_cred`パーティションへUART経由で
アップロードするツール)を参考に、「Threadの鍵(Operational Dataset)も同様に
再ビルド無しでUART経由アップロードできないか」を検討した。

**わかったこと**:

- `esphome/components/openthread/openthread_esp.cpp`の実際のコードを確認したところ、
  ```cpp
  #ifndef USE_OPENTHREAD_FORCE_DATASET
    otError error = otDatasetGetActiveTlvs(instance, &dataset);
    if (error != OT_ERROR_NONE) {
      dataset.mLength = 0;  // fallback to config
    } else {
      ESP_LOGI(TAG, "Found existing dataset, ignoring config (force_dataset: true to override)");
    }
  #endif
  ```
  という実装になっており、**YAMLの`tlv:`はあくまで初回起動時のブートストラップ用
  フォールバックに過ぎない**。一度でも有効なデータセットがNVSに永続化されて
  いれば、以後の起動ではコンパイル済みの値は無視されそちらが優先される。
  WiFi版の`improv_serial`(コンパイル時デフォルト→実行時上書きされたデータが
  以後優先)と全く同じ構造。
- つまり**「再ビルド無しで鍵を差し替える」こと自体はESPHome/OpenThreadの
  設計上はじめから可能**で、足りないのは「実行時に新しいデータセットを
  流し込むツール(Thread版improv_serial に相当するもの)」がESPHomeに
  存在しないという点だけ。プロトコル・ハードウェア面の制約ではない。

**`Wireless_USBHID`と同じ手法(生パーティション書き込み)がそのまま
使えない理由**:

- `Wireless_USBHID`の方式は、**自分で定義した専用パーティション**
  (`wifi_cred`)に対して、ブートローダーモード中に`parttool.py`
  (esptool経由)で生バイトを直接書き込む。自分が完全に所有するフォーマット
  なので安全。
- 一方OpenThreadのデータセットは**標準の`nvs`パーティション**(ESP-IDFの
  NVS key-valueバイナリ形式)に、WiFiの資格情報や`preferences:`の状態など
  他のESPHomeサブシステムの値と**同居**して保存される。ここに生バイトを
  直接書き込む方式は、(1) 正しいNVSバイナリ形式(ページ構造・チェックサム)
  で書かないと壊れる、(2) OpenThread内部が使うnamespace/key名は公開APIでは
  ない実装詳細でバージョン間の安定性が無い、という2点でリスクが大きい。

**筋の良い代替案(将来実装するならこちら)**:

- OpenThreadの公開C API `otDatasetSetActiveTlvs()` を呼べば、正しいNVS
  永続化はOpenThread自身が面倒を見てくれる(「生バイトを直接書く」のでは
  なく「ちゃんと公開APIにお願いする」方式)。
- これをESPHomeの`external_component`として実装すれば
  (`external_components/adt7410/`と同じ要領)、UART経由で新しい
  データセットを流し込める「Thread版improv_serial」が作れる見込み。
  UARTのフレーミングプロトコルの実装と、OpenThreadインスタンスへの
  アクセス(`esp_openthread_get_instance()`等、`esp_openthread.h`の
  公開API)が必要になる、そこそこの新規C++実装。

**結論**: 技術的には現実的だが、今すぐ必要な機能ではない(まずは
`secrets.yaml`への直接埋め込みで動作確認を優先する)ため、実装は
[`2026-09-12_IRHub-thread-plan.md`](./2026-09-12_IRHub-thread-plan.md)の
Phase T3(将来対応)に位置づけて保留。複数台運用や鍵ローテーションの
必要が実際に出てから着手する。

### 2026-09-12: 実機確認結果(mDNS自動検出・消費電力・OTA速度)

- **mDNS自動検出**: 設定変更・再登録一切無しでHAから即座に認識され、
  リモコン操作も動作。SRP + OTBRのAdvertising Proxyによる橋渡しが
  設計通り機能した(investigation.md参照)。IPアドレスが変わっても
  再登録が要らない理由: HAのESPHome統合は接続識別にMACアドレス由来の
  `unique_id`を使い、接続先自体もIPではなく`<name>.local`という
  ホスト名で管理している。名前解決さえ通ればアドレスの変化は透過的に
  吸収される(WiFi版のDHCPアドレス変化と同じ理屈)。
- **消費電力**: WiFi版0.12W → Thread版(FTD)0.33Wと約2.7倍に増加。
  原因はFTDが仕様上スリープしない(常時RX)ため。`device_type: MTD` +
  `poll_period: 1s`に変更して再検証中(`irhub-network-thread.yaml`)。
  トレードオフとしてHA→ESP32方向の通信に最大poll_period分の遅延が
  乗る(SEDと同じ理屈)。
- **OTA速度が激遅(実測)**: WiFi版のOTAが3.6秒に対し、Thread版は147秒
  (約41倍)。OTA対象バイナリ(`irhub-node-c5-thread.bin`、OTA用)は
  883,840バイトなので、実効スループットは
  `883,840 byte × 8 bit / 147s ≈ 48kbps`。
  当初「OTBRのRCP-UART速度(460800bps)で律速されているのでは」という
  仮説が出たが、457800bpsはおろか115200bpsのUARTでも48kbpsより
  十分速いため、**UARTは律速点ではない**と判断。真因は802.15.4の
  生PHYレート自体が250kbpsしか無く(WiFiの数十〜数百Mbpsと3〜4桁違う)、
  さらに6LoWPANフラグメンテーション(IPv6パケットが802.15.4の最大フレーム長
  127byteを超えるため必須)+CSMA/CAバックオフ+ACK待ち+ESPHome OTA自体の
  チャンク毎応答待ちプロトコルのオーバーヘッドが重なった結果と考えられる
  (250kbps理論値に対し実効効率約19%は、この手のオーバーヘッドを踏まえると
  典型的な数字)。ZigbeeやThreadのOTA更新が総じて遅いことの一般的な理由と
  合致しており、異常ではない。
  - 実用上の指針: 物理アクセスできる場合はUSBシリアルで焼く。Thread OTAは
    「物理アクセスできない時の非常手段」という位置づけが妥当。

### 2026-09-12: MTD化の効果測定 + 最終結論

`device_type: MTD` + `poll_period: 1s`で再実測。

- **消費電力**: 0.33W(FTD) → **0.22W**(MTD 1s)。下がったが、まだ
  WiFi版(0.12W)の**約1.8倍**。
- **レイテンシ**: 体感で明らかに増加(HA→ESP32方向の応答が遅くなった)。

**なぜMTDにしてもWiFiに届かないのか**:

- **ポーリング頻度は下がったが、1回あたりのコストがWiFiより重い**。
  WiFiのDTIMベースのモデムスリープは「短時間だけ起きてビーコン確認→また
  寝る」という長年ハードウェア支援込みで練り込まれた仕組みで、ウェイク
  時間もごく短い(数〜数十ms)。一方Thread MTDのPoll(データポーリング)は、
  送信前にCSMA/CAのランダムバックオフを挟む必要があり、応答待ちの往復も
  あるので、1秒に1回とはいえその1回が相対的に長く/重い。
- **poll_periodと無関係な定期処理が別途走っている**。OpenThreadは親への
  Child Update(生存確認)やSRPの登録更新など、ポーリング間隔とは別軸の
  タイマーで動く処理を複数持っている。ここはFTD/MTDに関わらず一定の負荷
  として乗る。poll_periodをいくら伸ばしてもこの分は減らないので、
  どこかで消費電力は下げ止まると予想される。
- **このチップ自体が「WiFiが主、802.15.4は後乗せ」という設計**なので、
  CPU側のライトスリープとの協調度合いもWiFiの方が最適化されていて
  不思議はない。

`poll_period`を伸ばすほど電力は下がるがレイテンシとのトレードオフが
キツくなり、上記の「ポーリング非依存の定期処理」分は減らないため
下げ止まりがあるはず、という前提で`poll_period: 5s`での追加検証に移行。

**結果**: `poll_period: 5s`でも**0.22W(1sと同値)**。ポーリング間隔を
5倍に伸ばしても消費電力は全く変わらなかった。これは「Child Update/SRP
登録更新などpoll_period非依存の定期処理がフロアを形成している」という
仮説を裏付ける結果で、**このノードの消費電力はもはやpoll_periodでは
下げられない**(=ポーリング自体のコストではなく、OpenThreadスタックの
常時稼働コストの方が支配的)ことが実測で確定した。

**結論**: WiFi 0.12W / Thread FTD 0.33W / Thread MTD(1s) 0.22W、OTA速度
41倍遅い(前セクション参照)、レイテンシも増加、`improv_serial`相当の
恩恵も無し…と並べると、**IRHubのような常時USB給電の据え置き機器には
WiFiの方が総合的に優れている**という結論になった。investigation.mdの
「所感」セクションで事前に立てていた予想(Thread化の実利はバッテリー
駆動デバイス向け)が実測で裏付けられた形。**Thread版は技術検証として
完了とし、IRHub本番運用はWiFi版を継続する**。

### 2026-09-12: WiFi版に戻したらsend_commandが失敗した(HA側の運用メモ)

同じ物理ボードをThread版(`irhub-node-c5-thread`)からWiFi版(`irhub-node-c5`)に
焼き直した後、`remote.send_command`が
`Not connected to irhub-node-c5-thread`で失敗する事象が発生。

- entity_id(`remote.irhub_irhub_node_c5`)・`input_text.irhub_target_entity`
  ともに正しく新しい方(WiFi版)を指していることを確認済みだったにも
  関わらず発生 → `custom_components/irhub`側のロジックの問題ではなかった。
- ESPHome統合はMACアドレスで同一物理デバイスと認識するため、`name:`が
  変わっても同じ設定エントリのまま繋ぎ直しにいくが、
  `esphome.irhub_node_c5_thread_send_raw`という**古いサービス登録だけが
  内部にキャッシュされたまま残っていた**(`開発者ツール > アクション`で
  古い名前のサービスがまだ候補に出ることで確認)。
- **統合のreloadでは直らず、HA Coreの完全な再起動で解消した**。
- `ha/README.md`のトラブルシューティングにも追記済み。同じ物理ボードで
  `name:`(=ESPHomeデバイス名)を変える運用(WiFi⇄Thread切り替え含む)を
  する場合は、再書き込み後に一度HAを完全再起動する運用にしておくと安全。

## 動作確認チェックリスト

- [x] C5/C6 × WiFi/Thread 4パターンの`esphome config`バリデーション
- [x] C5/C6 × WiFi/Thread 4パターンの実ビルド(`bin/build.sh`、ダミーTLV)
- [x] 実際のOperational Dataset TLVでの実機書き込み・起動確認(C5)
- [x] HAのESPHome統合による自動検出(mDNS/SRP経由。設定変更・再登録不要で即認識)
- [x] IR学習・送信のThread経由End-to-End動作確認(リモコン操作成功)
- [x] 消費電力の実測比較(WiFi 0.12W → Thread FTD 0.33W。原因はFTDの非スリープ仕様)
- [x] OTA速度の実測比較(WiFi 3.6秒 → Thread 147秒。802.15.4の帯域制約が原因)
- [x] MTD + poll_period化での消費電力・レイテンシ再検証(1s/5sとも0.22Wで下げ止まり、まだWiFiの1.8倍。レイテンシは増加)
- [ ] 「Thread版improv_serial」(UARTでの鍵アップロード)の実装(優先度低、複数台運用の必要が出たら着手)

## オープンなissue/今後の検討事項

- 上記チェックリストの未完了項目一式。
- `web_server:`(デバッグUI)がThreadメッシュ越しでどの程度実用的か(帯域が
  WiFiよりかなり細いため)。
- バッテリー駆動の付加センサー(MTD、スリープ運用)をThreadで追加する場合の
  設計(investigation.mdの所感セクション参照。IRHub本体よりもこちら向けに
  Thread化の旨みがある)。
