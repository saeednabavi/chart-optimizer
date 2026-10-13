# -*- coding: utf-8 -*-
"""Matrix Series (MS) — exact Chartix port.

Chartix plots: candles between the smoothed up/down lines (green when up > down),
plot_00 / plot_01 = CCI dynamic zones (Dynamic zones), plot_02 / plot_03 =
overbought / oversold marks, plot_04 / plot_05 = OB / OS levels (Show OB/OS).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import chartix_exact as cx
from .common import empty_result, ensure_ohlcv, line_frame, plot_style


def _params(cfg: Dict[str, Any]):
    return (
        int(cfg.get("smoother", cfg.get("length", 5))),
        int(cfg.get("sup_res_period", 50)),
        float(cfg.get("sup_res_percentage", 100)),
        int(cfg.get("price_period", 16)),
        float(cfg.get("overbought", 200)),
        float(cfg.get("oversold", -200)),
        bool(cfg.get("show_obos", False)),
        bool(cfg.get("dynamic_zones", True)),
    )


def chartix_plots(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Raw Chartix plot values (one column per plot id)."""
    return cx.matrix_series(df, *_params(cfg or {}))


def compute(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    nn, lookback, percent, pds, ob, os_, _, _ = _params(cfg)

    show_candles = bool(cfg.get("show_candles", True))
    show_plot_00 = bool(cfg.get("show_plot_00", cfg.get("show_plot_up", True)))
    show_plot_01 = bool(cfg.get("show_plot_01", cfg.get("show_plot_down", True)))
    show_plot_02 = bool(cfg.get("show_plot_02", cfg.get("show_up_shape", True)))
    show_plot_03 = bool(cfg.get("show_plot_03", cfg.get("show_down_shape", True)))
    show_plot_04 = bool(cfg.get("show_plot_04", cfg.get("show_resistance", True)))
    show_plot_05 = bool(cfg.get("show_plot_05", cfg.get("show_support", True)))

    candle_up = cfg.get("candle_color2", cfg.get("candle_up", "#008000"))
    candle_down = cfg.get("candle_color1", cfg.get("candle_down", "#ff0000"))
    candle_wick = cfg.get("candle_wick", "#737375")
    candle_border = cfg.get("candle_border", "#000000")
    c00 = cfg.get("plot_00_color", cfg.get("plot_up_color", "#008000"))
    c01 = cfg.get("plot_01_color", cfg.get("plot_down_color", "#ff0000"))
    c02 = cfg.get("plot_02_color", cfg.get("up_shape_color", "#00ffff"))
    c03 = cfg.get("plot_03_color", cfg.get("down_shape_color", "#00ffff"))
    c04 = cfg.get("plot_04_color", cfg.get("resistance_color", "#000000"))
    c05 = cfg.get("plot_05_color", cfg.get("support_color", "#000000"))
    w00 = int(cfg.get("plot_00_linewidth", cfg.get("line_width", 2)))
    w01 = int(cfg.get("plot_01_linewidth", w00))
    w02 = int(cfg.get("plot_02_linewidth", 2))
    w03 = int(cfg.get("plot_03_linewidth", 2))
    w04 = int(cfg.get("plot_04_linewidth", 1))
    w05 = int(cfg.get("plot_05_linewidth", 1))
    t00 = cfg.get("plot_00_plottype", "line")
    t01 = cfg.get("plot_01_plottype", "line")
    t02 = cfg.get("plot_02_plottype", "cross")
    t03 = cfg.get("plot_03_plottype", "cross")
    t04 = cfg.get("plot_04_plottype", "line")
    t05 = cfg.get("plot_05_plottype", "line")

    data = ensure_ohlcv(df)
    result = empty_result()
    if len(data) < 3:
        return result

    plots = chartix_plots(data, cfg)

    show_color_down = bool(cfg.get("show_candle_color1", True))
    show_color_up = bool(cfg.get("show_candle_color2", True))
    if show_candles and (show_color_down or show_color_up):
        lo = plots["candle_open"].to_numpy()
        hi = plots["candle_close"].to_numpy()
        green = plots["candle_color"].to_numpy() == 1
        # The pane colors candles by close vs open, so orient each body by the Chartix color.
        keep = ~(np.isnan(lo) | np.isnan(hi)) & np.where(green, show_color_up, show_color_down)
        candles = pd.DataFrame(
            {
                "time": data["time"],
                "open": np.where(green, lo, hi),
                "high": hi,
                "low": lo,
                "close": np.where(green, hi, lo),
                "volume": 0.0,
            }
        ).loc[keep]
        candles["__up_color"] = candle_up
        candles["__down_color"] = candle_down
        candles["__wick_color"] = candle_wick
        candles["__border_color"] = candle_border
        result["candles"] = {"pane": "matrix", "data": candles}

    def _ms_line(name: str, values, prefix: str, color: str, width: int, plot_type: str) -> Dict[str, Any]:
        spec = {
            "name": name,
            "pane": "matrix",
            "data": line_frame(data["time"], values, name),
            "color": color,
            "width": width,
            "plot_type": plot_type,
        }
        spec.update(plot_style(cfg, prefix, color=color, width=width, plot_type=plot_type))
        return spec

    for show, name, col, prefix, color, width, ptype in (
        (show_plot_00, "MS_Zone00", "plot_00", "plot_00", c00, w00, t00),
        (show_plot_01, "MS_Zone01", "plot_01", "plot_01", c01, w01, t01),
        (show_plot_02, "MS_OB", "plot_02", "plot_02", c02, w02, t02),
        (show_plot_03, "MS_OS", "plot_03", "plot_03", c03, w03, t03),
        (show_plot_04, "MS_OBLevel", "plot_04", "plot_04", c04, w04, t04),
        (show_plot_05, "MS_OSLevel", "plot_05", "plot_05", c05, w05, t05),
    ):
        if show:
            result["lines"].append(_ms_line(name, plots[col].to_numpy(), prefix, color, width, ptype))

    result["markers"] = []
    result["title"] = f"MS {nn} {lookback} {int(percent)} {pds} {int(ob)} {int(os_)}"
    return result
