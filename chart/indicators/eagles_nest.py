# -*- coding: utf-8 -*-
"""Eagles Nest — exact Chartix port (Stochastic + strict/any cross signals)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import chartix_exact as cx
from chart.indicator_settings import marker_position, marker_shape

from .common import empty_result, ensure_ohlcv, line_frame, plot_style


def _calc_kwargs(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "length": int(cfg.get("stoch_len", 14)),
        "smooth_k": int(cfg.get("smooth_k", 3)),
        "smooth_d": int(cfg.get("smooth_d", 3)),
        "upper": float(cfg.get("upper_line", cfg.get("ob_level", 80.0))),
        "lower": float(cfg.get("lower_line", cfg.get("os_level", 20.0))),
        "show_mid": bool(cfg.get("show_mid_line", True)),
        "show_high_low_bg": bool(cfg.get("highlight_above_below", False)),
        "show_strict_bg": bool(cfg.get("highlight_strict", True)),
        "show_strict_letters": bool(cfg.get("show_strict_letters", True)),
        "show_any_bg": bool(cfg.get("highlight_any_cross", False)),
        "show_any_letters": bool(cfg.get("show_any_letters", False)),
        "use_current_resolution": bool(cfg.get("use_chart_resolution", True)),
        "resolution": str(cfg.get("alt_tf", "60")),
        "show_second": bool(cfg.get("show_2nd_stoch", False)),
        "resolution2": str(cfg.get("second_tf", "D")),
        "use_current_resolution2": bool(cfg.get("use_2nd_on_current", False)),
        "length2": int(cfg.get("stoch_len2", cfg.get("length2", 14))),
        "smooth_k2": int(cfg.get("smooth_k2", cfg.get("smoothK2", 3))),
        "smooth_d2": int(cfg.get("smooth_d2", cfg.get("smoothD2", 3))),
        "chart_resolution": cfg.get("_chart_tf"),
        "htf_loader": cfg.get("_htf_loader"),
    }


def chartix_plots(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Raw Chartix plot values (one column per plot id)."""
    return cx.eagles_nest(df, **_calc_kwargs(cfg or {}))


