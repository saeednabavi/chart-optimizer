# -*- coding: utf-8 -*-
"""TradingView PineJS ``Std`` semantics on numpy arrays.

Chartix custom indicators run inside the TradingView Charting Library, so their
numbers depend on how ``Std.*`` and ``context.new_var`` behave there:

* A series never stores its first bar (the engine only records depth on bar 0),
  so every ``new_var`` series reads NaN at index 0. Use :func:`nv` for that.
* ``sum`` is a running sum where NaN/inf count as 0; ``sma`` is NaN only when the
  oldest bar of the window is NaN.
* ``ema``/``rma`` seed with the windowed sum / length and reseed after a NaN.
* ``highest``/``lowest`` are NaN when the oldest bar of the window is NaN.
* ``stdev`` is the population deviation around ``sma``; ``dev`` is the mean
  absolute deviation around ``sma``.
* ``cross`` only stores its sign on bars where both inputs are numbers, and the
  first stored sign is dropped like any other new series.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

NAN = float("nan")


def arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def nv(x) -> np.ndarray:
    """``context.new_var(x)`` history: same values, first bar unreadable."""
    out = arr(x).copy()
    if len(out):
        out[0] = NAN
    return out


def nvu(x) -> np.ndarray:
    """``context.new_unlimited_var(x)`` history: its buffer is zero-filled, so bars before the start read 0."""
    out = arr(x).copy()
    if len(out):
        out[0] = 0.0
    return out


def get(x: np.ndarray, k: int, pad: float = NAN) -> np.ndarray:
    """``series.get(k)`` for every bar (k bars back)."""
    k = int(k)
    if k <= 0:
        return x
    out = np.full(len(x), pad)
    if k < len(x):
        out[k:] = x[:-k]
    return out


def _oldest(x: np.ndarray, n: int, pad: float = NAN) -> np.ndarray:
    return get(x, max(1, int(n)) - 1, pad)


def _windows(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    padded = np.concatenate([np.full(n - 1, NAN), x])
    return sliding_window_view(padded, n)


def nz(x, repl: float = 0.0) -> np.ndarray:
    x = arr(x)
    return np.where(np.isfinite(x), x, repl)


def sum_(x: np.ndarray, n: int) -> np.ndarray:
    # Running sum in the engine's order; flat windows depend on the exact rounding.
    n = max(1, int(n))
    cur = nz(x).tolist()
    old = nz(get(arr(x), n)).tolist()
    out = [0.0] * len(cur)
    s = 0.0
    for i in range(len(cur)):
        s = (cur[i] + (s if i > 1 else 0.0)) - old[i]
        out[i] = s
    return arr(out)


def sma(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    s = sum_(x, n) / n
    return np.where(np.isnan(_oldest(x, n)), NAN, s)


def ema(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    s = sum_(x, n).tolist()
    old = _oldest(x, n).tolist()
    xs = arr(x).tolist()
    out = [NAN] * len(xs)
    prev = NAN
    for i in range(len(xs)):
        if math.isnan(old[i]):
            v = NAN
        elif math.isnan(prev):
            v = s[i] / n
        else:
            v = 2 * (xs[i] - prev) / (n + 1) + prev
        out[i] = v
        prev = v
    return arr(out)


def rma(x: np.ndarray, n: int, unlimited: bool = False) -> np.ndarray:
    """``unlimited=True`` when ``x`` comes from :func:`nvu` (nothing is readable on bar 0)."""
    n = max(1, int(n))
    s = sum_(x, n).tolist()
    old = _oldest(x, n, 0.0 if unlimited else NAN).tolist()
    xs = arr(x).tolist()
    out = [NAN] * len(xs)
    prev = NAN
    r = n - 1
    for i in range(len(xs)):
        if unlimited and i == 0:
            v = NAN
        elif math.isnan(old[i]):
            v = NAN
        elif math.isnan(prev):
            v = s[i] / n
        else:
            v = (xs[i] + prev * r) / n
        out[i] = v
        prev = v
    return arr(out)


def _extreme(x: np.ndarray, n: int, fn) -> np.ndarray:
    n = max(1, int(n))
    with np.errstate(all="ignore"):
        w = _windows(x, n)
        valid = ~np.isnan(w)
        filled = np.where(valid, w, -np.inf if fn is np.max else np.inf)
        val = fn(filled, axis=1)
    return np.where(np.isnan(_oldest(x, n)), NAN, val)


def highest(x: np.ndarray, n: int) -> np.ndarray:
    return _extreme(x, n, np.max)


def lowest(x: np.ndarray, n: int) -> np.ndarray:
    return _extreme(x, n, np.min)


def variance(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    m = sma(x, n)
    acc = np.zeros(len(x))
    with np.errstate(all="ignore"):
        for r in range(n):
            d = np.abs(get(x, r) - m)
            acc = acc + d * d
        return acc / n


def stdev(x: np.ndarray, n: int) -> np.ndarray:
    with np.errstate(all="ignore"):
        return np.sqrt(variance(x, n))


def dev(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    m = sma(x, n)
    acc = np.zeros(len(x))
    with np.errstate(all="ignore"):
        for r in range(n):
            acc = acc + np.abs(get(x, r) - m)
        return acc / n


def change(x: np.ndarray) -> np.ndarray:
    return x - get(x, 1)


def tr(high, low, close, fill_first: bool) -> np.ndarray:
    high, low, close = arr(high), arr(low), arr(close)
    prev = get(nv(close), 1)
    if fill_first:
        prev = np.where(np.isnan(prev), close, prev)
    return np.maximum(np.maximum(high - low, np.abs(high - prev)), np.abs(low - prev))


def atr(high, low, close, n: int) -> np.ndarray:
    return rma(nv(tr(high, low, close, False)), n)


def rsi_from(series: np.ndarray, n: int, unlimited: bool = False) -> np.ndarray:
    """RSI as written inline in the Chartix scripts (change → rma → ratio)."""
    ch = change(series)
    store = nvu if unlimited else nv
    up = rma(store(np.maximum(ch, 0.0)), n, unlimited)
    down = rma(store(-np.minimum(ch, 0.0)), n, unlimited)
    with np.errstate(all="ignore"):
        return np.where(down == 0, 100.0, np.where(up == 0, 0.0, 100.0 - 100.0 / (1.0 + up / down)))


def cross(a, b) -> np.ndarray:
    """``Std.cross(a, b)``: sign of (a - b) changed since its last stored bar."""
    av = arr(a).tolist() if not np.isscalar(a) else None
    bv = arr(b).tolist() if not np.isscalar(b) else None
    n = len(av) if av is not None else len(bv)
    out = np.zeros(n, dtype=bool)
    prev = NAN
    created = False
    for i in range(n):
        x = av[i] if av is not None else float(a)
        y = bv[i] if bv is not None else float(b)
        if math.isnan(x) or math.isnan(y):
            continue
        r = x - y
        s = -1.0 if r < 0 else (0.0 if r == 0 else 1.0)
        if not created:
            created = True
            continue
        out[i] = (not math.isnan(prev)) and prev != s
        prev = s
    return out


def source(open_, high, low, close, name: str) -> np.ndarray:
    key = str(name or "close").strip().lower()
    o, h, l, c = arr(open_), arr(high), arr(low), arr(close)
    if key == "open":
        return o
    if key == "high":
        return h
    if key == "low":
        return l
    if key == "hl2":
        return (h + l) / 2
    if key == "hlc3":
        return (h + l + c) / 3
    if key == "ohlc4":
        return (o + h + l + c) / 4
    return c


def where(cond: Sequence[bool], a, b) -> np.ndarray:
    return np.where(np.asarray(cond, dtype=bool), a, b)
