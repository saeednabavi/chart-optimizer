# -*- coding: utf-8 -*-
"""Major tops/bottoms: ZigZag whose reversal threshold adapts to volatility (ATR multiple)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# level -> (ATR multiple, minimum swing %, ATR period); multiple 0 = fixed-percent ZigZag
# "6%" matches the optimizer's default real tops/bottoms (optimizer/find_pivots.py swing:6).
LEVELS: Dict[str, Tuple[float, float, int]] = {
    "Medium": (4.0, 1.0, 50),
    "Major": (8.0, 2.0, 50),
    "6%": (0.0, 6.0, 50),
}


def _atr_pct(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    prev = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    atr = pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()
    with np.errstate(all="ignore"):
        return np.nan_to_num(atr / close * 100.0)


def adaptive_zigzag(
    high: np.ndarray, low: np.ndarray, thr_pct: np.ndarray
) -> Tuple[List[int], List[int], Optional[Tuple[int, str]]]:
    """Confirmed (bottoms, tops) plus the running extreme of the last leg as (index, kind) or None.

    A reversal needs a move of thr_pct (taken at the extreme bar).
    """
    n = len(high)
    bottoms: List[int] = []
    tops: List[int] = []
    if n < 2:
        return bottoms, tops, None
    high, low, thr_pct = np.asarray(high).tolist(), np.asarray(low).tolist(), np.asarray(thr_pct).tolist()
    trend = 0
    max_i = min_i = 0
    for i in range(1, n):
        if trend >= 0 and high[i] >= high[max_i]:
            max_i = i
        if trend <= 0 and low[i] <= low[min_i]:
            min_i = i
        if trend == 0:
            if min_i < max_i and high[max_i] >= low[min_i] * (1 + thr_pct[min_i] / 100):
                bottoms.append(min_i)
                trend = 1
            elif max_i < min_i and low[min_i] <= high[max_i] * (1 - thr_pct[max_i] / 100):
                tops.append(max_i)
                trend = -1
        elif trend == 1:
            if low[i] <= high[max_i] * (1 - thr_pct[max_i] / 100):
                tops.append(max_i)
                trend, min_i = -1, i
        elif high[i] >= low[min_i] * (1 + thr_pct[min_i] / 100):
            bottoms.append(min_i)
            trend, max_i = 1, i
    pending = (max_i, "top") if trend == 1 else (min_i, "bottom") if trend == -1 else None
    return bottoms, tops, pending


def threshold(high: np.ndarray, low: np.ndarray, close: np.ndarray, level: str) -> np.ndarray:
    """Per-bar reversal threshold (%) of `level`."""
    mult, min_pct, period = LEVELS[level]
    return np.maximum(min_pct, mult * _atr_pct(high, low, close, period))


def pivot_indices(high: np.ndarray, low: np.ndarray, thr_pct: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Confirmed (bottoms, tops) as index arrays; the unconfirmed last leg is left out."""
    bottoms, tops, _ = adaptive_zigzag(high, low, thr_pct)
    return np.asarray(bottoms, dtype=np.int64), np.asarray(tops, dtype=np.int64)


def find_pivots(df: pd.DataFrame, level: str) -> List[Dict[str, Any]]:
    """Chart markers (main pane) for the confirmed tops/bottoms of `df` at `level`."""
    if level not in LEVELS or df is None or len(df) < 3:
        return []
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    thr = threshold(high, low, close, level)
    bottoms, tops, pending = adaptive_zigzag(high, low, thr)

    points = sorted([(i, "bottom", low[i], True) for i in bottoms] + [(i, "top", high[i], True) for i in tops])
    if pending is not None:
        i, kind = pending
        # Last leg is unconfirmed: show its extreme once price has pulled back half the threshold.
        if kind == "top":
            pullback = (1 - low[i + 1:].min() / high[i]) * 100 if i + 1 < len(df) else 0.0
            price = high[i]
        else:
            pullback = (high[i + 1:].max() / low[i] - 1) * 100 if i + 1 < len(df) else 0.0
            price = low[i]
        if pullback >= thr[i] / 2:
            points.append((i, kind, price, False))

    markers: List[Dict[str, Any]] = []
    prev_price = None
    for i, kind, price, confirmed in points:
        swing = "" if prev_price is None else f" ({(price / prev_price - 1) * 100:+.1f}%)"
        prev_price = price
        bottom = kind == "bottom"
        if confirmed:
            color = "#00e676" if bottom else "#ff5252"
        else:
            color = "#80cbc4" if bottom else "#ffab91"
        markers.append({
            "time": df["time"].iloc[i],
            "position": "below" if bottom else "above",
            "shape": "arrow_up" if bottom else "arrow_down",
            "color": color,
            "text": f"{'?' if not confirmed else ''}{price:,.0f}{swing}",
        })
    return markers