def compute(df: pd.DataFrame, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cfg = cfg or {}
    kw = _calc_kwargs(cfg)
    upper, lower, show_mid, show_2nd = kw["upper"], kw["lower"], kw["show_mid"], kw["show_second"]
    show_k = bool(cfg.get("show_stochK", cfg.get("show_k", True)))
    show_d = bool(cfg.get("show_stochD", cfg.get("show_d", True)))
    k_color = cfg.get("stochK_color", cfg.get("k_color", "#9400D3"))
    d_color = cfg.get("stochD_color", cfg.get("d_color", "#FFD700"))
    show_k2 = bool(cfg.get("show_stochK2", cfg.get("show_k2", True)))
    show_d2 = bool(cfg.get("show_stochD2", cfg.get("show_d2", True)))
    k2_color = cfg.get("stochK2_color", cfg.get("k2_color", "#ffa500"))
    d2_color = cfg.get("stochD2_color", cfg.get("d2_color", "#ffff00"))
    show_upper = bool(cfg.get("show_upper", True))
    show_lower = bool(cfg.get("show_lower", True))
    upper_color = cfg.get("upper_color", "#FFD700")
    lower_color = cfg.get("lower_color", "#9400D3")
    mid_color = cfg.get("middle_color", cfg.get("mid_color", "#808080"))
    buy_strict_c = cfg.get("strictBuy_color", cfg.get("buy_strict_color", "#9400D3"))
    sell_strict_c = cfg.get("strictSell_color", cfg.get("sell_strict_color", "#FFD700"))
    buy_any_c = cfg.get("anyBuy_color", cfg.get("buy_any_color", "#9400D3"))
    sell_any_c = cfg.get("anySell_color", cfg.get("sell_any_color", "#FFD700"))
    show_strict_buy = bool(cfg.get("show_strictBuy", True))
    show_strict_sell = bool(cfg.get("show_strictSell", True))
    show_any_buy = bool(cfg.get("show_anyBuy", True))
    show_any_sell = bool(cfg.get("show_anySell", True))
    show_mid_style = bool(cfg.get("show_middle", True))
    line_width = int(cfg.get("stochK_linewidth", cfg.get("line_width", 3)))
    k_type = cfg.get("stochK_plottype", cfg.get("k_type", "line"))
    d_type = cfg.get("stochD_plottype", cfg.get("d_type", "line"))
    k2_type = cfg.get("stochK2_plottype", cfg.get("k2_type", "line"))
    d2_type = cfg.get("stochD2_plottype", cfg.get("d2_type", "line"))

    data = ensure_ohlcv(df)
    result = empty_result()
    if len(data) < 3:
        return result

    plots = cx.eagles_nest(data, **kw)

    def _line(name: str, values, prefix: str, color: str, width: int, plot_type: str):
        spec = {
            "name": name,
            "pane": "eagles",
            "data": line_frame(data["time"], values, name),
            "color": color,
            "width": width,
            "plot_type": plot_type,
        }
        spec.update(plot_style(cfg, prefix, color=color, width=width, plot_type=plot_type))
        return spec

    if show_k:
        result["lines"].append(_line("Eagles_K", plots["stochK"], "stochK", k_color, line_width, k_type))
    if show_d:
        result["lines"].append(
            _line("Eagles_D", plots["stochD"], "stochD", d_color, int(cfg.get("stochD_linewidth", line_width)), d_type)
        )
    if show_2nd:
        if show_k2:
            result["lines"].append(
                _line("Eagles_K2", plots["stochK2"], "stochK2", k2_color,
                      int(cfg.get("stochK2_linewidth", line_width)), k2_type)
            )
        if show_d2:
            result["lines"].append(
                _line("Eagles_D2", plots["stochD2"], "stochD2", d2_color,
                      int(cfg.get("stochD2_linewidth", line_width)), d2_type)
            )

    def _level(price: float, prefix: str, color: str, width: int, linestyle: str) -> None:
        st = plot_style(cfg, prefix, color=color, width=width, plot_type="line", linestyle=linestyle)
        result["hline"].append(
            {
                "pane": "eagles",
                "price": float(price),
                "color": st["color"],
                "width": st["width"],
                "linestyle": st["linestyle"],
                "plot_type": st["plot_type"],
            }
        )

    if show_upper:
        _level(upper, "upper", upper_color, int(cfg.get("upper_linewidth", line_width)),
               str(cfg.get("upper_linestyle", "solid")))
    if show_lower:
        _level(lower, "lower", lower_color, int(cfg.get("lower_linewidth", line_width)),
               str(cfg.get("lower_linestyle", "solid")))
    if show_mid and show_mid_style:
        _level(50.0, "middle", mid_color, int(cfg.get("middle_linewidth", 2)), str(cfg.get("middle_linestyle", "dashed")))

    # Chartix background colorer: 0 = gold (sell / above upper), 1 = purple (buy / below lower).
    style_bg = bool(cfg.get("show_background", cfg.get("show_bg_highlights", True)))
    show_gold = bool(cfg.get("show_bg_gold", True))
    show_purple = bool(cfg.get("show_bg_purple", True))
    bg_gold = cfg.get("bg_gold", "#ffd54f")
    bg_purple = cfg.get("bg_purple", "#7e57c2")
    if style_bg and (show_gold or show_purple):
        bg = plots["background"].to_numpy()
        # 0 = gold, 1 = purple. A checked-off color drops only that highlight.
        keep = np.where(bg == 1, show_purple, show_gold)
        bg_df = pd.DataFrame(
            {
                "time": data["time"],
                "Eagles_BG": np.where(np.isnan(bg) | ~keep, np.nan, 100.0),
                "color": np.where(bg == 1, bg_purple, bg_gold),
            }
        ).dropna(subset=["Eagles_BG"])
        if not bg_df.empty:
            result["histograms"].append(
                {"name": "Eagles_BG", "pane": "eagles", "data": bg_df, "color": bg_gold, "plot_type": "histogram"}
            )

    markers = []
    times = data["time"]
    for col, show, default_pos, default_shape, color, text in (
        ("strictBuy", show_strict_buy, "below", "square", buy_strict_c, "B"),
        ("strictSell", show_strict_sell, "above", "square", sell_strict_c, "S"),
        ("anyBuy", show_any_buy, "below", "circle", buy_any_c, "B"),
        ("anySell", show_any_sell, "above", "circle", sell_any_c, "S"),
    ):
        if not show:
            continue
        pos = marker_position(cfg.get(f"{col}_location"), default_pos)
        shape = marker_shape(cfg.get(f"{col}_plottype"), default_shape)
        for i in np.flatnonzero(plots[col].to_numpy() == 1):
            markers.append(
                {"time": times.iat[i], "position": pos, "shape": shape, "color": color, "text": text, "pane": "eagles"}
            )
    result["markers"] = markers
    result["title"] = "Eagles Nest - CHARTIX"
    return result
