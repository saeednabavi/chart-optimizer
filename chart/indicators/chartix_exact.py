# -*- coding: utf-8 -*-
"""Exact ports of the Chartix "اختصاصی" indicators (max.chartix.ir bundle).

Each function mirrors the indicator's ``main()`` from the Chartix JavaScript and
returns one column per Chartix plot id, so a row is what Chartix computes for
that bar. Shapes/flags are 1.0 where Chartix draws them and NaN elsewhere.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import numpy as np
import pandas as pd

from . import pinejs as pj
from .common import ensure_ohlcv

NAN = float("nan")


def _ohlc(df: pd.DataFrame):
    data = ensure_ohlcv(df)
    return (
        data,
        data["open"].to_numpy(dtype=float),
        data["high"].to_numpy(dtype=float),
        data["low"].to_numpy(dtype=float),
        data["close"].to_numpy(dtype=float),
    )


def _flag(cond) -> np.ndarray:
    return np.where(np.asarray(cond, dtype=bool), 1.0, NAN)


def _frame(data: pd.DataFrame, cols: Dict[str, Any]) -> pd.DataFrame:
    out = pd.DataFrame({"time": data["time"].to_numpy()})
    for k, v in cols.items():
        vals = np.asarray(v, dtype=float) if not np.isscalar(v) else np.full(len(out), float(v))
        # Chartix does not draw ±inf (flat windows divide by a zero deviation).
        out[k] = np.where(np.isinf(vals), NAN, vals)
    return out


def ai_engulfing(
    df: pd.DataFrame, source: str = "close", length: int = 14, overbought: float = 70, oversold: float = 30
) -> pd.DataFrame:
    data, o, h, l, c = _ohlc(df)
    src = pj.nv(pj.source(o, h, l, c, source))
    cl, op = pj.nv(c), pj.nv(o)
    prev_open = pj.get(op, 1)
    bull = (pj.get(cl, 1) < prev_open) & (c >= prev_open)
    bear = (pj.get(cl, 1) > prev_open) & (c <= prev_open)
    rsi = pj.rsi_from(src, int(length))
    ob = rsi >= overbought
    os_ = rsi <= oversold
    ob_s, os_s = pj.nv(ob), pj.nv(os_)
    os_recent = (pj.get(os_s, 2) == 1) | os_ | (pj.get(os_s, 1) == 1)
    ob_recent = (pj.get(ob_s, 2) == 1) | ob | (pj.get(ob_s, 1) == 1)
    g = (os_recent & bull) | (ob_recent & bear)
    return _frame(data, {"bullish": _flag(g & bull), "bearish": _flag(g & bear), "rsi": rsi})


def bulls_v_bears(df: pd.DataFrame, period: int = 14, bars_back: int = 120, line_height: float = 80) -> pd.DataFrame:
    data, o, h, l, c = _ohlc(df)
    ma = pj.ema(pj.nv(c), int(period))
    bulls = h - ma
    bears = ma - l
    bs, rs = pj.nv(bulls), pj.nv(bears)
    with np.errstate(all="ignore"):
        lo_b, hi_b = pj.lowest(bs, bars_back), pj.highest(bs, bars_back)
        z = ((bulls - lo_b) / (hi_b - lo_b) - 0.5) * 100
        lo_r, hi_r = pj.lowest(rs, bars_back), pj.highest(rs, bars_back)
        hh = ((bears - lo_r) / (hi_r - lo_r) - 0.5) * 100
    g = z - hh
    color = np.where(g > 0, 0.0, 1.0)
    dots = np.where((g > line_height) | (g < -line_height), g, NAN)
    return _frame(data, {"plot_00": g, "plot_00c": color, "plot_01": dots})


def _stoch_kd(h, l, c, length: int, smooth_k: int, smooth_d: int):
    hi = pj.highest(pj.nv(h), length)
    lo = pj.lowest(pj.nv(l), length)
    with np.errstate(all="ignore"):
        raw = np.where(hi == lo, 0.0, (c - lo) / (hi - lo) * 100)
    k = pj.sma(pj.nv(raw), smooth_k)
    d = pj.sma(pj.nv(k), smooth_d)
    return k, d


_RES_TO_TF = {
    "1": "1min", "2": "2min", "3": "3min", "5": "5min", "10": "10min", "15": "15min", "30": "30min", "45": "45min",
    "60": "1h", "120": "2h", "180": "3h", "240": "4h", "D": "1d", "1D": "1d", "W": "1w", "1W": "1w",
    "M": "1mon", "1M": "1mon",
}


def resolution_to_tf(res: str) -> Optional[str]:
    """Chartix resolution string ("60", "D", ...) → CSV timeframe label ("1h", "1d", ...)."""
    return _RES_TO_TF.get(str(res).strip()) or _RES_TO_TF.get(str(res).strip().upper())


def _same_resolution(res: str, chart_res: Optional[str]) -> bool:
    if str(res) == str(chart_res):
        return True
    norm = {"1d": "D", "d": "D", "1w": "W", "w": "W", "1mon": "M", "1m": "M", "m": "M", "1h": "60", "2h": "120",
            "3h": "180", "4h": "240", "1min": "1", "2min": "2", "3min": "3", "5min": "5", "10min": "10", "15min": "15", "30min": "30",
            "45min": "45"}
    a = norm.get(str(res).strip().lower(), str(res).strip().upper())
    b = norm.get(str(chart_res).strip().lower(), str(chart_res).strip().upper())
    return a == b


def _stoch_on(
    data: pd.DataFrame,
    res: str,
    chart_res: Optional[str],
    htf_loader: Optional[Callable[[str], Optional[pd.DataFrame]]],
    length: int,
    smooth_k: int,
    smooth_d: int,
):
    h = data["high"].to_numpy(dtype=float)
    l = data["low"].to_numpy(dtype=float)
    c = data["close"].to_numpy(dtype=float)
    if _same_resolution(res, chart_res):
        return _stoch_kd(h, l, c, length, smooth_k, smooth_d)
    other = htf_loader(res) if htf_loader else None
    if other is None or other.empty:
        from .common import resample_ohlcv

        other = resample_ohlcv(data, res)
        # Chartix adopts the other-timeframe bar by its open time; resample_ohlcv labels bars at their close.
        other = other.copy()
        other["time"] = other["time"].shift(1)
        other = other.dropna(subset=["time"])
    other = ensure_ohlcv(other)
    k, d = _stoch_kd(
        other["high"].to_numpy(dtype=float),
        other["low"].to_numpy(dtype=float),
        other["close"].to_numpy(dtype=float),
        length,
        smooth_k,
        smooth_d,
    )
    left = pd.DataFrame({"time": data["time"].to_numpy()})
    right = pd.DataFrame({"time": other["time"].to_numpy(), "k": k, "d": d}).sort_values("time")
    merged = pd.merge_asof(left, right, on="time", direction="backward")
    return merged["k"].to_numpy(dtype=float), merged["d"].to_numpy(dtype=float)


def eagles_nest(
    df: pd.DataFrame,
    length: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
    upper: float = 80,
    lower: float = 20,
    show_mid: bool = True,
    show_high_low_bg: bool = False,
    show_strict_bg: bool = True,
    show_strict_letters: bool = True,
    show_any_bg: bool = False,
    show_any_letters: bool = False,
    use_current_resolution: bool = True,
    resolution: str = "60",
    show_second: bool = False,
    resolution2: str = "D",
    use_current_resolution2: bool = False,
    length2: int = 14,
    smooth_k2: int = 3,
    smooth_d2: int = 3,
    chart_resolution: Optional[str] = None,
    htf_loader: Optional[Callable[[str], Optional[pd.DataFrame]]] = None,
) -> pd.DataFrame:
    data = ensure_ohlcv(df)
    cur = chart_resolution if chart_resolution is not None else "__chart__"
    res1 = cur if use_current_resolution else resolution
    res2 = cur if use_current_resolution2 else resolution2
    k, d = _stoch_on(data, res1, cur, htf_loader, length, smooth_k, smooth_d)
    if show_second:
        k2, d2 = _stoch_on(data, res2, cur, htf_loader, length2, smooth_k2, smooth_d2)
    else:
        k2 = d2 = np.full(len(data), NAN)
    pk, pd_ = pj.get(pj.nv(k), 1), pj.get(pj.nv(d), 1)
    strict_buy = (pk < pd_) & (pk < lower) & (k > d)
    strict_sell = (pk > pd_) & (pk > upper) & (k < d)
    any_buy = (pk < pd_) & (k > d)
    any_sell = (pk > pd_) & (k < d)
    bg = np.full(len(data), NAN)
    if show_high_low_bg:
        bg = np.where(k > upper, 0.0, np.where(k < lower, 1.0, NAN))
    if show_strict_bg:
        bg = np.where(strict_buy | strict_sell, np.where(strict_buy, 1.0, 0.0), bg)
    if show_any_bg:
        bg = np.where(any_buy | any_sell, np.where(any_buy, 1.0, 0.0), bg)
    n = len(data)
    return _frame(
        data,
        {
            "stochK": k,
            "stochD": d,
            "stochK2": k2 if show_second else np.full(n, NAN),
            "stochD2": d2 if show_second else np.full(n, NAN),
            "upper": np.full(n, float(upper)),
            "lower": np.full(n, float(lower)),
            "middle": np.full(n, 50.0 if show_mid else NAN),
            "strictBuy": _flag(strict_buy & show_strict_letters),
            "strictSell": _flag(strict_sell & show_strict_letters),
            "anyBuy": _flag(any_buy & show_any_letters),
            "anySell": _flag(any_sell & show_any_letters),
            "background": bg,
        },
    )


def gainzalgo(
    df: pd.DataFrame,
    candle_stability: float = 0.5,
    rsi_index: float = 50,
    candle_delta_len: int = 5,
    disable_repeating: bool = False,
) -> pd.DataFrame:
    # Chartix resets its "last signal" every bar, so Disable Repeating Signals never removes anything.
    data, o, h, l, c = _ohlc(df)
    op, cl = pj.nv(o), pj.nv(c)
    rsi = pj.rsi_from(cl, 14)
    rng = pj.tr(h, l, c, True)
    with np.errstate(all="ignore"):
        stable = np.abs(c - o) / rng > candle_stability
    prev_c, prev_o = pj.get(cl, 1), pj.get(op, 1)
    back = pj.get(cl, int(candle_delta_len))
    bull = (prev_c < prev_o) & (c > o) & (c > prev_o)
    buy = bull & stable & (rsi < rsi_index) & (c < back)
    bear = (prev_c > prev_o) & (c < o) & (c < prev_o)
    sell = bear & stable & (rsi > 100 - rsi_index) & (c > back)
    return _frame(data, {"plot_0": np.where(buy, l, NAN), "plot_1": np.where(sell, h, NAN)})


def matrix_series(
    df: pd.DataFrame,
    smoother: int = 5,
    sup_res_period: int = 50,
    sup_res_percentage: float = 100,
    price_period: int = 16,
    overbought: float = 200,
    oversold: float = -200,
    show_obos: bool = False,
    dynamic_zones: bool = True,
) -> pd.DataFrame:
    data, o, h, l, c = _ohlc(df)
    p = int(smoother)
    ys = (h + l + c * 2) / 4
    m = pj.nv(ys)
    with np.errstate(all="ignore"):
        g = (ys - pj.ema(m, p)) * 200 / pj.stdev(m, p)
    up = pj.ema(pj.nv(pj.ema(pj.nv(g), p)), p)
    up_s = pj.nv(up)
    down = pj.ema(up_s, p)
    down_s = pj.nv(down)
    lo = np.where(up < down, up, down)
    hi = np.where(up < down, down, up)
    color = np.where(lo > hi, 0.0, np.where(up > down, 1.0, 0.0))
    cl = pj.nv(c)
    with np.errstate(all="ignore"):
        cci = (c - pj.sma(cl, price_period)) / (0.015 * np.abs(pj.dev(cl, price_period)))
    cci_s = pj.nv(cci)
    top = pj.highest(cci_s, sup_res_period)
    bot = pj.lowest(cci_s, sup_res_period)
    span = (top - bot) * (sup_res_percentage / 100)
    sup = bot + span
    res = top - span
    up_last = pj.highest(up_s, 1)
    down_last = pj.highest(down_s, 1)
    ob_mark = np.where(
        (up > overbought) & (up > down), up_last + 20, np.where((up > overbought) & (up < down), down_last + 20, NAN)
    )
    os_mark = np.where(
        (down < oversold) & (up > down),
        pj.lowest(down_s, 1) - 20,
        np.where((down < oversold) & (up < down), pj.lowest(up_s, 1) - 20, NAN),
    )
    n = len(data)
    return _frame(
        data,
        {
            "candle_open": lo,
            "candle_high": lo,
            "candle_low": hi,
            "candle_close": hi,
            "candle_color": color,
            "plot_00": sup if dynamic_zones else np.full(n, NAN),
            "plot_01": res if dynamic_zones else np.full(n, NAN),
            "plot_02": ob_mark,
            "plot_03": os_mark,
            "plot_04": np.full(n, float(overbought) if show_obos else NAN),
            "plot_05": np.full(n, float(oversold) if show_obos else NAN),
            "ms_up": up,
            "ms_down": down,
        },
    )


def tcg_ai_tools(
    df: pd.DataFrame,
    price: str = "close",
    bb_len: int = 20,
    bb_mult: float = 2,
    overbought: float = 70,
    oversold: float = 30,
    length: int = 14,
) -> pd.DataFrame:
    data, o, h, l, c = _ohlc(df)
    cl = pj.nv(c)
    trend_color = np.where(pj.sma(cl, 20) > pj.sma(cl, 10), 0.0, 1.0)
    src = pj.source(o, h, l, c, price)
    src_s = pj.nv(src)
    basis = pj.sma(src_s, bb_len)
    width = bb_mult * pj.stdev(src_s, bb_len)
    upper = basis + width
    lower = basis - width
    prev_src = pj.get(src_s, 1)
    cross_upper = (src >= upper) & (prev_src < pj.get(upper, 1))
    cross_lower = (src >= lower) & (prev_src < pj.get(lower, 1))
    rsi = pj.rsi_from(cl, int(length), unlimited=True)
    n = len(data)
    return _frame(
        data,
        {
            "plot_00": np.zeros(n),
            "plot_00c": trend_color,
            "plot_01": np.where(cross_upper, 0.0, NAN),
            "plot_02": np.where(cross_lower, 0.0, NAN),
            "plot_03": np.where(rsi >= overbought, 0.0, NAN),
            "plot_04": np.where(rsi <= oversold, 0.0, NAN),
            "rsi": rsi,
            "bb_upper": upper,
            "bb_lower": lower,
        },
    )


def ut_bot(df: pd.DataFrame, key_value: float = 1, atr_period: int = 10, heikin_ashi: bool = False) -> pd.DataFrame:
    data, o, h, l, c = _ohlc(df)
    # "Heikin Ashi" in the Chartix script only swaps the source to ohlc4 of the real candle.
    src = (o + h + l + c) / 4 if heikin_ashi else c
    src_s = pj.nv(src)
    prev_src = pj.get(src_s, 1).tolist()
    loss = (key_value * pj.atr(h, l, c, int(atr_period))).tolist()
    px = src.tolist()
    trail = [NAN] * len(px)
    t = NAN
    for i in range(len(px)):
        base = 0.0 if (t != t or t == 0) else t
        p, u, m = px[i], prev_src[i], loss[i]
        if p > base and u > base:
            f = float(np.maximum(base, p - m))
        elif p < base and u < base:
            f = float(np.minimum(base, p + m))
        elif p > base:
            f = p - m
        else:
            f = p + m
        trail[i] = f
        t = f
    trail_a = np.asarray(trail, dtype=float)
    z = pj.nv(trail_a)
    a = pj.nv(pj.ema(src_s, 1))
    above = pj.cross(a, z) & (a > z)
    below = pj.cross(z, a) & (z > a)
    buy = (src > trail_a) & above
    sell = (src < trail_a) & below
    bar = np.where(src > trail_a, 0.0, np.where(src < trail_a, 1.0, NAN))
    return _frame(data, {"plot_0": bar, "plot_1": _flag(buy), "plot_2": _flag(sell), "trail": trail_a})


def vtx_oscillator(df: pd.DataFrame, length: int = 14, source: str = "Close") -> pd.DataFrame:
    data, o, h, l, c = _ohlc(df)
    lo = pj.lowest(pj.nv(l), length)
    hi = pj.highest(pj.nv(h), length)
    pick = {"Open": o, "High": h, "Low": l}.get(str(source), c)
    with np.errstate(all="ignore"):
        value = (pick - lo) / (hi - lo) * 100
    return _frame(
        data,
        {
            "plot_00": np.where(pj.cross(value, 20.0), value, NAN),
            "plot_01": np.where(pj.cross(80.0, value), value, NAN),
            "plot_02": value,
        },
    )
