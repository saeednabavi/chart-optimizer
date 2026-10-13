# -*- coding: utf-8 -*-
"""Search space of every indicator: calculation inputs (searched) vs display-only inputs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from chart import indicator_settings as iset
from chart.data_loader import available_timeframes
from chart.indicators.chartix_exact import resolution_to_tf


@dataclass
class Param:
    key: str
    label: str
    kind: str  # "int" | "float" | "choice" | "bool"
    lo: float = 0.0
    hi: float = 0.0
    step: float = 1.0
    choices: Sequence[Any] = ()
    # Keys that are not chart settings (rule levels of the client's signal definition)
    rule_only: bool = False

    def values(self) -> List[Any]:
        """Every value the search may try, in order."""
        if self.kind == "bool":
            return [False, True]
        if self.kind == "choice":
            return list(self.choices)
        n = int(round((self.hi - self.lo) / self.step))
        if self.kind == "int":
            return [int(round(self.lo + i * self.step)) for i in range(n + 1)]
        return [round(self.lo + i * self.step, 6) for i in range(n + 1)]

    def coarse(self, k: int = 3) -> List[Any]:
        vals = self.values()
        if len(vals) <= k:
            return vals
        idx = sorted({round(i * (len(vals) - 1) / (k - 1)) for i in range(k)})
        return [vals[i] for i in idx]

    def neighbours(self, value: Any) -> List[Any]:
        vals = self.values()
        try:
            i = vals.index(value)
        except ValueError:
            i = min(range(len(vals)), key=lambda j: _dist(vals[j], value))
        return [vals[j] for j in (i - 1, i + 1) if 0 <= j < len(vals)]


def _dist(a: Any, b: Any) -> float:
    try:
        return abs(float(a) - float(b))
    except (TypeError, ValueError):
        return 0.0 if a == b else 1.0


@dataclass
class IndicatorSpace:
    key: str
    label: str
    params: List[Param]
    # Inputs-tab fields that only change what is drawn (never the signal)
    display_inputs: List[str] = field(default_factory=list)
    # Rule constants used when they are not searched
    fixed: Dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def defaults(self) -> Dict[str, Any]:
        base = iset.default_all().get(self.key, {})
        out = {}
        for p in self.params:
            if p.key in self.fixed:
                out[p.key] = self.fixed[p.key]
            elif p.key in base:
                out[p.key] = _snap(p, base[p.key])
            else:
                out[p.key] = p.values()[0]
        return out

    def size(self, keys: Optional[Sequence[str]] = None) -> int:
        ps = [p for p in self.params if keys is None or p.key in keys]
        return math.prod(len(p.values()) for p in ps) if ps else 1

    def param(self, key: str) -> Param:
        return next(p for p in self.params if p.key == key)


def _snap(p: Param, v: Any) -> Any:
    if p.kind == "bool":
        return bool(v)
    if p.kind == "choice":
        return v if v in p.choices else p.choices[0]
    vals = p.values()
    return min(vals, key=lambda x: abs(x - float(v)))


INDICATOR_LABELS = {
    "vtx": "VTX Oscillator",
    "tcg": "TCG AI Tools",
    "eagles": "Eagles Nest",
    "utbot": "UT Bot Alerts",
    "gainz": "GainzAlgo Pro",
    "aieng": "EngulfingCandle (AI Engulfing)",
    "matrix": "Matrix Series (MS)",
    "bvb": "Bulls v Bears (BvB)",
}

_TF_ORDER = ["1min", "2min", "3min", "5min", "10min", "15min", "30min", "45min", "1h", "2h", "3h", "4h", "1d", "1w", "1mon"]
_RESOLUTIONS = ["60", "240", "D", "W", "M"]


def higher_resolutions(ticker: str, tf: str, adj: str) -> List[str]:
    """Eagles 'Use Different Timeframe' choices that are above the chart timeframe and exist as CSV."""
    have = set(available_timeframes(ticker, adj))
    cur = _TF_ORDER.index(tf) if tf in _TF_ORDER else -1
    out = []
    for res in _RESOLUTIONS:
        other = resolution_to_tf(res)
        if other in have and _TF_ORDER.index(other) > cur:
            out.append(res)
    return out


def build_space(ind: str, ticker: str, tf: str, adj: str, optimize_vtx_levels: bool = False) -> IndicatorSpace:
    if ind == "vtx":
        params = [
            Param("length", "Length", "int", 2, 100),
            Param("source", "Source", "choice", choices=("Close", "Open", "High", "Low")),
            Param("buy_level", "Buy level (break up)", "int", 5, 50, rule_only=True),
            Param("sell_level", "Sell level (break down)", "int", 50, 95, rule_only=True),
        ]
        fixed = {} if optimize_vtx_levels else {"buy_level": 30, "sell_level": 80}
        return IndicatorSpace(ind, INDICATOR_LABELS[ind], params, [], fixed,
                              "Buy: VTX line breaks the buy level upward. Sell: breaks the sell level downward.")
    if ind == "tcg":
        params = [
            Param("length", "Length (RSI)", "int", 2, 50),
            Param("overbought", "Overbought", "int", 50, 95),
            Param("oversold", "Oversold", "int", 5, 50),
            Param("price", "Price", "choice", choices=tuple(iset.SOURCE_CHOICES)),
            Param("bb_len", "Bollinger length", "int", 5, 60),
            Param("bb_mult", "Bollinger Multiplier", "float", 1.0, 4.0, 0.25),
        ]
        return IndicatorSpace(ind, INDICATOR_LABELS[ind], params, [], {},
                              "Sell: column is color 0, then the first-color box appears. "
                              "Buy: column is color 1, then the second-color box appears.")
    if ind == "eagles":
        params = [
            Param("stoch_len", "Length for Main Stochastic", "int", 2, 60),
            Param("smooth_k", "SmoothK", "int", 1, 12),
            Param("smooth_d", "SmoothD", "int", 1, 12),
            Param("upper_line", "Upper Line Value", "int", 50, 90),
            Param("lower_line", "Lower Line Value", "int", 10, 50),
            Param("highlight_above_below", "Highlight Above/Below High/Low Lines", "bool"),
            Param("highlight_strict", "Highlight Strict Crosses", "bool"),
            Param("highlight_any_cross", "Highlight Any Cross", "bool"),
        ]
        higher = higher_resolutions(ticker, tf, adj)
        if higher:
            params.append(Param("use_chart_resolution", "Use Current Chart Resolution", "bool"))
            params.append(Param("alt_tf", "Use Different Timeframe", "choice", choices=tuple(higher)))
        display = ["show_mid_line", "show_strict_letters", "show_any_letters", "show_2nd_stoch",
                   "second_tf", "use_2nd_on_current", "stoch_len2", "smooth_k2", "smooth_d2"]
        fixed = {} if higher else {"use_chart_resolution": True}
        return IndicatorSpace(ind, INDICATOR_LABELS[ind], params, display, fixed,
                              "Sell: gold background highlight appears. Buy: purple background highlight appears.")
    if ind == "utbot":
        params = [
            Param("key_value", "Key Value", "float", 0.3, 6.0, 0.1),
            Param("atr_period", "ATR Period", "int", 1, 60),
            Param("heikin_ashi", "Signals from Heikin Ashi Candles", "bool"),
        ]
        return IndicatorSpace(ind, INDICATOR_LABELS[ind], params, [], {}, "Buy / Sell labels of UT Bot.")
    if ind == "gainz":
        params = [
            Param("candle_stability", "Candle Stability Index", "float", 0.0, 1.0, 0.05),
            Param("rsi_index", "RSI Index", "int", 0, 100),
            Param("candle_delta_len", "Candle Delta Length", "int", 3, 40),
            Param("disable_repeating", "Disable Repeating Signals", "bool"),
        ]
        return IndicatorSpace(ind, INDICATOR_LABELS[ind], params, [], {}, "BUY / SELL labels of GainzAlgo.")
    if ind == "aieng":
        params = [
            Param("rsi_source", "rsi Source", "choice", choices=tuple(iset.SOURCE_CHOICES)),
            Param("rsi_len", "rsi Length", "int", 2, 50),
            Param("ob", "rsi Overbought Level", "int", 50, 95),
            Param("os_", "rsi Oversold Level", "int", 5, 50),
        ]
        return IndicatorSpace(ind, INDICATOR_LABELS[ind], params, [], {}, "Bullish (buy MIT) / Bearish (sell MIT).")
    if ind == "matrix":
        params = [
            Param("smoother", "Smoother", "int", 1, 30),
            Param("sup_res_period", "SupResPeriod", "int", 5, 150, 5),
            Param("sup_res_percentage", "SupResPercentage", "int", 10, 100, 5),
            Param("price_period", "PricePeriod", "int", 2, 60),
            Param("overbought", "Overbought", "int", 0, 400, 10),
            Param("oversold", "Oversold", "int", -400, 0, 10),
        ]
        return IndicatorSpace(ind, INDICATOR_LABELS[ind], params, ["show_obos", "dynamic_zones"], {},
                              "Sell: overbought dot appears. Buy: oversold dot appears.")
    if ind == "bvb":
        params = [
            Param("period", "BvB Period", "int", 2, 60),
            Param("bars_back", "Normalized bars back", "int", 10, 400, 5),
            Param("line_height", "Line Height", "int", 10, 150, 2),
        ]
        return IndicatorSpace(ind, INDICATOR_LABELS[ind], params, [], {},
                              "Sell: yellow dot above +Line Height appears. Buy: dot below -Line Height appears.")
    raise KeyError(ind)


def style_labels(ind: str) -> List[str]:
    """Labels of the Style tab rows (all display-only)."""
    out = []
    for f in iset.SCHEMAS.get(ind, {}).get("styles", []):
        lab = f.get("label")
        if lab and lab not in out:
            out.append(str(lab))
    return out
