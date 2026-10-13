# -*- coding: utf-8 -*-
"""UT Bot Alerts — exact Chartix port (Bar Color + BUY/SELL)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import chartix_exact as cx
from chart.indicator_settings import marker_position, marker_shape

from .common import empty_result, ensure_ohlcv, line_frame


def chartix_plots(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Raw Chartix plot values (one column per plot id)."""
    cfg = cfg or {}
    return cx.ut_bot(
        df,
        float(cfg.get("key_value", cfg.get("a", 1.0))),
        int(cfg.get("atr_period", cfg.get("c", 10))),
        bool(cfg.get("heikin_ashi", cfg.get("h", False))),
    )


def compute(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    atr_period = int(cfg.get("atr_period", cfg.get("c", 10)))
    show_trail = bool(cfg.get("show_trail", False))
    show_buy = bool(cfg.get("show_plot_1", cfg.get("show_buy", True)))
    show_sell = bool(cfg.get("show_plot_2", cfg.get("show_sell", True)))
    trail_color = cfg.get("trail_color", "#29b6f6")
    line_width = int(cfg.get("line_width", 1))
    buy_color = cfg.get("plot_1_color", cfg.get("buy_color", "#4CAF50"))
    sell_color = cfg.get("plot_2_color", cfg.get("sell_color", "#FF5252"))
    show_bar = bool(cfg.get("show_bar_color", True))
    bar_up = cfg.get("bar_up", "#008000")
    bar_down = cfg.get("bar_down", "#ff0000")

    data = ensure_ohlcv(df)
    result = empty_result()
    if len(data) < atr_period + 2:
        return result

    plots = chartix_plots(data, cfg)

    if show_trail:
        result["lines"].append(
            {
                "name": "UT_Trail",
                "pane": "main",
                "data": line_frame(data["time"], plots["trail"], "UT_Trail"),
                "color": trail_color,
                "width": line_width,
            }
        )

    show_bar_up = bool(cfg.get("show_bar_up", True))
    show_bar_down = bool(cfg.get("show_bar_down", True))
    if show_bar and (show_bar_up or show_bar_down):
        state = plots["plot_0"].to_numpy()
        # Bars without a Chartix color keep the chart's own candle colors.
        natural = np.where(data["close"] >= data["open"], "#26a69a", "#ef5350")
        bar_col = np.array(natural, copy=True)
        if show_bar_up:
            bar_col = np.where(state == 0, bar_up, bar_col)
        if show_bar_down:
            bar_col = np.where(state == 1, bar_down, bar_col)
        result["bar_colors"] = {
            "enabled": True,
            "data": pd.DataFrame({"time": data["time"], "color": bar_col}),
        }

    buy_pos = marker_position(cfg.get("plot_1_location"), "below")
    sell_pos = marker_position(cfg.get("plot_2_location"), "above")
    buy_shape = marker_shape(cfg.get("plot_1_plottype"), "arrowUp")
    sell_shape = marker_shape(cfg.get("plot_2_plottype"), "arrowDown")
    markers = []
    for t, buy, sell in zip(plots["time"], plots["plot_1"], plots["plot_2"]):
        if show_buy and buy == 1:
            markers.append({"time": t, "position": buy_pos, "shape": buy_shape, "color": buy_color, "text": "Buy"})
        if show_sell and sell == 1:
            markers.append({"time": t, "position": sell_pos, "shape": sell_shape, "color": sell_color, "text": "Sell"})
    result["markers"] = markers
    result["title"] = "UT Bot Alerts"
    return result
