# -*- coding: utf-8 -*-
"""Bulls v Bears — exact Chartix port."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import chartix_exact as cx
from .common import empty_result, ensure_ohlcv, line_frame, plot_style


def _params(cfg: Dict[str, Any]):
    return (
        int(cfg.get("period", cfg.get("ma_len", 14))),
        int(cfg.get("bars_back", 120)),
        float(cfg.get("line_height", 80.0)),
    )


def chartix_plots(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Raw Chartix plot values (one column per plot id)."""
    return cx.bulls_v_bears(df, *_params(cfg or {}))


def compute(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    period, bars_back, line_height = _params(cfg)
    show_hist = bool(cfg.get("show_plot_00", cfg.get("show_hist", True)))
    show_dots = bool(cfg.get("show_plot_01", cfg.get("show_dots", True)))
    hist_up = cfg.get("plot_00_color0", cfg.get("hist_up", "#008000"))
    hist_down = cfg.get("plot_00_color1", cfg.get("hist_down", "#ff0000"))
    show_hist_up = bool(cfg.get("show_plot_00_color0", True))
    show_hist_down = bool(cfg.get("show_plot_00_color1", True))
    dots_color = cfg.get("plot_01_color", cfg.get("dots_color", "#ffff00"))
    line_width = int(cfg.get("plot_01_linewidth", cfg.get("line_width", 4)))
    hist_type = cfg.get("plot_00_plottype", cfg.get("hist_type", "columns"))
    if hist_type in ("columns", "histogram"):
        hist_type = "histogram"
    dots_type = cfg.get("plot_01_plottype", cfg.get("dots_type", "circles"))

    data = ensure_ohlcv(df)
    result = empty_result()
    if len(data) < 3:
        return result

    plots = chartix_plots(data, cfg)
    diff = plots["plot_00"]

    if show_hist and (show_hist_up or show_hist_down):
        up = plots["plot_00c"].to_numpy() == 0
        values = diff.to_numpy().astype(float)
        if not show_hist_up:
            values = np.where(up, np.nan, values)
        if not show_hist_down:
            values = np.where(~up, np.nan, values)
        colors = np.where(up, hist_up, hist_down)
        hist = pd.DataFrame({"time": data["time"], "BvB": values, "color": colors}).dropna(subset=["BvB"])
        spec = {
            "name": "BvB",
            "pane": "bvb",
            "data": hist,
            "color": hist_up,
            "color_neg": hist_down,
            "color_pos": hist_up,
            "plot_type": hist_type,
        }
        spec.update(
            {
                k: v
                for k, v in plot_style(
                    cfg, "plot_00", color=hist_up, width=1, plot_type=hist_type
                ).items()
                if k != "color"
            }
        )
        kind = str(spec.get("plot_type", hist_type)).lower()
        if kind in ("histogram", "columns", "column", "area"):
            spec["plot_type"] = "histogram"
            result["histograms"].append(spec)
        else:
            result["lines"].append(spec)

    if show_dots:
        dots = plots["plot_01"]
        dot_type = dots_type if dots_type not in ("line",) else "circles"
        spec = {
            "name": "BvB_Dots",
            "pane": "bvb",
            "data": line_frame(data["time"], dots, "BvB_Dots"),
            "color": dots_color,
            "width": max(3, line_width),
            "plot_type": dot_type,
        }
        spec.update(plot_style(cfg, "plot_01", color=dots_color, width=spec["width"], plot_type=dot_type))
        result["lines"].append(spec)

    result["markers"] = []
    result["hline"].append({"pane": "bvb", "price": 0, "color": "#666666"})
    result["title"] = f"BvB {period} {bars_back} {int(line_height)}"
    return result
