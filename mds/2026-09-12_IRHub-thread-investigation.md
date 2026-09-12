# IRHubのThread(802.15.4)化 検討

## 背景・問い

[`Projects/Network/Thread/2_encount_thread.md`](/home/mizuho/media/nas/Documents/obsidian/Projects/Network/Thread/2_encount_thread.md)(Obsidian)で、
LANにULA+OTBRを構築し、LANのPCから既存Threadスマートホーム機器のIPv6アドレスへ
`ping -6`が素で通ることを確認済み。NAT無しでOMR prefix経由のネイティブ
IPv6ルーティングが効いていること、名前解決はOpenThreadのSRP(Service
Registration Protocol) + OTBRのAdvertising Proxyが自動的にLAN側mDNSへ
橋渡ししてくれる、という理解まで到達している。

これを踏まえての問い: **「IPレイヤの話なら、名前解決さえできればWiFiの
ときと同じようにIRHub(ESPHome)ノードをThread化して使えるのでは?」**

## 結論(先に)

**技術的には十分現実的。** ESPHome(インストール済み2026.8.2)には既に
`openthread:`という正式コンポーネントが存在し、ESP32-C5/C6/H2系で
サポートされている。しかも中身を見ると、ちょうどObsidianメモで
結論づけた「SRP + OTBRのAdvertising Proxy → mDNS橋渡し」という仕組みを
**ESPHome自身がすでに内部で実装済み**で、`api:`/`ota:`/`mdns:`のような
既存コンポーネントは「WiFiかThreadか」を意識しない作りになっている
(`network:`という抽象コンポーネント経由でしか依存していない)。

つまり「IRHub用のIR送受信・HA連携ロジックはそのまま」で、**ネットワーク
まわりの設定ブロックだけ`wifi:`+`improv_serial:`から`openthread:`に
差し替える**、という形の変更で成立する見込みが高い。ただしトレードオフも
あるので後述する。

## ESPHomeの`openthread:`コンポーネント調査

`esphome/.venv/lib/python3.14/site-packages/esphome/components/openthread/`
を読んだ内容。

### 対応チップ・フレームワーク

```python
def _validate_platform(config):
    ...
    return only_on_variant(
        supported=[VARIANT_ESP32C5, VARIANT_ESP32C6, VARIANT_ESP32H2,
                   VARIANT_ESP32H4, VARIANT_ESP32H21, VARIANT_ESP32S31]
    )(config)
```

- **C5/C6ともにサポート対象**(既にIRHubが使っているチップそのまま。
  ハードウェア変更は不要。802.15.4は内蔵RFなので配線変更も無し)。
- `esp32: framework: type: esp-idf` が必須(Arduinoコア非対応)。
  → これは`irhub-node-c5.yaml`/`c6.yaml`に**既に設定済み**
  (「将来Thread対応する前提でesp-idfに固定しておく」というコメントを
  最初期から入れていた。伏線回収)。

### WiFiとは同時に使えない

```python
CONFLICTS_WITH = ["wifi"]
# Wi-fi / Bluetooth / Thread coexistence isn't implemented at this time
# TODO: Doesn't conflict with wifi if you're using another ESP as an RCP
# (radio coprocessor), but this isn't implemented yet
```

- ESPHomeの設定バリデーションレベルで**`wifi:`と`openthread:`は排他**。
  1つのビルドでどちらか一方を選ぶ必要があり、実行時切り替えや両対応は
  できない(将来的に別チップをRCPにする方式なら共存できる余地はある、
  とコメントされているが未実装)。
- 実務上の意味: **「WiFi版とThread版は別のYAML(別バイナリ)」**になる。
  今の`irhub-node-c5.yaml`/`c6.yaml`を直接書き換えるのではなく、
  `irhub-node-c5-thread.yaml`のような第3の派生ファイルを作る形が妥当。

### 認証情報(Operational Dataset)の与え方

```python
_CONNECTION_SCHEMA = cv.Schema({
    cv.Optional(CONF_PAN_ID): cv.hex_int,
    cv.Optional(CONF_CHANNEL): cv.int_range(min=11, max=26),
    cv.Optional(CONF_NETWORK_KEY): cv.hex_int,
    cv.Optional(CONF_EXT_PAN_ID): cv.hex_int,
    cv.Optional(CONF_NETWORK_NAME): cv.string_strict,
    cv.Optional(CONF_PSKC): cv.hex_int,
    cv.Optional(CONF_MESH_LOCAL_PREFIX): cv.ipv6network,
})
...
cv.has_exactly_one_key(CONF_NETWORK_KEY, CONF_TLV)
```

