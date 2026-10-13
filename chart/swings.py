# -*- coding: utf-8 -*-
"""Alternating tops/bottoms (swing points) at two levels: minor and major.

Rules
-----
* Tops and bottoms always alternate: between two tops there is exactly one bottom (and vice versa).
* A top is the highest high between its two neighbouring bottoms; a bottom is the lowest low
  between its two neighbouring tops.
* Noise filter per level:
    - ``pct``      : minimum swing size in percent (top / bottom - 1).
    - ``atr_mult`` : optional volatility-adaptive threshold; the effective threshold of a leg is
                     max(pct, atr_mult * ATR%) measured at the leg's first pivot. 0 disables it.
    - ``min_bars`` : minimum number of bars between two consecutive pivots.
* Major pivots are always a subset of minor pivots (a major top is also a minor top).

Algorithm
---------
1. Minor candidates come from a ZigZag with the minor threshold (guarantees alternation + true extremes).
2. Legs that break the level's rules are removed smallest-first. Removing a leg drops one top and one
   bottom, keeping the more extreme pivot of each kind, so alternation and extremes are preserved.
3. Major pivots = the same pruning applied to the minor pivots with the major rules.

Usage
-----
    python -m chart.swings BRS001195 1d
    python -m chart.swings BRS001195 1h --minor-pct 3 --major-pct 10 --minor-bars 3 --major-bars 15
"""

from __future__ import annotations

import argparse
import heapq
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chart.data_loader import PROJECT_ROOT, load_ohlcv

SETTINGS_FILE = Path(__file__).resolve().parent / "swing_settings.json"
OUTPUT_DIR = PROJECT_ROOT / "output" / "swings"

TOP, BOTTOM = 1, -1


@dataclass
class SwingLevel:
    pct: float = 5.0
    atr_mult: float = 0.0
    min_bars: int = 3


