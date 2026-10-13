# -*- coding: utf-8 -*-
"""VTX Oscillator — exact Chartix port (cross-of-20/80 dots + SRO line)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from . import chartix_exact as cx
from .common import color_alpha, empty_result, ensure_ohlcv, line_frame, plot_style


def _params(cfg: Dict[str, Any]):
    return int(cfg.get("length", 14)), str(cfg.get("source", "Close"))


def chartix_plots(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Raw Chartix plot values (one column per plot id)."""
    return cx.vtx_oscillator(df, *_params(cfg or {}))


def compute(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    length, source = _params(cfg)
    show_vi_m = bool(cfg.get("show_plot_00", cfg.get("show_plot_vi_minus", True)))
    show_vi_p = bool(cfg.get("show_plot_01", cfg.get("show_plot_vi_plus", True)))
    show_sro = bool(cfg.get("show_plot_02", cfg.get("show_sro", True)))
    vi_m_color = cfg.get("plot_00_color", cfg.get("vi_minus_color", "#ff5252"))
    vi_p_color = cfg.get("plot_01_color", cfg.get("vi_plus_color", "#4caf50"))
    sro_color = cfg.get("plot_02_color", cfg.get("sro_color", "#2196f3"))
    w0 = int(cfg.get("plot_00_linewidth", cfg.get("line_width", 2)))
    w1 = int(cfg.get("plot_01_linewidth", w0))
    w2 = int(cfg.get("plot_02_linewidth", 2))
    t0 = str(cfg.get("plot_00_plottype", cfg.get("vi_minus_type", "circles"))).lower()
    t1 = str(cfg.get("plot_01_plottype", cfg.get("vi_plus_type", "circles"))).lower()
    t2 = str(cfg.get("plot_02_plottype", "line")).lower()
    show_mid = bool(cfg.get("show_midline", True))
    mid_val = float(cfg.get("midline_value", 50.0))
    mid_color = cfg.get("midline_color", "#787b86")
    show_ob = bool(cfg.get("show_overbought", True))
    ob_val = float(cfg.get("overbought_value", 80.0))
    ob_color = cfg.get("overbought_color", "#ef5350")
    show_os = bool(cfg.get("show_oversold", True))
    os_val = float(cfg.get("oversold_value", 20.0))
    os_color = cfg.get("oversold_color", "#26a69a")
    show_hlines_bg = bool(cfg.get("show_hlines_bg", True))

    data = ensure_ohlcv(df)
    result = empty_result()
    if len(data) < length + 2:
        return result

    # Chartix: plot_02 = %K of the high/low channel, plot_00 / plot_01 = that value
    # on bars where it crosses 20 / 80 (either direction).
    plots = chartix_plots(data, cfg)
    sro = plots["plot_02"]
    vi_m_plot = plots["plot_00"]
    vi_p_plot = plots["plot_01"]

    def _ptype(t: str, default: str = "circles") -> str:
        return t if t in ("circles", "cross", "line") else default

    if show_vi_p:
        spec = {
            "name": "VI+",
            "pane": "vtx",
            "data": line_frame(data["time"], vi_p_plot, "VI+"),
            "color": vi_p_color,
            "width": max(2, w1),
            "plot_type": _ptype(t1, "circles"),
        }
        spec.update(plot_style(cfg, "plot_01", color=vi_p_color, width=spec["width"], plot_type=spec["plot_type"]))
        result["lines"].append(spec)
    if show_vi_m:
        spec = {
            "name": "VI-",
            "pane": "vtx",
            "data": line_frame(data["time"], vi_m_plot, "VI-"),
            "color": vi_m_color,
            "width": max(2, w0),
            "plot_type": _ptype(t0, "circles"),
        }
        spec.update(plot_style(cfg, "plot_00", color=vi_m_color, width=spec["width"], plot_type=spec["plot_type"]))
        result["lines"].append(spec)
    if show_sro:
        spec = {
            "name": "SRO_VTX",
            "pane": "vtx",
            "data": line_frame(data["time"], sro, "SRO_VTX"),
            "color": sro_color,
            "width": max(2, w2),
            "plot_type": t2,
        }
        spec.update(plot_style(cfg, "plot_02", color=sro_color, width=spec["width"], plot_type=t2))
        result["lines"].append(spec)

    if show_mid:
        result["hline"].append(
            {
                "pane": "vtx",
                "price": mid_val,
                "color": mid_color,
                "width": 1,
                "linestyle": str(cfg.get("midline_linestyle", "dashed")),
            }
        )
    if show_ob:
        result["hline"].append(
            {
                "pane": "vtx",
                "price": ob_val,
                "color": ob_color,
                "width": 1,
                "linestyle": str(cfg.get("overbought_linestyle", "dotted")),
            }
        )
    if show_os:
        result["hline"].append(
            {
                "pane": "vtx",
                "price": os_val,
                "color": os_color,
                "width": 1,
                "linestyle": str(cfg.get("oversold_linestyle", "dotted")),
            }
        )

    # Chartix "Hlines Background": a soft band between oversold and overbought.
    if show_hlines_bg:
        lo = min(os_val, ob_val)
        hi = max(os_val, ob_val)
        band = pd.DataFrame(
            {
                "time": data["time"],
                "open": lo,
                "high": hi,
                "low": lo,
                "close": hi,
                "volume": 0.0,
            }
        )
        bg_color = str(cfg.get("hlines_bg_color") or "")
        wash = bg_color if bg_color.lower().startswith("rgba") else color_alpha(bg_color or mid_color, 0.20)
        band["__up_color"] = wash
        band["__down_color"] = wash
        band["__wick_color"] = "rgba(0,0,0,0)"
        band["__border_color"] = "rgba(0,0,0,0)"
        result["candles"] = {"pane": "vtx", "data": band}

    result["title"] = f"VTX Oscillator {length} {source}"
    return result
