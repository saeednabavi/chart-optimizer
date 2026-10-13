# -*- coding: utf-8 -*-
"""TCG AI Tools — exact Chartix port.

1) Thick bar at 0: red when SMA20(close) > SMA10(close), else green.
   A solid line uses the Chartix pixel width (default 40) and round caps.
   Those caps are the ellipses at each end and at every color change.
2) Pane background: green when RSI(close) >= Overbought, red when RSI <= Oversold.
3) Triangles: up when price crosses up through the lower BB, down when it crosses
   up through the upper BB.
Legend value is always 0.00 (plot of zero with a colorer).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import chartix_exact as cx
from chart.indicator_settings import marker_position

from .common import empty_result, ensure_ohlcv, line_frame


def _params(cfg: Dict[str, Any]):
    return (
        str(cfg.get("price", "close")),
        int(cfg.get("bb_len", 20)),
        float(cfg.get("bb_mult", 2.0)),
        float(cfg.get("overbought", cfg.get("rsi_ob", 70.0))),
        float(cfg.get("oversold", cfg.get("rsi_os", 30.0))),
        int(cfg.get("length", cfg.get("rsi_len", 14))),
    )


def chartix_plots(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Raw Chartix plot values (one column per plot id)."""
    return cx.tcg_ai_tools(df, *_params(cfg or {}))