@dataclass
class SwingConfig:
    minor: SwingLevel = field(default_factory=lambda: SwingLevel(5.0, 0.0, 3))
    major: SwingLevel = field(default_factory=lambda: SwingLevel(15.0, 0.0, 10))
    atr_period: int = 50

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "SwingConfig":
        d = d or {}
        base = cls()
        return cls(
            minor=SwingLevel(**{**asdict(base.minor), **(d.get("minor") or {})}),
            major=SwingLevel(**{**asdict(base.major), **(d.get("major") or {})}),
            atr_period=int(d.get("atr_period", base.atr_period)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_config(timeframe: Optional[str] = None) -> SwingConfig:
    """Settings from swing_settings.json: {"default": {...}, "1h": {...}} — timeframe overrides default."""
    if not SETTINGS_FILE.exists():
        return SwingConfig()
    data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    merged = dict(data.get("default") or {})
    for k, v in (data.get(timeframe) or {}).items():
        merged[k] = {**(merged.get(k) or {}), **v} if isinstance(v, dict) else v
    return SwingConfig.from_dict(merged)


def atr_pct(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    atr = pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()
    with np.errstate(all="ignore"):
        return np.nan_to_num(atr / close * 100.0)


def level_threshold(atr: np.ndarray, level: SwingLevel) -> np.ndarray:
    """Per-bar minimum swing (%) of a level."""
    if level.atr_mult <= 0:
        return np.full(len(atr), float(level.pct))
    return np.maximum(float(level.pct), level.atr_mult * atr)


def zigzag(high: np.ndarray, low: np.ndarray, thr: np.ndarray) -> List[Tuple[int, int]]:
    """Alternating (bar, kind) pivots in time order; the last one is the still-running extreme.

    Both directions use top / bottom - 1 >= thr, so a lower low after a bottom always flips the
    trend first and every bottom stays the lowest low between its tops (and vice versa).
    """
    n = len(high)
    out: List[Tuple[int, int]] = []
    if n < 2:
        return out
    high, low, thr = np.asarray(high).tolist(), np.asarray(low).tolist(), np.asarray(thr).tolist()
    trend = 0
    max_i = min_i = 0
    for i in range(1, n):
        if trend >= 0 and high[i] >= high[max_i]:
            max_i = i
        if trend <= 0 and low[i] <= low[min_i]:
            min_i = i
        if trend == 0:
            if min_i < max_i and high[max_i] >= low[min_i] * (1 + thr[min_i] / 100):
                out.append((min_i, BOTTOM))
                trend = 1
            elif max_i < min_i and high[max_i] >= low[min_i] * (1 + thr[max_i] / 100):
                out.append((max_i, TOP))
                trend = -1
        elif trend == 1:
            if high[max_i] >= low[i] * (1 + thr[max_i] / 100):
                out.append((max_i, TOP))
                trend, min_i = -1, i
        elif high[i] >= low[min_i] * (1 + thr[min_i] / 100):
            out.append((min_i, BOTTOM))
            trend, max_i = 1, i
    if trend == 1:
        out.append((max_i, TOP))
    elif trend == -1:
        out.append((min_i, BOTTOM))
    return out


def prune(
    bars: List[int],
    kinds: List[int],
    prices: List[float],
    thr: np.ndarray,
    min_bars: int,
    high: np.ndarray,
    low: np.ndarray,
) -> List[int]:
    """Positions (into the input lists) of the pivots that survive the level's rules."""
    n = len(bars)
    n_bars = len(high)
    if n < 3:
        return list(range(n))
    prv = list(range(-1, n - 1))
    nxt = list(range(1, n + 1))
    nxt[-1] = -1
    alive = [True] * n

    def swing(a: int, b: int) -> float:
        hi, lo = (prices[a], prices[b]) if kinds[a] == TOP else (prices[b], prices[a])
        return (hi / lo - 1) * 100 if lo > 0 else 0.0

    def ratio(a: int, b: int) -> float:
        t = thr[bars[a]]
        return swing(a, b) / t if t > 0 else float("inf")

    def violates(a: int, b: int) -> bool:
        return ratio(a, b) < 1 or bars[b] - bars[a] < min_bars

    def more_extreme(x: int, y: int) -> bool:
        return prices[x] >= prices[y] if kinds[x] == TOP else prices[x] <= prices[y]

    def beats_bars(x: int, lo: int, hi: int) -> bool:
        """Is pivot x at least as extreme as every bar in [lo, hi)?"""
        if lo >= hi:
            return True
        if kinds[x] == TOP:
            return prices[x] >= high[lo:hi].max()
        return prices[x] <= low[lo:hi].min()

    def can_drop(x: int, y: int) -> bool:
        """Removing x..y (one pivot, or two adjacent ones) keeps alternation and true extremes."""
        p, q = prv[x], nxt[y]
        if p < 0 and q < 0:
            return False
        if x == y:
            if p < 0:
                return beats_bars(q, 0, bars[x] + 1)
            if q < 0:
                return beats_bars(p, bars[x], n_bars)
            return False
        if p < 0:
            return more_extreme(q, x)
        if q < 0:
            return more_extreme(p, y)
        return more_extreme(p, y) and more_extreme(q, x)

    def choose_drop(a: int, b: int) -> Optional[Tuple[int, int]]:
        p, q = prv[a], nxt[b]
        options: List[Tuple[int, int]] = []
        if p < 0:
            options.append((a, a))
        if q < 0:
            options.append((b, b))
        options.append((a, b))
        side = []
        if p >= 0:
            side.append((swing(p, a), (p, a)))
        if q >= 0:
            side.append((swing(b, q), (b, q)))
        options += [o for _, o in sorted(side)]
        return next((o for o in options if can_drop(*o)), None)

    heap: List[Tuple[float, int, int]] = []
    for a in range(n - 1):
        if violates(a, a + 1):
            heapq.heappush(heap, (ratio(a, a + 1), a, a + 1))

    while heap:
        _, a, b = heapq.heappop(heap)
        if not (alive[a] and alive[b] and nxt[a] == b) or not violates(a, b):
            continue
        drop = choose_drop(a, b)
        if drop is None:
            continue
        x, y = drop
        p, q = prv[x], nxt[y]
        alive[x] = alive[y] = False
        if p >= 0:
            nxt[p] = q
        if q >= 0:
            prv[q] = p
        if p >= 0 and q >= 0 and violates(p, q):
            heapq.heappush(heap, (ratio(p, q), p, q))

    return [i for i in range(n) if alive[i]]


def _is_confirmed(bar: int, kind: int, high: np.ndarray, low: np.ndarray, thr: float) -> bool:
    """Has price already reversed `thr` % away from this pivot?"""
    if bar + 1 >= len(high):
        return False
    if kind == TOP:
        return (high[bar] / low[bar + 1:].min() - 1) * 100 >= thr
    return (high[bar + 1:].max() / low[bar] - 1) * 100 >= thr


def find_swings(df: pd.DataFrame, cfg: Optional[SwingConfig] = None) -> pd.DataFrame:
    """One row per minor pivot; major pivots have level == 'major'.

    Columns: bar, time, kind ('top'/'bottom'), price, level ('major'/'minor'), confirmed,
    swing_pct / bars_from_prev (vs previous minor pivot), major_swing_pct / major_bars_from_prev
    (vs previous major pivot, major rows only).
    """
    cfg = cfg or SwingConfig()
    cols = ["bar", "time", "kind", "price", "level", "confirmed",
            "swing_pct", "bars_from_prev", "major_swing_pct", "major_bars_from_prev"]
    if df is None or len(df) < 3:
        return pd.DataFrame(columns=cols)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    atr = atr_pct(high, low, close, cfg.atr_period)
    thr_minor = level_threshold(atr, cfg.minor)
    thr_major = level_threshold(atr, cfg.major)

    raw = zigzag(high, low, thr_minor)
    if not raw:
        return pd.DataFrame(columns=cols)
    bars = [b for b, _ in raw]
    kinds = [k for _, k in raw]
    prices = [high[b] if k == TOP else low[b] for b, k in raw]

    keep = prune(bars, kinds, prices, thr_minor, cfg.minor.min_bars, high, low)
    bars = [bars[i] for i in keep]
    kinds = [kinds[i] for i in keep]
    prices = [prices[i] for i in keep]
    major_pos = set(prune(bars, kinds, prices, thr_major, cfg.major.min_bars, high, low))

    rows = []
    last_major: Optional[int] = None
    for i, (b, k, px) in enumerate(zip(bars, kinds, prices)):
        is_major = i in major_pos
        prev_px = prices[i - 1] if i > 0 else None
        row = {
            "bar": b,
            "time": df["time"].iloc[b],
            "kind": "top" if k == TOP else "bottom",
            "price": px,
            "level": "major" if is_major else "minor",
            "confirmed": True,
            "swing_pct": None if prev_px is None else round((px / prev_px - 1) * 100, 2),
            "bars_from_prev": None if i == 0 else b - bars[i - 1],
            "major_swing_pct": None,
            "major_bars_from_prev": None,
        }
        if is_major:
            if last_major is not None:
                row["major_swing_pct"] = round((px / prices[last_major] - 1) * 100, 2)
                row["major_bars_from_prev"] = b - bars[last_major]
            last_major = i
        rows.append(row)

    out = pd.DataFrame(rows, columns=cols)
    # Only the last pivot of each level can still be running.
    last = len(out) - 1
    out.at[last, "confirmed"] = _is_confirmed(bars[last], kinds[last], high, low, thr_minor[bars[last]])
    if last_major is not None:
        out.at[last_major, "confirmed"] = _is_confirmed(
            bars[last_major], kinds[last_major], high, low, thr_major[bars[last_major]]
        )
    return out


def chart_markers(df: pd.DataFrame, cfg: Optional[SwingConfig] = None) -> List[Dict[str, Any]]:
    """Main-pane markers: big arrows for major pivots, small circles for minor ones."""
    sw = find_swings(df, cfg)
    markers: List[Dict[str, Any]] = []
    for r in sw.itertuples(index=False):
        top = r.kind == "top"
        if r.level == "major":
            color = ("#ff1744" if top else "#00e676") if r.confirmed else ("#ffab91" if top else "#80cbc4")
            pct = "" if pd.isna(r.major_swing_pct) else f" ({r.major_swing_pct:+.1f}%)"
            markers.append({
                "time": r.time,
                "position": "above" if top else "below",
                "shape": "arrow_down" if top else "arrow_up",
                "color": color,
                "text": f"{'?' if not r.confirmed else ''}{r.price:,.0f}{pct}",
            })
        else:
            markers.append({
                "time": r.time,
                "position": "above" if top else "below",
                "shape": "circle",
                "color": "#ef9a9a" if top else "#a5d6a7",
                "text": "" if r.confirmed else "?",
            })
    return markers


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Find major/minor tops and bottoms.")
    ap.add_argument("ticker")
    ap.add_argument("timeframe", nargs="?", default="1d")
    ap.add_argument("--adj", default="adjusted")
    ap.add_argument("--minor-pct", type=float)
    ap.add_argument("--minor-atr", type=float, help="ATR multiple for minor (0 = fixed percent)")
    ap.add_argument("--minor-bars", type=int)
    ap.add_argument("--major-pct", type=float)
    ap.add_argument("--major-atr", type=float, help="ATR multiple for major (0 = fixed percent)")
    ap.add_argument("--major-bars", type=int)
    ap.add_argument("--atr-period", type=int)
    ap.add_argument("--out", help="CSV path (default output/swings/<ticker>_<tf>_<adj>.csv)")
    args = ap.parse_args(argv)

    cfg = load_config(args.timeframe)
    for lvl_name in ("minor", "major"):
        lvl = getattr(cfg, lvl_name)
        for attr, arg in (("pct", "pct"), ("atr_mult", "atr"), ("min_bars", "bars")):
            v = getattr(args, f"{lvl_name}_{arg}")
            if v is not None:
                setattr(lvl, attr, v)
    if args.atr_period is not None:
        cfg.atr_period = args.atr_period

    df = load_ohlcv(args.ticker, args.timeframe, args.adj)
    sw = find_swings(df, cfg)
    out = Path(args.out) if args.out else OUTPUT_DIR / f"{args.ticker}_{args.timeframe}_{args.adj}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    sw.to_csv(out, index=False, encoding="utf-8-sig")

    n_major = int((sw["level"] == "major").sum())
    print(f"{args.ticker} {args.timeframe} {args.adj}: bars={len(df)} pivots={len(sw)} "
          f"(major={n_major}, minor-only={len(sw) - n_major})")
    print(f"config: {json.dumps(cfg.to_dict())}")
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
