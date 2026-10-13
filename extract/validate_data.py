# -*- coding: utf-8 -*-
"""Cross-check downloaded CSVs: rebuild higher timeframes from 1min and compare."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent / "data" / "csv_data"
ADJ = sys.argv[1] if len(sys.argv) > 1 else "adjusted"
RECENT_DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 60


def load(sym: str, tf: str) -> pd.DataFrame | None:
    p = ROOT / sym / f"{tf}_{ADJ}.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, encoding="utf-8-sig", parse_dates=["time"])
    return df.set_index("time").sort_index()


def agg(m1: pd.DataFrame, key: pd.Series) -> pd.DataFrame:
    g = m1.groupby(key)
    return pd.DataFrame({
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
        "volume": g["volume"].sum(),
    })


def compare(name: str, ref: pd.DataFrame, built: pd.DataFrame) -> str:
    common = ref.index.intersection(built.index)
    if len(common) == 0:
        return f"{name}: no overlap"
    r = ref.loc[common]
    b = built.loc[common]
    tol = 1e-6
    bad = ((r[["open", "high", "low", "close"]] - b[["open", "high", "low", "close"]]).abs()
           > tol * r["close"].abs().values[:, None] + 1e-9).any(axis=1)
    vbad = (r["volume"] - b["volume"]).abs() > 0.5
    missing_in_1m = ref.index.difference(built.index)
    out = (f"{name}: compared={len(common)} ohlc_mismatch={int(bad.sum())} "
           f"vol_mismatch={int(vbad.sum())} ref_bars_missing_in_1m={len(missing_in_1m)}")
    if bad.any():
        idx = r.index[bad][-3:]
        for t in idx:
            out += f"\n     {t}  ref={r.loc[t, ['open','high','low','close','volume']].tolist()}"
            out += f"\n     {' ' * len(str(t))}  1m ={b.loc[t, ['open','high','low','close','volume']].tolist()}"
    return out


def main() -> None:
    syms = sorted(p.name for p in ROOT.iterdir() if p.is_dir())
    for sym in syms:
        m1 = load(sym, "1min")
        if m1 is None:
            print(f"== {sym}: no 1min file")
            continue
        cutoff = m1.index.max() - pd.Timedelta(days=RECENT_DAYS)
        m1 = m1[m1.index >= cutoff]
        print(f"== {sym}  1min last={m1.index.max()}  bars(last {RECENT_DAYS}d)={len(m1)}")
        dup = m1.index.duplicated().sum()
        if dup:
            print(f"   duplicated 1min timestamps: {dup}")

        for tf, minutes in (("5min", 5), ("15min", 15), ("30min", 30), ("1h", 60)):
            ref = load(sym, tf)
            if ref is None:
                continue
            ref = ref[ref.index >= cutoff + pd.Timedelta(days=1)]
            key = m1.index.floor(f"{minutes}min")
            built = agg(m1, pd.Series(key, index=m1.index))
            print("   " + compare(tf, ref, built))

        ref = load(sym, "1d")
        if ref is not None:
            ref = ref[ref.index >= cutoff + pd.Timedelta(days=1)]
            ref.index = ref.index.normalize()
            built = agg(m1, pd.Series(m1.index.normalize(), index=m1.index))
            print("   " + compare("1d", ref, built))


if __name__ == "__main__":
    main()