def compute(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    price_src, bb_len, bb_mult, rsi_ob, rsi_os, length = _params(cfg)

    show_plot = bool(cfg.get("show_plot_00", cfg.get("show_plot", True)))
    try:
        plot_width = int(cfg.get("plot_00_linewidth", cfg.get("line_width", 40)))
    except (TypeError, ValueError):
        plot_width = 40
    plot_style_name = str(cfg.get("plot_00_plottype", cfg.get("plot_type", "line"))).lower()
    plot_ls = str(cfg.get("plot_00_linestyle", "solid"))
    # Chartix palette_0: Color0=red (bear), Color1=green (bull), linewidth≈40
    plot_bear = cfg.get("plot_00_color0", cfg.get("plot_color0", "#ff0000"))
    plot_bull = cfg.get("plot_00_color1", cfg.get("plot_color1", "#008000"))
    show_bear = bool(cfg.get("show_plot_00_color0", True))
    show_bull = bool(cfg.get("show_plot_00_color1", True))
    show_down = bool(cfg.get("show_plot_01", cfg.get("show_bb_cross_down", True)))
    show_up = bool(cfg.get("show_plot_02", cfg.get("show_bb_cross_up", True)))
    down_c = cfg.get("plot_01_color", cfg.get("bb_cross_down_color", "#ff6969"))
    up_c = cfg.get("plot_02_color", cfg.get("bb_cross_up_color", "#61ff67"))
    down_loc = marker_position(cfg.get("plot_01_location"), "absolute")
    up_loc = marker_position(cfg.get("plot_02_location"), "absolute")
    # Chartix defaults: both bg colorers on
    show_bg_ob = bool(cfg.get("show_plot_03", cfg.get("show_bg_up", True)))
    show_bg_os = bool(cfg.get("show_plot_04", cfg.get("show_bg_down", True)))
    # palette_1 green = RSI overbought; palette_2 red = RSI oversold (per script docs)
    # Soft washes (TV bgcolor); keep alpha low so LWC hist does not look solid
    bg_ob = cfg.get("plot_03_color", cfg.get("bg_up_color", "rgba(76, 175, 80, 0.22)"))
    bg_os = cfg.get("plot_04_color", cfg.get("bg_down_color", "rgba(255, 82, 82, 0.22)"))

    data = ensure_ohlcv(df)
    result = empty_result()
    need = max(bb_len, length, 20) + 2
    if len(data) < need:
        return result

    plots = chartix_plots(data, cfg)
    bull = (plots["plot_00c"] == 1).to_numpy()

    # Fixed pane scale anchors so ribbon stays a mid band (like TV linewidth=40 at 0)
    # while RSI bgcolor can paint full-height translucent columns.
    result["hline"].extend(
        [
            {"pane": "tcg", "price": 1.0, "color": "rgba(0,0,0,0)"},
            {"pane": "tcg", "price": -1.0, "color": "rgba(0,0,0,0)"},
            {"pane": "tcg", "price": 0.0, "color": "rgba(120,120,120,0.25)"},
        ]
    )

    # 2) RSI background colorers (full-height translucent hist)
    if show_bg_ob or show_bg_os:
        bg_vals: list = []
        bg_cols: list = []
        ob_on = plots["plot_03"].notna().to_numpy()
        os_on = plots["plot_04"].notna().to_numpy()
        for i in range(len(data)):
            if show_bg_ob and ob_on[i]:
                bg_vals.append(1.0)
                bg_cols.append(bg_ob)
            elif show_bg_os and os_on[i]:
                bg_vals.append(-1.0)
                bg_cols.append(bg_os)
            else:
                bg_vals.append(np.nan)
                bg_cols.append("#00000000")
        bg_df = pd.DataFrame({"time": data["time"], "TCG_BG": bg_vals, "color": bg_cols}).dropna(
            subset=["TCG_BG"]
        )
        if not bg_df.empty:
            result["histograms"].append(
                {
                    "name": "TCG_BG",
                    "pane": "tcg",
                    "data": bg_df,
                    "color": bg_ob,
                    "plot_type": "histogram",
                }
            )

    if show_plot and (show_bear or show_bull):
        # Legend series always 0.00 (matches Chartix). Width/style come from the dialog.
        # A checked-off palette color drops only those bars; the other color stays.
        zero = np.where(bull, 0.0 if show_bull else np.nan, 0.0 if show_bear else np.nan)
        colors = np.where(bull, plot_bull, plot_bear)
        as_dots = plot_style_name in ("circles", "cross", "shape")
        as_fill = plot_style_name in ("histogram", "columns", "column", "area")
        # Chartix draws plot style Line as a pixel stroke (linewidth 40) with round caps.
        # The caps are the ellipses at the two ends and wherever red and green meet.
        # A histogram ribbon is square, so it never produces those ellipses.
        round_caps = (not as_dots) and (not as_fill) and plot_ls == "solid"
        if round_caps:
            stroke = max(1, min(64, int(plot_width)))
            trend = pd.DataFrame(
                {"time": data["time"], "TCG_Trend": zero, "color": colors}
            ).dropna(subset=["TCG_Trend"])
            result["lines"].append(
                {
                    "name": "TCG_Trend",
                    "pane": "tcg",
                    "data": trend,
                    "color": plot_bull if bool(bull[-1]) else plot_bear,
                    "width": stroke,
                    "width_cap": 64,
                    "round_caps": True,
                    "plot_type": "line",
                    "linestyle": "solid",
                }
            )
        else:
            # Columns/area still use a ribbon. Dashed and dotted stay a real stroke:
            # a ribbon painted on top of them hides the line style.
            ribbon_amp = 0.0
            if as_fill and plot_ls == "solid":
                ribbon_amp = max(0.4, min(0.48, 0.14 * (max(plot_width, 1) / 40.0)))
            dot_width = max(3, min(8, int(round(plot_width / 5.0)) or 3))
            result["lines"].append(
                {
                    "name": "TCG_Trend",
                    "pane": "tcg",
                    "data": line_frame(data["time"], pd.Series(zero, index=data.index), "TCG_Trend"),
                    "color": plot_bull if bool(bull[-1]) else plot_bear,
                    "width": dot_width if as_dots else (2 if ribbon_amp else min(4, max(2, plot_width))),
                    "plot_type": "cross" if plot_style_name == "cross" else ("circles" if as_dots else "line"),
                    "linestyle": plot_ls,
                }
            )
            ribbon = np.full(len(data), ribbon_amp)
            if not show_bull:
                ribbon = np.where(bull, np.nan, ribbon)
            if not show_bear:
                ribbon = np.where(~bull, np.nan, ribbon)
            if ribbon_amp > 0 and np.isfinite(ribbon).any():
                up_df = pd.DataFrame(
                    {"time": data["time"], "TCG_RibbonUp": ribbon, "color": colors}
                ).dropna(subset=["TCG_RibbonUp"])
                dn_df = pd.DataFrame(
                    {"time": data["time"], "TCG_RibbonDn": -ribbon, "color": colors}
                ).dropna(subset=["TCG_RibbonDn"])
                for name, frame in (("TCG_RibbonUp", up_df), ("TCG_RibbonDn", dn_df)):
                    result["histograms"].append(
                        {
                            "name": name,
                            "pane": "tcg",
                            "data": frame,
                            "color": plot_bull if bool(bull[-1]) else plot_bear,
                            "width": 4,
                            "plot_type": "histogram",
                        }
                    )
    # Keep the pane scaled even when the main plot is off, so crosses stay visible.
    result["fixed_scale"] = {"pane": "tcg", "min": -1.0, "max": 1.0}

    # 3) BB triangles: Chartix plot_02 (green, up) when price crosses up through the
    # lower band, plot_01 (red, down) when it crosses up through the upper band.
    # Drawn as dots on this pane so they stay visible with the main plot off.
    markers = []
    up_mark = np.where(plots["plot_02"].notna(), 0.28, np.nan) if show_up else np.full(len(data), np.nan)
    dn_mark = np.where(plots["plot_01"].notna(), -0.28, np.nan) if show_down else np.full(len(data), np.nan)
    # Absolute keeps the cross on its oscillator value. Top / Bottom move it to the pane edge.
    if show_up and up_loc == "absolute" and np.isfinite(up_mark).any():
        result["lines"].append(
            {
                "name": "TCG_CrossUp",
                "pane": "tcg",
                "data": line_frame(data["time"], pd.Series(up_mark, index=data.index), "TCG_CrossUp"),
                "color": up_c,
                "width": 5,
                "plot_type": "circles",
                "linestyle": "solid",
            }
        )
    if show_down and down_loc == "absolute" and np.isfinite(dn_mark).any():
        result["lines"].append(
            {
                "name": "TCG_CrossDn",
                "pane": "tcg",
                "data": line_frame(data["time"], pd.Series(dn_mark, index=data.index), "TCG_CrossDn"),
                "color": down_c,
                "width": 5,
                "plot_type": "circles",
                "linestyle": "solid",
            }
        )
    if show_up and up_loc != "absolute":
        for t, v in zip(data["time"], plots["plot_02"]):
            if pd.notna(v):
                markers.append(
                    {"time": t, "position": up_loc, "shape": "arrowUp", "color": up_c, "text": "", "pane": "tcg"}
                )
    if show_down and down_loc != "absolute":
        for t, v in zip(data["time"], plots["plot_01"]):
            if pd.notna(v):
                markers.append(
                    {"time": t, "position": down_loc, "shape": "arrowDown", "color": down_c, "text": "", "pane": "tcg"}
                )
    result["markers"] = markers
    result["title"] = f"TCG AI Tools {price_src} {bb_len} {bb_mult:g} {int(rsi_ob)} {int(rsi_os)} {length}"
    return result
