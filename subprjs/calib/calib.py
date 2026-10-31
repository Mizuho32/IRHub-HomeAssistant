#!/usr/bin/env python3
"""HAの履歴CSVから、参照センサーに対するターゲットセンサーの補正式を求める。

    venv/bin/python calib.py calib.yaml

定義ファイル(calib.yaml)の書式は calib.example.yaml 参照。
入力CSVは、HAの履歴画面で参照/ターゲットのエンティティを表示し、
「データをダウンロード」で得たもの(entity_id,state,last_changed)。

処理:
  1. 各系列を1分グリッドに前方補完して揃える(HAは値の変化時しか記録しない)。
  2. ターゲットに既に補正(applied:)がかかっていれば、その逆変換で生値に戻す。
  3. センサー間の応答遅れを推定し、その分ずらして組を作る。
  4. offset / linear / poly2 で「生値 -> 参照値」を当てはめ、前半で学習して
     後半で検証(とその逆)した誤差を並べ、ESPHomeのfilters例を表示する。
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime

import numpy as np
import yaml

GRID_S = 60
MAX_HOLD_S = 30 * 60  # これ以上記録が無ければ欠測とみなす


def load_csv(path: str) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    pts: dict[str, list[tuple[float, float]]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t = datetime.fromisoformat(row["last_changed"].replace("Z", "+00:00")).timestamp()
            try:
                v = float(row["state"])
            except ValueError:
                v = np.nan  # unavailable/unknown は NaN (=そこから欠測)
            pts.setdefault(row["entity_id"], []).append((t, v))
    out = {}
    for ent, p in pts.items():
        a = np.array(sorted(p))
        out[ent] = (a[:, 0], a[:, 1])
    return out


def resample(t: np.ndarray, v: np.ndarray, grid: np.ndarray) -> np.ndarray:
    i = np.searchsorted(t, grid, side="right") - 1
    ok = i >= 0
    out = np.full(grid.shape, np.nan)
    out[ok] = v[i[ok]]
    out[ok & (grid - t[np.clip(i, 0, None)] > MAX_HOLD_S)] = np.nan
    return out


# --- 既にかかっている補正(ESPHomeのfilters:の書式)の解釈と逆変換 ---

def _datapoints(spec) -> np.ndarray:
    pts = spec["datapoints"] if isinstance(spec, dict) else spec
    return np.array([[float(s) for s in p.split("->")] if isinstance(p, str) else p for p in pts], dtype=float)


def filter_poly(f: dict) -> np.polynomial.Polynomial:
    """1つのfilterを x -> y の多項式として返す。"""
    (kind, spec), = f.items()
    P = np.polynomial.Polynomial
    if kind == "offset":
        return P([spec, 1.0])
    if kind == "multiply":
        return P([0.0, spec])
    if kind == "calibrate_linear":
        d = _datapoints(spec)
        return P.fit(d[:, 0], d[:, 1], 1).convert()
    if kind == "calibrate_polynomial":
        d = _datapoints(spec)
        return P.fit(d[:, 0], d[:, 1], spec["degree"]).convert()
    raise ValueError(f"未対応のfilter: {kind} (offset/multiply/calibrate_linear/calibrate_polynomialのみ)")


def invert(p: np.polynomial.Polynomial, y: np.ndarray) -> np.ndarray:
    """y = p(x) を満たす x。2次以上で解が複数あるときは y に最も近い実数解を採る
    (補正量は小さいので、元の値は補正後の値の近くにあるはず)。"""
    x = np.full(y.shape, np.nan)
    for i, yi in enumerate(y):
        if np.isnan(yi):
            continue
        r = (p - yi).roots()
        r = r[np.abs(r.imag) < 1e-9].real
        if r.size:
            x[i] = r[np.argmin(np.abs(r - yi))]
    return x


def undo_applied(v: np.ndarray, applied: list[dict]) -> np.ndarray:
    for f in reversed(applied):  # filtersは上から順にかかるので、逆順に戻す
        v = invert(filter_poly(f), v)
    return v


# --- 当てはめ ---

def fit(kind: str, x: np.ndarray, y: np.ndarray) -> np.polynomial.Polynomial:
    P = np.polynomial.Polynomial
    if kind == "offset":
        return P([np.mean(y - x), 1.0])
    deg = {"linear": 1, "poly2": 2, "poly3": 3}[kind]
    return P.fit(x, y, deg).convert()


def rmse(p, x, y) -> float:
    return float(np.sqrt(np.mean((p(x) - y) ** 2)))


def paired(ref: np.ndarray, tgt: np.ndarray, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """lag>0: ターゲットが参照よりlag分遅れて追従(tgt[i+lag]とref[i]を組にする)。"""
    if lag >= 0:
        r, t = ref[: len(ref) - lag], tgt[lag:]
    else:
        r, t = ref[-lag:], tgt[: len(tgt) + lag]
    ok = ~np.isnan(r) & ~np.isnan(t)
    return t[ok], r[ok]


def estimate_lag(ref, tgt, max_lag: int) -> int:
    cands = [(rmse(fit("linear", *xy), *xy), lag)
             for lag in range(-max_lag, max_lag + 1)
             if len((xy := paired(ref, tgt, lag))[0]) >= 30]
    return min(cands)[1] if cands else 0


def esphome_filter(kind: str, p, lo: float, hi: float) -> str:
    """当てはめ結果を、生値に対するESPHomeのfilters:として書く。
    calibrate_*は内部で最小二乗するだけなので、当てはめた式上の点を渡せば同じ式になる。"""
    if kind == "offset":
        return f"filters:\n  - offset: {p.coef[0]:.3f}"
    if kind == "linear":
        xs = [lo, hi]
        head = "filters:\n  - calibrate_linear:\n      datapoints:"
    else:
        deg = p.degree()
        xs = list(np.linspace(lo, hi, deg + 1))
        head = f"filters:\n  - calibrate_polynomial:\n      degree: {deg}\n      datapoints:"
    return head + "".join(f"\n        - {x:.2f} -> {p(x):.3f}" for x in xs)


def indent(s: str, n: int) -> str:
    return "\n".join(" " * n + line for line in s.splitlines())


def analyze(ref: np.ndarray, tgt_cfg: dict, tgt: np.ndarray, models: list[str], max_lag: int) -> None:
    name = tgt_cfg["entity"]
    applied = tgt_cfg.get("applied") or []
    print(f"\n=== {name}")
    if applied:
        print(f"  既存の補正を逆変換して生値に戻して計算: {applied}")
        tgt = undo_applied(tgt, applied)
    lag = estimate_lag(ref, tgt, max_lag) if max_lag else 0
    x, y = paired(ref, tgt, lag)
    if len(x) < 20:
        print(f"  有効な組が{len(x)}個しかないためスキップ")
        return
    print(f"  有効な組: {len(x)}個 ({len(x) * GRID_S / 3600:.1f}h分)  推定遅れ: {lag:+d}分")
    print(f"  生値の範囲: {x.min():.2f} .. {x.max():.2f}   参照の範囲: {y.min():.2f} .. {y.max():.2f}")
    print(f"  補正なし(生値そのまま)の誤差: RMSE {rmse(np.polynomial.Polynomial([0, 1]), x, y):.3f}"
          f"   平均 {np.mean(x - y):+.3f} (生値-参照)")
    if applied:
        cur = np.polynomial.Polynomial([0, 1])
        for f in applied:
            cur = filter_poly(f)(cur)
        print(f"  既存の補正をかけた値(=今のHA上の値)の誤差: RMSE {rmse(cur, x, y):.3f}")

    h = len(x) // 2
    folds = [(slice(None, h), slice(h, None)), (slice(h, None), slice(None, h))]
    print(f"  {'model':7s} {'学習RMSE':>8s} {'検証RMSE':>8s} {'検証最大誤差':>10s}   式(全データ, 生値x -> 補正後)")
    for k in models:
        tr = [rmse(fit(k, x[a], y[a]), x[a], y[a]) for a, _ in folds]
        te = [rmse(fit(k, x[a], y[a]), x[b], y[b]) for a, b in folds]
        mx = [float(np.max(np.abs(fit(k, x[a], y[a])(x[b]) - y[b]))) for a, b in folds]
        p = fit(k, x, y)
        terms = " ".join(f"{c:+.5g}" + ("" if i == 0 else "*x" if i == 1 else f"*x^{i}") for i, c in enumerate(p.coef))
        print(f"  {k:7s} {np.mean(tr):8.3f} {np.mean(te):8.3f} {max(mx):10.3f}   {terms}")
    print("  ESPHomeのfilters例(既存のfilters:と置き換える。生値に対する補正):")
    for k in models:
        print(f"    # {k}")
        print(indent(esphome_filter(k, fit(k, x, y), float(x.min()), float(x.max())), 4))


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    cfg = yaml.safe_load(open(sys.argv[1]))
    series = load_csv(cfg["csv"])
    ents = [cfg["reference"], *(t["entity"] for t in cfg["targets"])]
    if missing := [e for e in ents if e not in series]:
        print(f"error: CSVに無いエンティティ: {missing}\n  CSVにあるもの: {list(series)}", file=sys.stderr)
        return 1
    t0 = min(t[0] for t, _ in series.values())
    t1 = max(t[-1] for t, _ in series.values())
    grid = np.arange(t0, t1, GRID_S)
    ref = resample(*series[cfg["reference"]], grid)
    print(f"参照: {cfg['reference']}")
    models = cfg.get("models", ["offset", "linear", "poly2"])
    for tc in cfg["targets"]:
        analyze(ref, tc, resample(*series[tc["entity"]], grid), models, cfg.get("max_lag_min", 20))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
