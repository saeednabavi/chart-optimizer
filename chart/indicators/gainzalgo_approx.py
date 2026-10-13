# -*- coding: utf-8 -*-
"""GainzAlgo Pro — exact Chartix port (the module name is kept for imports/settings)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from . import chartix_exact as cx
from chart.indicator_settings import marker_position, marker_shape

from .common import empty_result, ensure_ohlcv


def chartix_plots(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Raw Chartix plot values (one column per plot id)."""
    cfg = cfg or {}
    return cx.gainzalgo(
        df,
        float(cfg.get("candle_stability", 0.5)),
        float(cfg.get("rsi_index", 50.0)),
        int(cfg.get("candle_delta_len", 5)),
        bool(cfg.get("disable_repeating", False)),
    )


def compute(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    show_buy = bool(cfg.get("show_plot_0", cfg.get("show_buy", True)))
    show_sell = bool(cfg.get("show_plot_1", cfg.get("show_sell", True)))
    buy_color = cfg.get("plot_0_color", cfg.get("buy_color", "#1dff28"))
    sell_color = cfg.get("plot_1_color", cfg.get("sell_color", "#ff0000"))

    data = ensure_ohlcv(df)
    result = empty_result()
    if len(data) < 3:
        return result

    out = chartix_plots(data, cfg)
    buy_pos = marker_position(cfg.get("plot_0_location"), "absolute")
    sell_pos = marker_position(cfg.get("plot_1_location"), "absolute")
    buy_shape = marker_shape(cfg.get("plot_0_plottype"), "arrowUp")
    sell_shape = marker_shape(cfg.get("plot_1_plottype"), "arrowDown")
    markers = []
    for t, buy, sell in zip(out["time"], out["plot_0"], out["plot_1"]):
        if show_buy and buy == buy:
            markers.append({"time": t, "position": buy_pos, "shape": buy_shape, "color": buy_color, "text": "BUY"})
        if show_sell and sell == sell:
            markers.append({"time": t, "position": sell_pos, "shape": sell_shape, "color": sell_color, "text": "SELL"})
    result["markers"] = markers
    result["title"] = "GainzAlgo Pro"
    return result
