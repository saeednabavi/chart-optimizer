# -*- coding: utf-8 -*-
"""Buy / sell signal bars of every indicator for one set of inputs.

Every function returns a boolean array (one entry per bar of ``df``): True where the signal fires.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from chart.data_loader import load_ohlcv
from chart.indicators import chartix_exact as cx

BUY, SELL = "buy", "sell"


class Context:
    """Chart timeframe + cached loader for the other-timeframe bars (Eagles Nest)."""

    def __init__(self, ticker: str, tf: str, adj: str):
        self.ticker, self.tf, self.adj = ticker, tf, adj
        self._cache: Dict[str, Optional[pd.DataFrame]] = {}

    def htf_loader(self, res: str) -> Optional[pd.DataFrame]:
        if res not in self._cache:
            tf = cx.resolution_to_tf(res)
            try:
                self._cache[res] = load_ohlcv(self.ticker, tf, self.adj) if tf else None
            except (FileNotFoundError, ValueError):
                self._cache[res] = None
        return self._cache[res]


def _onset(flag: np.ndarray) -> np.ndarray:
    """First bar of every run of True."""
    flag = np.asarray(flag, dtype=bool)
    prev = np.concatenate(([False], flag[:-1]))
    return flag & ~prev


def _vtx(df, p, side, ctx):
    value = cx.vtx_oscillator(df, int(p["length"]), str(p["source"]))["plot_02"].to_numpy()
    prev = np.concatenate(([np.nan], value[:-1]))
    with np.errstate(invalid="ignore"):
        if side == BUY:
            lvl = float(p.get("buy_level", 30))
            return (prev < lvl) & (value >= lvl)
        lvl = float(p.get("sell_level", 80))
        return (prev > lvl) & (value <= lvl)


def _tcg(df, p, side, ctx):
    plots = cx.tcg_ai_tools(df, str(p["price"]), int(p["bb_len"]), float(p["bb_mult"]),
                            float(p["overbought"]), float(p["oversold"]), int(p["length"]))
    column = plots["plot_00c"].to_numpy()
    if side == SELL:
        box = plots["plot_03"].notna().to_numpy()
        return _onset(box) & (column == 0)
    box = plots["plot_04"].notna().to_numpy()
    return _onset(box) & (column == 1)


def _htf_groups(df: pd.DataFrame, res: str, ctx: Context) -> np.ndarray:
    """Higher-timeframe period number of every chart bar."""
    times = pd.to_datetime(df["time"])
    if res in ("D", "1D"):
        day = times.dt.normalize()
        return pd.factorize(day, sort=True)[0]
    other = ctx.htf_loader(res)
    if other is not None and len(other):
        starts = pd.DataFrame({"start": pd.to_datetime(other["time"]).to_numpy(), "g": np.arange(len(other))})
        merged = pd.merge_asof(pd.DataFrame({"time": times.to_numpy()}), starts.sort_values("start"),
                               left_on="time", right_on="start", direction="backward")
        g = merged["g"].fillna(-1).to_numpy(dtype=np.int64)
        return pd.factorize(g, sort=True)[0]
    freq = {"W": "W-FRI", "1W": "W-FRI", "M": "M", "1M": "M"}.get(res, "D")
    return pd.factorize(times.dt.to_period(freq), sort=True)[0]


def _stoch_realtime_htf(df: pd.DataFrame, res: str, ctx: Context, length: int, smooth_k: int, smooth_d: int):
    """Higher-timeframe Stochastic as a live chart showed it on each chart bar (no look-ahead).

    Completed higher-timeframe bars are built from the chart bars of their period; the bar in progress
    uses only the chart bars up to the current one (running high / low, current close).
    """
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    g = _htf_groups(df, res, ctx)
    n_g = int(g.max()) + 1 if len(g) else 0
    s = pd.Series
    run_hi = s(h).groupby(g).cummax().to_numpy()
    run_lo = s(l).groupby(g).cummin().to_numpy()
    last = np.r_[g[1:] != g[:-1], True]
    H = np.full(n_g, np.nan)
    L = np.full(n_g, np.nan)
    C = np.full(n_g, np.nan)
    H[g[last]], L[g[last]], C[g[last]] = run_hi[last], run_lo[last], c[last]

    # Completed-bar windows that end one bar before the current period
    def prev_window(x: np.ndarray, n: int, fn) -> np.ndarray:
        out = np.full(n_g, np.nan)
        if n <= 1:
            return out
        vals = s(x).rolling(n - 1, min_periods=n - 1)
        r = (vals.max() if fn == "max" else vals.min()).to_numpy()
        out[1:] = r[:-1]
        return out

    hh_prev = prev_window(H, length, "max")[g]
    ll_prev = prev_window(L, length, "min")[g]
    hi = run_hi if length <= 1 else np.fmax(hh_prev, run_hi)
    lo = run_lo if length <= 1 else np.fmin(ll_prev, run_lo)
    if length > 1:
        enough = g >= length - 1
        hi = np.where(enough, hi, np.nan)
        lo = np.where(enough, lo, np.nan)
    with np.errstate(all="ignore"):
        raw = np.where(hi == lo, 0.0, (c - lo) / (hi - lo) * 100)

    # Completed raw / K per period (value on the period's last chart bar)
    def smooth(cur: np.ndarray, n: int) -> Tuple[np.ndarray, np.ndarray]:
        full = np.full(n_g, np.nan)
        full[g[last]] = cur[last]
        if n <= 1:
            return cur, full
        prev_sum = s(full).rolling(n - 1, min_periods=n - 1).sum().to_numpy()
        shifted = np.full(n_g, np.nan)
        shifted[1:] = prev_sum[:-1]
        live = (shifted[g] + cur) / n
        done = np.full(n_g, np.nan)
        done[g[last]] = live[last]
        return live, done

    k, _ = smooth(raw, smooth_k)
    d, _ = smooth(k, smooth_d)
    return k, d


def _eagles(df, p, side, ctx):
    if ctx is not None and not bool(p.get("use_chart_resolution", True)):
        k, d = _stoch_realtime_htf(df, str(p.get("alt_tf", "D")), ctx, int(p["stoch_len"]),
                                   int(p["smooth_k"]), int(p["smooth_d"]))
        upper, lower = float(p["upper_line"]), float(p["lower_line"])
        pk = np.r_[np.nan, k[:-1]]
        pd_ = np.r_[np.nan, d[:-1]]
        with np.errstate(invalid="ignore"):
            strict_buy = (pk < pd_) & (pk < lower) & (k > d)
            strict_sell = (pk > pd_) & (pk > upper) & (k < d)
            any_buy = (pk < pd_) & (k > d)
            any_sell = (pk > pd_) & (k < d)
            bg = np.full(len(df), np.nan)
            if p["highlight_above_below"]:
                bg = np.where(k > upper, 0.0, np.where(k < lower, 1.0, np.nan))
        if p["highlight_strict"]:
            bg = np.where(strict_buy | strict_sell, np.where(strict_buy, 1.0, 0.0), bg)
        if p["highlight_any_cross"]:
            bg = np.where(any_buy | any_sell, np.where(any_buy, 1.0, 0.0), bg)
        return _onset(bg == (1.0 if side == BUY else 0.0))
    plots = cx.eagles_nest(
        df,
        length=int(p["stoch_len"]),
        smooth_k=int(p["smooth_k"]),
        smooth_d=int(p["smooth_d"]),
        upper=float(p["upper_line"]),
        lower=float(p["lower_line"]),
        show_high_low_bg=bool(p["highlight_above_below"]),
        show_strict_bg=bool(p["highlight_strict"]),
        show_any_bg=bool(p["highlight_any_cross"]),
        use_current_resolution=bool(p.get("use_chart_resolution", True)),
        resolution=str(p.get("alt_tf", "60")),
        chart_resolution=ctx.tf if ctx else None,
        htf_loader=ctx.htf_loader if ctx else None,
    )
    bg = plots["background"].to_numpy()
    # gold (0) = tops / sell, purple (1) = bottoms / buy
    return _onset(bg == (1.0 if side == BUY else 0.0))


def _utbot(df, p, side, ctx):
    plots = cx.ut_bot(df, float(p["key_value"]), int(p["atr_period"]), bool(p["heikin_ashi"]))
    return (plots["plot_1" if side == BUY else "plot_2"] == 1).to_numpy()


def _gainz(df, p, side, ctx):
    plots = cx.gainzalgo(df, float(p["candle_stability"]), float(p["rsi_index"]),
                         int(p["candle_delta_len"]), bool(p["disable_repeating"]))
    return plots["plot_0" if side == BUY else "plot_1"].notna().to_numpy()


def _aieng(df, p, side, ctx):
    plots = cx.ai_engulfing(df, str(p["rsi_source"]), int(p["rsi_len"]), float(p["ob"]), float(p["os_"]))
    return (plots["bullish" if side == BUY else "bearish"] == 1).to_numpy()


def _matrix(df, p, side, ctx):
    plots = cx.matrix_series(df, int(p["smoother"]), int(p["sup_res_period"]), float(p["sup_res_percentage"]),
                             int(p["price_period"]), float(p["overbought"]), float(p["oversold"]), False, True)
    return _onset(plots["plot_03" if side == BUY else "plot_02"].notna().to_numpy())


def _bvb(df, p, side, ctx):
    plots = cx.bulls_v_bears(df, int(p["period"]), int(p["bars_back"]), float(p["line_height"]))
    g = plots["plot_00"].to_numpy()
    lh = float(p["line_height"])
    with np.errstate(invalid="ignore"):
        return _onset(g < -lh if side == BUY else g > lh)


_FUNCS: Dict[str, Callable[..., np.ndarray]] = {
    "vtx": _vtx,
    "tcg": _tcg,
    "eagles": _eagles,
    "utbot": _utbot,
    "gainz": _gainz,
    "aieng": _aieng,
    "matrix": _matrix,
    "bvb": _bvb,
}


def compute_signal(ind: str, df: pd.DataFrame, params: Dict[str, Any], side: str,
                   ctx: Optional[Context] = None) -> np.ndarray:
    out = _FUNCS[ind](df, params, side, ctx)
    return np.nan_to_num(np.asarray(out, dtype=float), nan=0.0).astype(bool)
