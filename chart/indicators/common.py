# -*- coding: utf-8 -*-
"""Common helpers for indicator modules."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd


def ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "time" not in out.columns:
        raise ValueError("DataFrame must have a 'time' column")
    out["time"] = pd.to_datetime(out["time"], errors="coerce").astype("datetime64[ns]")
    for col in ("open", "high", "low", "close"):
        if col not in out.columns:
            raise ValueError(f"Missing column: {col}")
        out[col] = pd.to_numeric(out[col], errors="coerce")
    if "volume" not in out.columns:
        out["volume"] = 0.0
    else:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
    return out.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


def select_source(df: pd.DataFrame, source: str = "close") -> pd.Series:
    src = (source or "close").lower()
    if src == "open":
        return df["open"]
    if src == "high":
        return df["high"]
    if src == "low":
        return df["low"]
    if src == "hl2":
        return (df["high"] + df["low"]) / 2.0
    if src == "hlc3":
        return (df["high"] + df["low"] + df["close"]) / 3.0
    if src == "ohlc4":
        return (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    return df["close"]


def line_frame(time: pd.Series, values: pd.Series, name: str) -> pd.DataFrame:
    frame = pd.DataFrame({"time": time, name: values})
    return frame.dropna().reset_index(drop=True)


def empty_result() -> Dict[str, Any]:
    return {"lines": [], "histograms": [], "markers": [], "hline": []}


def plot_style(
    cfg: Dict[str, Any],
    prefix: str,
    *,
    color: str,
    width: int = 2,
    plot_type: str = "line",
    linestyle: str = "solid",
) -> Dict[str, Any]:
    """Style keys written by the settings dialog: show is handled by the caller."""
    cfg = cfg or {}
    try:
        w = int(cfg.get(f"{prefix}_linewidth", width) or width)
    except (TypeError, ValueError):
        w = int(width)
    return {
        "color": cfg.get(f"{prefix}_color", color),
        "width": max(1, w),
        "plot_type": str(cfg.get(f"{prefix}_plottype", plot_type) or plot_type),
        "linestyle": str(cfg.get(f"{prefix}_linestyle", linestyle) or linestyle),
    }


def color_alpha(color: str, alpha: float = 0.18) -> str:
    s = str(color or "#787b86").strip()
    if s.startswith("rgba") or s.startswith("rgb"):
        return s
    if s.startswith("#") and len(s) >= 7:
        try:
            r = int(s[1:3], 16)
            g = int(s[3:5], 16)
            b = int(s[5:7], 16)
            return f"rgba({r},{g},{b},{alpha})"
        except ValueError:
            return s
    return s


_RES_RULE = {
    "1": "1min",
    "2": "2min",
    "3": "3min",
    "5": "5min",
    "10": "10min",
    "15": "15min",
    "30": "30min",
    "60": "60min",
    "120": "120min",
    "240": "240min",
    "D": "1D",
    # TSE weeks run Saturday→Wednesday; Chartix weekly bars open on Saturday.
    "W": "W-FRI",
    # Chartix monthly bars follow Solar Hijri months (1 Mehr ≈ 23 Sep).
    "M": "JMONTH",
    "1min": "1min",
    "2min": "2min",
    "3min": "3min",
    "5min": "5min",
    "10min": "10min",
    "15min": "15min",
    "30min": "30min",
    "1h": "60min",
    "2h": "120min",
    "3h": "180min",
    "4h": "240min",
    "1d": "1D",
    "1w": "W-FRI",
    "1mon": "JMONTH",
}


def gregorian_to_jalali(gy: int, gm: int, gd: int):
    g_d_m = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def _resample_jalali_month(x: pd.DataFrame, agg: Dict[str, str]) -> pd.DataFrame:
    """Group by Solar Hijri month; label each month just after its last bar.

    Same visibility as the pandas right-labelled bins: a month's value reaches
    the chart from the first bar after that month closes.
    """
    t = x.index
    keys = [gregorian_to_jalali(d.year, d.month, d.day)[:2] for d in t]
    month_id = pd.Series([y * 12 + m for y, m in keys], index=t)
    y = x.groupby(month_id.to_numpy()).agg(agg)
    last_t = pd.Series(t, index=t).groupby(month_id.to_numpy()).max()
    y.index = (last_t + pd.Timedelta(nanoseconds=1)).to_numpy()
    y.index.name = "time"
    return y


def resolution_rule(res: str) -> str:
    key = str(res or "D").strip()
    return _RES_RULE.get(key) or _RES_RULE.get(key.lower()) or "1D"


def resample_ohlcv(df: pd.DataFrame, resolution: str) -> pd.DataFrame:
    """Aggregate chart bars onto another timeframe. Finer TFs cannot be invented."""
    if df is None or df.empty:
        return df
    rule = resolution_rule(resolution)
    x = df.copy()
    x["time"] = pd.to_datetime(x["time"], errors="coerce")
    x = x.dropna(subset=["time"]).set_index("time").sort_index()
    agg: Dict[str, str] = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in x.columns:
        agg["volume"] = "sum"
    if rule == "JMONTH":
        y = _resample_jalali_month(x, agg)
    else:
        y = x.resample(rule, label="right", closed="right").agg(agg)
    y = y.dropna(subset=["open", "high", "low", "close"])
    if y.empty:
        return df
    y = y.reset_index()
    y["time"] = pd.to_datetime(y["time"], errors="coerce").astype("datetime64[ns]")
    return y


def project_to_times(src_time: pd.Series, src_values: pd.Series, target_time: pd.Series) -> pd.Series:
    """Step-hold a higher-timeframe series onto each chart bar."""
    right = pd.DataFrame(
        {
            "time": pd.to_datetime(src_time, errors="coerce").astype("datetime64[ns]"),
            "v": pd.to_numeric(src_values, errors="coerce"),
        }
    ).dropna(subset=["time"])
    right = right.sort_values("time")
    left = pd.DataFrame({"time": pd.to_datetime(target_time, errors="coerce").astype("datetime64[ns]")})
    if right.empty:
        return pd.Series(float("nan"), index=getattr(target_time, "index", None))
    merged = pd.merge_asof(left, right, on="time", direction="backward")
    return merged["v"]


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    """TradingView-compatible RSI (Wilder / RMA)."""
    s = pd.to_numeric(series, errors="coerce")
    length = max(1, int(length))
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # RMA = EWM with alpha=1/length, adjust=False (Wilder)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    out = 100.0 - (100.0 / (1.0 + rs))
    return pd.to_numeric(out, errors="coerce")


def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(length, min_periods=length).mean()


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def bollinger(series: pd.Series, length: int = 20, mult: float = 2.0):
    mid = sma(series, length)
    std = series.rolling(length, min_periods=length).std()
    upper = mid + mult * std
    lower = mid - mult * std
    return mid, upper, lower