- 個別パラメータ(`network_key`/`pan_id`/`channel`/`ext_pan_id`/
  `network_name`/`pskc`)を書くか、まとめて`tlv:`(Operational Dataset全体を
  hexダンプした1本の文字列)で渡すかの二択。`tlv:`の方が楽で、
  OTBR側から
  ```sh
  docker exec -it addon_core_openthread_border_router ot-ctl dataset active -x
  ```
  を実行すればそのままコピペできるhex文字列が得られる(既存Threadネットワークに
  参加させたいだけなら、実質これ一発で済む)。
- **Joiner/コミッショニング(実機のボタン押下等でその場でネットワーク参加させる
  標準的なThreadオンボーディング)のサポートはESPHomeに無い**。つまり
  認証情報は`secrets.yaml`経由とはいえ**コンパイル時にバイナリへ焼き込む**
  ことになる。WiFiで`improv_serial`をわざわざ採用してまで避けた
  「資格情報をバイナリに焼き込まない」方針を、Threadでは(現状の
  ESPHomeでは)維持できない。ネットワーク鍵を変えたい場合は再ビルド・
  再書き込みが要る(初回参加後はOTA(WiFi版で使っているものと同じ
  `ota: platform: esphome`)が使えるはずなので、2回目以降の更新は
  無線越しにできる可能性は高い)。

### FTD/MTD、スリープ

```python
CONF_DEVICE_TYPES = ["FTD", "MTD"]
...
if device_type == "FTD" and poll_period and poll_period > 0:
    raise cv.Invalid(f"{CONF_POLL_PERIOD} can only be used with {CONF_DEVICE_TYPE}: MTD")
```

- IRHubノードはUSB給電で常時起動・常時IR受信待ちなので、素直に
  **FTD(Full Thread Device、非スリープ・メッシュルーター能力あり)**
  一択。`poll_period`(スリープ端末のポーリング間隔)はMTD専用なので関係ない。
  Obsidianメモで観測した「バッテリー駆動デバイスがSED(スリーピーエンド
  デバイス)として数秒単位で遅延する」という挙動は、IRHubには当てはまらない
  ということになる。

### SRP + mDNS橋渡しの実装

```python
enable_mdns_storage()
...
srp = cg.new_Pvariable(config[CONF_SRP_ID])
mdns_component = await cg.get_variable(config[CONF_MDNS_ID])
cg.add(srp.set_mdns(mdns_component))
```

```python
add_idf_sdkconfig_option("CONFIG_OPENTHREAD_SRP_CLIENT", True)
add_idf_sdkconfig_option("CONFIG_OPENTHREAD_DNS64_CLIENT", True)
```

- `openthread:`は既存の`mdns:`コンポーネントが持っているサービス定義
  (`_esphomelib._tcp`等、`api:`/`ota:`が自動登録するもの)を**そのまま
  流用**し、LAN上への生mDNSマルチキャストの代わりにOpenThreadの
  **SRP Client**でOTBR(=SRPサーバー)へ登録する`OpenThreadSrpComponent`を
  自前実装済み。OTBRのAdvertising ProxyがこれをLAN側の通常のmDNSレコードに
  変換してくれる、というObsidianメモで結論づけた仕組みそのもの。
- つまり**HA側のESPHome統合による自動検出(mDNS)は、WiFi版と同じ体験の
  ままThread版でも動く見込みが高い**(実機未検証だが、設計上そうなる
  ように作られている)。
- `use_address`のデフォルトは`${name}.local`で、これはWiFi版で今使っている
  `ota:`/`api:`のホスト名解決と全く同じ規約。Thread版に変えても
  「`irhub-node-c5.local`にアクセスする」という運用は変わらない想定。

### `network: enable_ipv6: true`が必須

```python
def _final_validate(_):
    ...
    if not network_config.get(CONF_ENABLE_IPV6, False):
        raise cv.Invalid(
            "OpenThread requires IPv6 to be enabled in the network component. "
            "Please set `enable_ipv6: true` in the `network` configuration."
        )
```

- `network:`ブロックに`enable_ipv6: true`を明示する必要がある
  (WiFi版では今まで意識していなかった設定)。

## 既存コンポーネントとの依存関係チェック

「WiFi前提で書かれていて詰む」箇所が無いか、主要コンポーネントの
`DEPENDENCIES`/`CONFLICTS_WITH`を実際に読んで確認した。

