# -*- coding: utf-8 -*-
"""EngulfingCandle — exact Chartix port (buy MIT / sell MIT)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from . import chartix_exact as cx
from chart.indicator_settings import marker_position, marker_shape

from .common import empty_result, ensure_ohlcv


def chartix_plots(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Raw Chartix plot values (one column per plot id)."""
    cfg = cfg or {}
    return cx.ai_engulfing(
        df,
        str(cfg.get("rsi_source", "close")),
        int(cfg.get("rsi_len", 14)),
        float(cfg.get("ob", 70.0)),
        float(cfg.get("os_", 30.0)),
    )


def compute(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    show_bull = bool(cfg.get("show_bullish", cfg.get("show_markers", True)))
    show_bear = bool(cfg.get("show_bearish", cfg.get("show_markers", True)))
    bull_c = cfg.get("bullish_color", cfg.get("buy_color", "#4CAF50"))
    bear_c = cfg.get("bearish_color", cfg.get("sell_color", "#FF5252"))

    data = ensure_ohlcv(df)
    result = empty_result()
    if len(data) < 3:
        return result

    out = chartix_plots(data, cfg)
    bull_pos = marker_position(cfg.get("bullish_location"), "below")
    bear_pos = marker_position(cfg.get("bearish_location"), "above")
    bull_shape = marker_shape(cfg.get("bullish_plottype"), "arrowUp")
    bear_shape = marker_shape(cfg.get("bearish_plottype"), "arrowDown")
    markers = []
    for t, bull, bear in zip(out["time"], out["bullish"], out["bearish"]):
        if show_bull and bull == 1:
            markers.append({"time": t, "position": bull_pos, "shape": bull_shape, "color": bull_c, "text": "buy MIT"})
        if show_bear and bear == 1:
            markers.append({"time": t, "position": bear_pos, "shape": bear_shape, "color": bear_c, "text": "sell MIT"})
    result["markers"] = markers
    result["title"] = "EngulfingCandle"
    return result
