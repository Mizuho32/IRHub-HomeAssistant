# センサー補正値をHAのUIから変更できるようにする案(保留)

ステータス: **保留**(2026-10-28)。どの案も固有の面倒さがあるため、今は
yamlの`filters:`に直書き + 再ビルド/OTAの運用のまま。

## 背景

- 補正値は`subprjs/calib/calib.py`(HA履歴CSV + 参照センサーから
  offset / linear / poly2 を当てはめ)で求め、各ノードのyamlに
  `- id: !extend bme280_1`等で`filters:`として書いている。
- 値を変えるたびに再ビルド + OTAが要るので、HAのUIから変えたい。
- ただしESPHomeの`calibrate_linear`/`calibrate_polynomial`は**コンパイル時に
  datapointsから係数を計算して定数として埋め込む**ため、実行時には変えられない。
  `offset`も`!lambda`を使えばtemplatableだが、linear/polyは不可。
- 実行時に変えるには、`number:`(template)エンティティに値を持たせ、
  `filters:`の`- lambda:`からそれを読む形にするしかない。
  何を`number`で持つかで以下の案に分かれる。

## 案A: 中心化した偏差の係数を3つ持つ

固定の中心値`x0`(センサー/量ごとにyamlで固定。例: 温度23℃、湿度50%)を使い

```
y = x + a + b·(x − x0) + c·(x − x0)²
```

- offset: `a`のみ、linear: `a,b`、poly2: `a,b,c`。全部0で補正なし。
- 値が小さく意味が読める(`a`=x0での誤差、`b`=1℃あたりの傾き誤差)。
  素の多項式係数(例: `-43.2 + 4.72x - 0.079x²`)は桁落ち的な打ち消し合いに
  なり、UIで手打ちする値として不適。
- **面倒な点**:
  - calib.py側で`x0`まわりの係数に変換して表示する必要がある(`x0`をyamlと
    calib.py定義ファイルの両方で揃える必要がある)。
  - `c`は感度が高い(x0から5℃離れると`c`の25倍効く)ので、step/表示桁の
    設定に注意。
  - datapoints形式(`a -> b`)とは見た目が違うので、既存のyaml補正や
    calib.pyのESPHome出力例との対応が直感的でない。

## 案B: datapoints(x→y の組)を持つ

最大3組(=`number`6個)を持ち、係数はデバイス上で計算する
(2組なら直線、3組ならラグランジュ補間で2次。組数は`select:`で切替)。

- yaml・calib.pyの出力(`21.68 -> 21.430`)と同じ形で入れられる。
- **面倒な点**:
  - 1量あたり`number`6個 + `select`1個でUIが散らかる
    (BME280の温湿度だけで14エンティティ)。
  - 未使用の組をどう扱うか(selectとの整合、xが重複した時の0除算ガード)。
  - 値を1つずつ書き換える途中で一時的に変な補正になる。

## 案C: `text:`に文字列で書く

`"21.68->21.43, 24.64->25.01"`のような文字列を`text:`(template)で持ち、
デバイス上でパースして係数を計算する。

- 一番自由で、エンティティも1量1個。
- **面倒な点**:
  - C++でのパース・バリデーション(不正入力時のフォールバック、エラーの
    見せ方)を自前で書く必要がある。
  - 入力ミスに気づきにくい。`text`の最大長制限。

## 共通の実装メモ

- `number:`は`platform: template`、`optimistic: true`、`restore_value: true`
  (NVS保存。書き込みは変更時のみなのでflash摩耗は問題にならない)、
  `initial_value: 0`、`entity_category: config`、`mode: box`。
- 名前はHA側unique_idになる(`mds/2026-09-13_IRHub-esphome-tips.md`参照)ので、
  センサーパッケージの`vars:`の番号に連動させる
  (例: `"BME280 Temperature ${bme280_n} Cal A"`)。
- 補正を使わないノードではエンティティを増やしたくないので、パッケージを
  「センサー本体」と「UI補正」に分けるか、`vars:`で有効/無効を切り替えられる
  ようにする。
- 値変更は次回の測定(update_interval、現状60s)から反映される。即時反映したい
  場合は`number`の`on_value`で`component.update: <sensor id>`を呼ぶ。
- 既存のyaml直書き補正(c6-deskの温度`offset: 0.7`、湿度`calibrate_linear`)は
  移行時に`number`の`initial_value`へ置き換える
  (restore済みの値がある場合はinitial_valueは使われない点に注意)。
- 将来的には、calib.pyがHAのREST API(`number.set_value`)で求めた値を
  直接書き込むこともできる。