| コンポーネント | 依存 | Thread化への影響 |
| --- | --- | --- |
| `api:` | `network`のみ | 影響なし。変更不要 |
| `mdns:` | `network`のみ(ESP32/IDFでは`wifi`/`ethernet`必須チェックはESP8266/RP2040限定) | 影響なし |
| `ota: platform: esphome` | (コード内にwifi依存箇所なし) | 影響なし |
| `web_server:` | `json`, `web_server_base`(下位も`network`ベース) | 動くが、Threadメッシュの帯域はWiFiよりかなり細いのでUIの反応は遅くなる可能性(デバッグ用途としては許容範囲と思われる) |
| `improv_serial:` | **`DEPENDENCIES = ["logger", "wifi"]`** | **ハード依存でThread版では使用不可**。WiFi資格情報のプロビジョニング専用機能なので、Wi-Fiを使わないThread版ではそもそも用途が無くなる(前述の通りThreadの鍵は別途コンパイル時に埋め込む形になる) |

このため、`irhub-common.yaml`の中で書き換えが要るのは実質
「`wifi:`+`improv_serial:`のブロックを`network:`+`openthread:`に
差し替える」部分だけで、IR受信・送信・ステータスLED・I2Cセンサー・
`api: services:`まわりのロジックは無改造で流用できる見込み。

## トレードオフまとめ

**得られるもの**
- LANから素のIPv6でIRHubノードに到達可能(Obsidianメモで実証済みの
  経路をそのまま利用)。NAT/ポートフォワード的な設定は一切不要。
- HA側のESPHome統合による自動検出・接続は理屈上WiFi版と同じ体験
  (SRP→mDNS橋渡しによる)。
- 2.4GHz WiFi帯域の輻輳を避けられる、複数の低消費電力Threadデバイスとの
  将来的な相互運用性(直接メッシュ内の他デバイスとやり取りする、なども
  将来的には視野に入る)。

**失う/増えるコスト**
- **WiFiとの共存不可**(ESPHome側の制約)。WiFi版とThread版は別ビルド
  ・別バイナリになる。
- **improv_serialによる無再ビルドWiFiプロビジョニングの恩恵が無くなる**。
  Thread側は鍵をコンパイル時に埋め込む前提(Joiner機能はESPHome未対応)。
  ネットワーク鍵のローテーション運用をするなら都度再ビルド・再書き込みが要る。
- Web UI(`web_server:`)がThreadメッシュ越しだと体感的に重くなる可能性。
- 実機検証はまだ無いので、実際のIR受信レイテンシ・API呼び出しの
  往復時間がWiFiと比べてどう変わるか(Obsidianメモで見た「数百ms〜数秒」の
  ばらつきの影響)は要実測。IRの学習・送信自体はHA↔ESP32間のAPI呼び出し
  1〜2往復で完結するので、多少の遅延があっても実用上は問題にならない
  可能性が高いが未検証。

## 所感: IRHub自体にThread化の実利はあるか

IRHubノードはUSB給電の常時稼働・据え置き機器なので、正直なところ
**WiFiのままでも困っていない**。Thread化の恩恵(省電力・メッシュでの
到達性)は本来、バッテリー駆動のセンサー類(人感・開閉・今回のADT7410の
ような温度センサーを電池駆動にする場合等)でこそ効いてくる話。

なので優先順位としては:

1. IRHub本体(常時給電・据え置き)は**当面WiFiのままで良い**。
2. Thread化は「ESPHomeのopenthread:が実用になるか」の**検証機会**として、
   IRHubノードの設定を流用した**別ビルド(第3のYAML)**を試すのが
   ローリスクで良さそう(今のWiFi版ノードは無傷のまま並行して残せる)。
3. 本命は将来追加するかもしれない**バッテリー駆動の付加センサー**を
   Thread(MTD、スリープ運用)で作る場合の予行演習、という位置づけ。

## 実装状況(2026-09-12)

上記の方針で実装済み。詳細は
[`2026-09-10_IRHub-impl-notes.md`](./2026-09-10_IRHub-impl-notes.md)の
「Thread版ノード実装(実験)」セクション参照。要点:

- `irhub-common.yaml`からネットワーク層を分離し、`irhub-network-wifi.yaml`/
  `irhub-network-thread.yaml`のどちらかを各ノードYAMLがincludeする構成にした。
