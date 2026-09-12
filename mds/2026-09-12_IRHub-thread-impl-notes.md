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

## 動作確認チェックリスト

- [x] C5/C6 × WiFi/Thread 4パターンの`esphome config`バリデーション
- [x] C5/C6 × WiFi/Thread 4パターンの実ビルド(`bin/build.sh`、ダミーTLV)
- [ ] 実際のOperational Dataset TLVでの実機書き込み・起動確認
- [ ] Threadネットワークへの参加確認(起動ログでrole変化を確認)
- [ ] HAのESPHome統合による自動検出(mDNS/SRP経由)
- [ ] IR学習・送信のThread経由End-to-End動作確認
- [ ] WiFi版とのレイテンシ比較
- [ ] 「Thread版improv_serial」(UARTでの鍵アップロード)の実装

## オープンなissue/今後の検討事項

- 上記チェックリストの未完了項目一式。
- `web_server:`(デバッグUI)がThreadメッシュ越しでどの程度実用的か(帯域が
  WiFiよりかなり細いため)。
- バッテリー駆動の付加センサー(MTD、スリープ運用)をThreadで追加する場合の
  設計(investigation.mdの所感セクション参照。IRHub本体よりもこちら向けに
  Thread化の旨みがある)。
