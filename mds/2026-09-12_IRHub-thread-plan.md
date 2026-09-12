# IRHub Thread(802.15.4)対応 実装プラン

前提となる調査は [`2026-09-12_IRHub-thread-investigation.md`](./2026-09-12_IRHub-thread-investigation.md) を参照(ESPHomeの`openthread:`コンポーネント調査、既存コンポーネントとの依存関係チェック、Matter経由での参加案の比較検討、TLV取得方法)。
本ドキュメントはそれを踏まえた**Thread版ノードの実装プラン**。WiFi版の初期実装プランは [`2026-09-10_IRHub-plan.md`](./2026-09-10_IRHub-plan.md) 参照(こちらは無改造で維持する)。

## 0. 前提・ゴール

- 既存のWiFi版IRHubノード(`irhub-node-c5.yaml`/`irhub-node-c6.yaml`)には一切手を入れない。Thread版は**完全に別バイナリ**として追加する(ESPHomeの`openthread:`が`CONFLICTS_WITH = ["wifi"]`のため同一ファームウェアに同居できない)。
- ゴールは「IR受信・送信・ステータスLED・I2Cセンサー・HA連携(学習/送信API)は無改造のまま、ネットワーク層だけをWiFiからThreadに差し替えて動かす」こと。
- Matter経由での参加(QRオンボーディング)は検討の上不採用(investigation.md参照)。ESPHomeを完全に手放すコストが見合わないため。

## 1. アーキテクチャ

### ファイル分割

```
esphome/
  irhub-common.yaml           # ネットワーク非依存の共通設定(IR/LED/I2C/api/ota等)
  irhub-network-wifi.yaml      # wifi: + improv_serial:
  irhub-network-thread.yaml    # network: + openthread:
  irhub-node-c5.yaml           # WiFi版(common + network-wifi)
  irhub-node-c6.yaml           # WiFi版
  irhub-node-c5-thread.yaml    # Thread版(common + network-thread)
  irhub-node-c6-thread.yaml    # Thread版
```

`irhub-common.yaml`からネットワーク層(`wifi:`/`improv_serial:`)を分離し、各ノードYAMLの`packages:`でWiFi用/Thread用のどちらか一方をincludeする。IR受信・送信・ステータスLED・I2Cセンサー(ADT7410)・`api: services:`まわりのロジックはWiFi版と完全に共有し、無改造で流用する。

### データフロー

WiFi版([`2026-09-10_IRHub-plan.md`](./2026-09-10_IRHub-plan.md)参照)と**ネットワーク層以外は完全に同一**。`api:`/`ota:`/`mdns:`はESPHome内部で`network:`という抽象コンポーネントにしか依存していないため、HA側から見た挙動(ESPHome統合による自動検出、`esphome.<slug>_send_raw`サービス呼び出し等)はそのまま変わらない想定(投資先はSRP + OTBRのAdvertising Proxyによるmdns橋渡し。investigation.md参照)。

### ネットワーク認証情報のプロビジョニング戦略

| フェーズ | 方式 | 状態 |
| --- | --- | --- |
| A(現在) | Operational Dataset TLVを`secrets.yaml`にコンパイル時埋め込み(`tlv:`)。HAのThreadタブからコピペで取得 | 実装済み |
| B(将来) | UART経由でのランタイムprovisioning(「Thread版improv_serial」)。再ビルド不要で鍵をローテーションできる | 検討済み・未実装。詳細は[`2026-09-12_IRHub-thread-impl-notes.md`](./2026-09-12_IRHub-thread-impl-notes.md)の検討結果参照 |

フェーズAの制約(鍵を変えるたびに再ビルド・再書き込みが要る)は許容した上でまず進める。フェーズBは実際に複数台運用したり鍵ローテーションの必要が出てから着手する。

## 2. 実装フェーズ

### Phase T0: ビルド基盤の分離(完了)
- `irhub-common.yaml`からネットワーク層を分離。
- `irhub-node-c5-thread.yaml`/`irhub-node-c6-thread.yaml`を新設。
- `bin/build.sh`/`flash.sh`/`monitor.sh`に`c5-thread`/`c6-thread`を追加。
- C5/C6 × WiFi/Threadの4パターン全てで`esphome config`・実ビルド成功を確認。

### Phase T1: 実機書き込み・疎通確認(進行中)
- `secrets.yaml`のダミーTLVを実際のOperational Dataset TLVに置き換える。
- `bin/build.sh c5-thread` → `bin/flash.sh c5-thread` → `bin/monitor.sh c5-thread`で書き込み・起動確認。
- 起動ログでThreadネットワークへの参加(`Activating dataset...`以降のログ、`role`がchild/router等に変化するか)を確認。
- HAのESPHome統合が自動検出するか確認(mDNS経由、WiFi版と同じ体験になる想定)。

### Phase T2: IR学習・送信のThread経由動作確認
- WiFi版と同じ手順(`remote.learn_command`/`remote.send_command`)でEnd-to-Endの動作を確認。
- 体感レイテンシをWiFi版と比較(Thread特有の遅延要因はThread調査ドキュメントの補足Q&A参照)。
- `web_server:`(デバッグUI)がThread経由でどの程度使い物になるか確認(帯域が細いため)。

### Phase T3(将来・スコープ外)
- 「Thread版improv_serial」の実装(UART経由でOpenThreadの`otDatasetSetActiveTlvs()`を呼ぶカスタム`external_component`)。
- 複数Thread IRHubノードの運用(鍵ローテーション時の運用フロー整備)。
- バッテリー駆動の付加センサー(MTD、スリープ運用)の追加検討。

## 3. 未検証・要確認事項

- SRP + OTBR Advertising Proxyによるアドバタイズが、実機でも本当にHAのmDNS自動検出に引っかかるか(設計上そうなるはずだが実機未検証)。
- IR学習・送信の往復レイテンシがWiFi版と比べてどう変わるか。
- `network: min_ipv6_addr_count`等、`network:`コンポーネントのThread向けデフォルトで調整が要る項目があるか。
- ダミーTLVではなく実際のOperational Dataset TLVでの動作(現状ビルド検証はダミー値でのコンパイル成功のみ)。

これらはPhase T1〜T2で実機を使いながら潰していく想定。