- `irhub-node-c5-thread.yaml`/`irhub-node-c6-thread.yaml`を新設。
- 4パターン(C5/C6 × WiFi/Thread)全て`esphome config`・実ビルド成功。
- **未実施**: 実機書き込み、HAでのmDNS自動検出確認、IR学習・送信の
  Thread経由での実動作確認、WiFi版とのレイテンシ比較。

## 次のステップ(提案)

1. Operational Dataset TLVを取得。以下のどちらでも同じ値が手に入る:
   - **HAのUIだけで完結する方法(推奨)**: `設定 > システム > ネットワーク >
     Thread`タブに該当ネットワークの詳細を開くと`Active dataset TLVs: ...`
     という項目にそのまま表示されている。SSH/docker/Proxmoxコンソール一切不要。
   - CLI経由(HAのSSHアドオンからやる場合、デフォルトのProtection mode
     ONだとDockerソケットが見えないので**Protection modeをOFFにする**必要
     がある。上級者モード有効化 → アドオン詳細でトグルOFF → 再起動):
     ```sh
     docker exec -it addon_core_openthread_border_router ot-ctl dataset active -x
     ```
2. `esphome/secrets.yaml`に`thread_dataset_tlv`のようなキーで保存
   (バイナリには焼き込まれるが、リポジトリにはコミットしない今まで通りの
   運用)。ESPHome側は`tlv:`を使う場合、`network_key`/`pan_id`等の個別
   パラメータとは排他(`cv.has_exactly_one_key`)なので混在させないこと。
3. `esphome/irhub-node-c5-thread.yaml`(仮)を新設し、`irhub-common.yaml`は
   共有しつつ`wifi:`/`improv_serial:`ブロックだけ`network: enable_ipv6:
   true` + `openthread: tlv: !secret thread_dataset_tlv` に差し替えた
   派生設定を作る(具体的な分割方法は実装時に要検討。共通部分から
   wifi/improv_serialを抜いて`irhub-common-network-wifi.yaml`と
   `irhub-common-network-thread.yaml`のように分離するのが素直そう)。
4. ビルド・書き込み後、HAのESPHome統合が自動検出するか、
   `irhub-node-c5-thread.local`で疎通するかを実機確認。
5. 問題なければ、IR学習・送信の往復レイテンシをWiFi版と比較。

## 補足: Matter経由での参加は検討したか

「スマートホーム機器みたいにQRでHAに追加、の流儀でThreadに参加してから
好きにできないか」という案も検討した(過去に`SleepBtn`
(`/home/mizuho/media/nas/prjs/HomeAssistant/SleepBtn/`)でMatter over Thread
デバイスを実際に動かした実績があるため、現実的な選択肢として比較)。

- QRスキャン/手入力によるオンボーディングは、ほぼ全てMatterのコミッショニング
  プロトコル(BLE PASEハンドシェイク)そのもの。`SleepBtn`もこれを使っており、
  QR画像の代わりに固定manual pairing code(`20202021`/discriminator`3840`)
  を使う運用だった。
- Matterとして参加すればThread自体には(内部がOpenThreadなので)普通に
  繋がるが、**コミッショニングを完了させるには必須クラスタ一式を備えた
  「まともなMatterデバイス」である必要があり、「鍵だけもらって中身は無視」
  はできない**。しかもMatterの標準デバイスタイプにIRブラスター/汎用リモコン
  に相当するものが無く、`SleepBtn`自身も「Generic Switchは合わないので
  On/Off Plug-in Unitで代用」という妥協をしている。
- Matterルートを取ると**ESPHomeを完全に手放す**ことになる(ESPHomeに
  Matterサポートは無く、`esp_matter`/connectedhomeipは生ESP-IDF C++の別物で
  共存不可)。IR受信・送信・LED・I2Cセンサー・OTA・学習/送信APIを全部
  手書きC++で再実装し、HA側もMatter統合では拾えないので新たに
  `custom_components`相当を書く必要が出る。
- 結論: 得られるのは「初回オンボーディングがQR/コード入力で済む」という
  一度きりの利便性、失うのは「ESPHomeの宣言的な楽さ全部」という恒常的な
  コスト。IRHubは配布物ではなく自分用DIY機器なので、
  **`openthread:`に`tlv:`(HAのThread画面からコピペで取得可能、後述)を
  渡す方式で進める**ことにした。QRオンボーディングが本当に欲しくなるのは
  「他人に配る/複数台を頻繁に入れ替える」ような別プロジェクトの場合。
