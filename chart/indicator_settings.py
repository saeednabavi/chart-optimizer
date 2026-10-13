# -*- coding: utf-8 -*-
"""Indicator Input / Style / Visibility schemas matching Chartix dialogs."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List

SETTINGS_FILE = Path(__file__).resolve().parent / "user_settings.json"

SOURCE_CHOICES = ["close", "open", "high", "low", "hl2", "hlc3", "ohlc4"]
SOURCE_OHLC = ["Open", "High", "Low", "Close"]
TF_CHOICES = ["1min", "2min", "3min", "5min", "10min", "15min", "30min", "1h", "1d", "1w", "1mon"]
RESOLUTION_CHOICES = ["1", "5", "15", "30", "60", "240", "D", "W", "M"]
RESOLUTION_LABELS = {
    "1": "1 minute",
    "5": "5 minutes",
    "15": "15 minutes",
    "30": "30 minutes",
    "60": "1 hour",
    "240": "4 hours",
    "D": "1 day",
    "W": "1 week",
    "M": "1 month",
}

# Chartix shape-location dropdowns. Pane studies use Top/Bottom/Absolute.
# Price overlays also offer Above bar / Below bar.
PANE_LOCATIONS = ["Top", "Bottom", "Absolute"]
PRICE_LOCATIONS = ["Above bar", "Below bar", "Absolute", "Top", "Bottom"]

LINESTYLE_CHOICES = ["solid", "dotted", "dashed"]
LINESTYLE_FROM_TV = {0: "solid", 1: "dotted", 2: "dashed"}
LINESTYLE_TO_TV = {"solid": 0, "dotted": 1, "dashed": 2}

PLOTTYPE_CHOICES = ["line", "histogram", "circles", "cross", "columns", "area", "shape"]
PLOTTYPE_FROM_TV = {
    0: "line",
    1: "histogram",
    3: "circles",
    4: "cross",
    5: "columns",
    6: "circles",
    7: "cross",
    "shape_triangle_up": "shape",
    "shape_triangle_down": "shape",
    "shape_label_up": "shape",
    "shape_label_down": "shape",
}

PRECISION_CHOICES = ["default", "0", "1", "2", "3", "4", "5", "6", "7", "8"]

# Chartix Visibility tab: checkbox + from/to range per interval group.
VISIBILITY_GROUPS = [
    {"id": "minutes", "label": "Minutes", "min": 1, "max": 59},
    {"id": "hours", "label": "Hours", "min": 1, "max": 24},
    {"id": "days", "label": "Days", "min": 1, "max": 366},
    {"id": "weeks", "label": "Weeks", "min": 1, "max": 52},
    {"id": "months", "label": "Months", "min": 1, "max": 12},
]
VISIBILITY_FIELDS = [
    {
        "kind": "range",
        "key": f"visible_{g['id']}",
        "from_key": f"visible_{g['id']}_from",
        "to_key": f"visible_{g['id']}_to",
        "label": g["label"],
        "min": g["min"],
        "max": g["max"],
        "default": True,
        "default_from": g["min"],
        "default_to": g["max"],
    }
    for g in VISIBILITY_GROUPS
]
_VIS_LIMITS = {g["id"]: (g["min"], g["max"]) for g in VISIBILITY_GROUPS}

OUTPUT_FIELDS = [
    {
        "key": "precision",
        "label": "Precision",
        "type": "choice",
        "default": "default",
        "choices": PRECISION_CHOICES,
    },
    {"key": "labels_on_price_scale", "label": "Labels on price scale", "type": "bool", "default": True},
    {"key": "values_in_status_line", "label": "Values in status line", "type": "bool", "default": True},
]


def _keep_color(c: Any, fallback: str = "#2196f3") -> str:
    """Keep Chartix rgba() fills; normalize everything else to hex."""
    s = "" if c is None else str(c).strip()
    if s.lower().startswith("rgba"):
        return s
    return _norm_color(c, fallback)


def _norm_color(c: Any, fallback: str = "#2196f3") -> str:
    if c is None:
        return fallback
    s = str(c).strip()
    if not s:
        return fallback
    named = {
        "green": "#008000",
        "red": "#ff0000",
        "aqua": "#00ffff",
        "black": "#000000",
        "yellow": "#ffff00",
        "orange": "#ffa500",
        "gray": "#808080",
        "grey": "#808080",
        "white": "#ffffff",
        "blue": "#2196f3",
    }
    low = s.lower()
    if low in named:
        return named[low]
    if s.startswith("rgb"):
        # rgb(a)(r,g,b[,a]) → #rrggbb
        try:
            inner = s[s.find("(") + 1 : s.rfind(")")]
            parts = [p.strip() for p in inner.split(",")]
            r, g, b = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return fallback
    if s.startswith("#") and len(s) in (4, 7, 9):
        return s[:7] if len(s) >= 7 else s
    return s


def _plot_row(
    key: str,
    label: str,
    *,
    color: str = "#2196f3",
    linestyle: str = "solid",
    linewidth: int = 2,
    plottype: str = "line",
    show: bool = True,
    simple: bool = False,
    location: str | None = None,
    locations: List[str] | None = None,
    shape_icon: str | None = None,
    nested: bool = False,
    color_label: str | None = None,
) -> Dict[str, Any]:
    """Style row matching Chartix: checkbox + title + color + line sample + type."""
    row: Dict[str, Any] = {
        "kind": "plot",
        "key": key,
        "label": label,
        "simple": simple,  # shapes / single-color fills: no line editor
        "show_key": f"show_{key}",
        "color_key": f"{key}_color",
        "linestyle_key": f"{key}_linestyle",
        "linewidth_key": f"{key}_linewidth",
        "plottype_key": f"{key}_plottype",
        "defaults": {
            f"show_{key}": show,
            f"{key}_color": _keep_color(color),
            f"{key}_linestyle": linestyle,
            f"{key}_linewidth": int(linewidth),
            f"{key}_plottype": plottype,
        },
    }
    if location is not None:
        row["location_key"] = f"{key}_location"
        row["location_choices"] = list(locations or PRICE_LOCATIONS)
        row["defaults"][f"{key}_location"] = location
    if shape_icon:
        row["shape_icon"] = shape_icon
    if nested:
        row["nested"] = True
        row["color_label"] = color_label or "Color 0"
    return row


def _candles_block(
    *,
    color1: str = "red",
    color2: str = "green",
    wick: str = "#737375",
    border: str = "black",
    show: bool = True,
) -> Dict[str, Any]:
    return {
        "kind": "candles",
        "key": "candles",
        "label": "Candles",
        "show_key": "show_candles",
        "color1_key": "candle_color1",
        "color2_key": "candle_color2",
        "wick_key": "candle_wick",
        "border_key": "candle_border",
        "show_color1_key": "show_candle_color1",
        "show_color2_key": "show_candle_color2",
        "defaults": {
            "show_candles": show,
            "show_candle_color1": True,
            "show_candle_color2": True,
            "candle_color1": _norm_color(color1, "#ff0000"),
            "candle_color2": _norm_color(color2, "#008000"),
            "candle_wick": _norm_color(wick, "#737375"),
            "candle_border": _norm_color(border, "#000000"),
        },
    }


def _tv_plottype(v: Any) -> str:
    if isinstance(v, str) and v.startswith("shape"):
        return "shape"
    if v in PLOTTYPE_FROM_TV:
        return PLOTTYPE_FROM_TV[v]
    try:
        return PLOTTYPE_FROM_TV.get(int(v), "line")
    except Exception:
        return "line"


def _tv_linestyle(v: Any) -> str:
    try:
        return LINESTYLE_FROM_TV.get(int(v), "solid")
    except Exception:
        return "solid"


SCHEMAS: Dict[str, Dict[str, Any]] = {
    "matrix": {
        "title": "MS",
        "inputs": [
            {"key": "smoother", "label": "Smoother", "type": "int", "default": 5, "min": 1},
            {"key": "sup_res_period", "label": "SupResPeriod", "type": "int", "default": 50, "min": 1},
            {"key": "sup_res_percentage", "label": "SupResPercentage", "type": "int", "default": 100},
            {"key": "price_period", "label": "PricePeriod", "type": "int", "default": 16, "min": 1},
            {"key": "overbought", "label": "Overbought", "type": "int", "default": 200},
            {"key": "oversold", "label": "Oversold", "type": "int", "default": -200},
            {"key": "show_obos", "label": "Show OB/OS", "type": "bool", "default": False},
            {"key": "dynamic_zones", "label": "Dynamic zones", "type": "bool", "default": True},
        ],
        "styles": [
            {
                **_candles_block(color1="red", color2="green", wick="#737375", border="black"),
                "body_label": "Body",  # Chartix Style shows Body under Candles
            },
            _plot_row("plot_00", "Plot", color="green", linestyle="solid", linewidth=2, plottype="line"),
            _plot_row("plot_01", "Plot", color="red", linestyle="solid", linewidth=2, plottype="line"),
            _plot_row("plot_02", "Plot", color="aqua", linestyle="solid", linewidth=2, plottype="circles"),
            _plot_row("plot_03", "Plot", color="aqua", linestyle="solid", linewidth=2, plottype="circles"),
            _plot_row("plot_04", "Plot", color="black", linestyle="dashed", linewidth=1, plottype="cross"),
            _plot_row("plot_05", "Plot", color="black", linestyle="dashed", linewidth=1, plottype="cross"),
            *OUTPUT_FIELDS,
        ],
    },
    "tcg": {
        "title": "TCG AI Tools",
        "inputs": [
            {
                "key": "price",
                "label": "Price",
                "type": "choice",
                "default": "close",
                "choices": SOURCE_CHOICES,
            },
            {"key": "bb_len", "label": "Bollinger length", "type": "int", "default": 20, "min": 1},
            {
                "key": "bb_mult",
                "label": "Bollinger Multiplier",
                "type": "float",
                "default": 2.0,
            },
            {"key": "overbought", "label": "Overbought", "type": "int", "default": 70, "min": 1},
            {"key": "oversold", "label": "Oversold", "type": "int", "default": 30, "min": 1},
            {"key": "length", "label": "Length", "type": "int", "default": 14, "min": 1},
        ],
        "styles": [
            _plot_row("plot_00", "Plot", color="red", linestyle="solid", linewidth=40, plottype="line"),
            # Chartix palette green for bullish trend bar
            {
                "kind": "palette",
                "key": "plot_00_palette",
                "label": "Plot Color 1 / Color 2",
                "show0_key": "show_plot_00_color0",
                "show1_key": "show_plot_00_color1",
                "defaults": {
                    "plot_00_color0": _norm_color("red"),
                    "plot_00_color1": _norm_color("green"),
                    "show_plot_00_color0": True,
                    "show_plot_00_color1": True,
                },
            },
            _plot_row(
                "plot_01",
                "BB Cross",
                color="#ff6969",
                plottype="shape_triangle_down",
                simple=True,
                location="Absolute",
                locations=PANE_LOCATIONS,
                shape_icon="triangle_down",
            ),
            _plot_row(
                "plot_02",
                "BB Cross",
                color="#61ff67",
                plottype="shape_triangle_up",
                simple=True,
                location="Absolute",
                locations=PANE_LOCATIONS,
                shape_icon="triangle_up",
            ),
            _plot_row(
                "plot_03",
                "Backgroud Color",
                color="rgba(76, 175, 80, 0.4)",
                plottype="shape",
                simple=True,
                nested=True,
                color_label="Color 0",
            ),
            _plot_row(
                "plot_04",
                "Backgroud Color",
                color="rgba(255, 82, 82, 0.4)",
                plottype="shape",
                simple=True,
                nested=True,
                color_label="Color 0",
            ),
            *OUTPUT_FIELDS,
        ],
    },
    "vtx": {
        "title": "VTX Oscillator",
        "inputs": [
            {"key": "length", "label": "Length", "type": "int", "default": 14, "min": 1},
            {
                "key": "source",
                "label": "Source",
                "type": "choice",
                "default": "Close",
                "choices": SOURCE_OHLC,
            },
        ],
        "styles": [
            _plot_row("plot_00", "Plot", color="rgb(255,82,82)", linestyle="solid", linewidth=2, plottype="circles"),
            _plot_row("plot_01", "Plot", color="rgb(76,175,80)", linestyle="solid", linewidth=2, plottype="circles"),
            _plot_row("plot_02", "SRO VTX", color="rgb(33,150,243)", linestyle="solid", linewidth=2, plottype="line"),
            # Chartix Style bands (exact labels from dialog)
            {
                "kind": "band",
                "key": "midline",
                "label": "Midline",
                "show_key": "show_midline",
                "color_key": "midline_color",
                "value_key": "midline_value",
                "linestyle_key": "midline_linestyle",
                "defaults": {
                    "show_midline": True,
                    "midline_color": "#787b86",
                    "midline_linestyle": "dashed",
                    "midline_value": 50.0,
                },
            },
            {
                "kind": "band",
                "key": "overbought",
                "label": "Overbought",
                "show_key": "show_overbought",
                "color_key": "overbought_color",
                "value_key": "overbought_value",
                "linestyle_key": "overbought_linestyle",
                "defaults": {
                    "show_overbought": True,
                    "overbought_color": "#ef5350",
                    "overbought_linestyle": "dotted",
                    "overbought_value": 80.0,
                },
            },
            {
                "kind": "band",
                "key": "oversold",
                "label": "Oversold",
                "show_key": "show_oversold",
                "color_key": "oversold_color",
                "value_key": "oversold_value",
                "linestyle_key": "oversold_linestyle",
                "defaults": {
                    "show_oversold": True,
                    "oversold_color": "#26a69a",
                    "oversold_linestyle": "dotted",
                    "oversold_value": 20.0,
                },
            },
            {
                "kind": "color_check",
                "key": "hlines_bg",
                "label": "Hlines Background",
                "show_key": "show_hlines_bg",
                "color_key": "hlines_bg_color",
                "defaults": {
                    "show_hlines_bg": True,
                    "hlines_bg_color": "rgba(120, 123, 134, 0.20)",
                },
            },
            *OUTPUT_FIELDS,
        ],
    },
    "eagles": {
        "title": "Eagles Nest - CHARTIX",
        "inputs": [
            {
                "key": "stoch_len",
                "label": "Length for Main Stochastic",
                "type": "int",
                "default": 14,
                "min": 1,
            },
            {
                "key": "smooth_k",
                "label": "SmoothK for Main Stochastic",
                "type": "int",
                "default": 3,
                "min": 1,
            },
            {
                "key": "smooth_d",
                "label": "SmoothD for Main Stochastic",
                "type": "int",
                "default": 3,
                "min": 1,
            },
            {
                "key": "upper_line",
                "label": "Upper Line Value",
                "type": "int",
                "default": 80,
                "min": 50,
                "max": 90,
            },
            {
                "key": "lower_line",
                "label": "Lower Line Value",
                "type": "int",
                "default": 20,
                "min": 10,
                "max": 50,
            },
            {"key": "show_mid_line", "label": "Show Mid Line", "type": "bool", "default": True},
            {
                "key": "highlight_above_below",
                "label": "Highlight Above/Below High/Low Lines",
                "type": "bool",
                "default": False,
            },
            {
                "key": "highlight_strict",
                "label": "Highlight Strict Crosses",
                "type": "bool",
                "default": True,
            },
            {
                "key": "show_strict_letters",
                "label": "Show Strict B/S Letters",
                "type": "bool",
                "default": True,
            },
            {
                "key": "highlight_any_cross",
                "label": "Highlight Any Cross",
                "type": "bool",
                "default": False,
            },
            {
                "key": "show_any_letters",
                "label": "Show Any-Cross B/S Letters",
                "type": "bool",
                "default": False,
            },
            {
                "key": "use_chart_resolution",
                "label": "Use Current Chart Resolution",
                "type": "bool",
                "default": True,
            },
            {
                "key": "alt_tf",
                "label": "Use Different Timeframe",
                "type": "choice",
                "default": "60",
                "choices": RESOLUTION_CHOICES,
                "labels": RESOLUTION_LABELS,
            },
            {"key": "show_2nd_stoch", "label": "Show 2nd Stoch", "type": "bool", "default": False},
            {
                "key": "second_tf",
                "label": "2nd Stoch Timeframe",
                "type": "choice",
                "default": "D",
                "choices": RESOLUTION_CHOICES,
                "labels": RESOLUTION_LABELS,
            },
            {
                "key": "use_2nd_on_current",
                "label": "Use 2nd Stoch on Current Timeframe",
                "type": "bool",
                "default": False,
            },
            {
                "key": "stoch_len2",
                "label": "2nd Stoch Length",
                "type": "int",
                "default": 14,
                "min": 1,
            },
            {
                "key": "smooth_k2",
                "label": "SmoothK for 2nd Stoch",
                "type": "int",
                "default": 3,
                "min": 1,
            },
            {
                "key": "smooth_d2",
                "label": "SmoothD for 2nd Stoch",
                "type": "int",
                "default": 3,
                "min": 1,
            },
        ],
        "styles": [
            _plot_row("stochK", "Stoch K", color="#9400D3", linewidth=3, plottype="line"),
            _plot_row("stochD", "Stoch D", color="#FFD700", linewidth=3, plottype="line"),
            _plot_row(
                "stochK2",
                "2nd Stoch K - Different TimeFrame",
                color="orange",
                linewidth=3,
                plottype="line",
            ),
            _plot_row(
                "stochD2",
                "2nd Stoch D - Different TimeFrame",
                color="yellow",
                linewidth=3,
                plottype="line",
            ),
            _plot_row("upper", "Upper Line", color="#FFD700", linewidth=3, plottype="line"),
            _plot_row("lower", "Lower Line", color="#9400D3", linewidth=3, plottype="line"),
            _plot_row("middle", "Mid Line", color="gray", linestyle="dashed", linewidth=2, plottype="line"),
            _plot_row(
                "strictBuy",
                "Buy Signal Strict Criteria",
                color="#9400D3",
                plottype="shape_label_up",
                simple=True,
                location="Bottom",
                locations=PANE_LOCATIONS,
                shape_icon="label_up",
            ),
            _plot_row(
                "strictSell",
                "Sell Signal Strict Criteria",
                color="#FFD700",
                plottype="shape_label_down",
                simple=True,
                location="Top",
                locations=PANE_LOCATIONS,
                shape_icon="label_down",
            ),
            _plot_row(
                "anyBuy",
                "Buy Signal Any Cross Up",
                color="#9400D3",
                plottype="shape_label_up",
                simple=True,
                location="Bottom",
                locations=PANE_LOCATIONS,
                shape_icon="label_up",
            ),
            _plot_row(
                "anySell",
                "Sell Signal Any Cross Down",
                color="#FFD700",
                plottype="shape_label_down",
                simple=True,
                location="Top",
                locations=PANE_LOCATIONS,
                shape_icon="label_down",
            ),
            {
                "kind": "bg",
                "key": "background",
                "label": "Background Highlights",
                "show_key": "show_background",
                "color0_key": "bg_gold",
                "color1_key": "bg_purple",
                "show0_key": "show_bg_gold",
                "show1_key": "show_bg_purple",
                "defaults": {
                    "show_background": True,
                    "show_bg_gold": True,
                    "show_bg_purple": True,
                    "bg_gold": "#ffd54f",
                    "bg_purple": "#9400D3",
                },
            },
            *OUTPUT_FIELDS,
        ],
    },
    "bvb": {
        "title": "BvB",
        "inputs": [
            {"key": "period", "label": "BvB Period", "type": "int", "default": 14, "min": 1},
            {"key": "bars_back", "label": "Nomralized bars back", "type": "int", "default": 120, "min": 1},
            {"key": "line_height", "label": "Line Height", "type": "int", "default": 80},
        ],
        "styles": [
            _plot_row("plot_00", "Plot", color="black", linestyle="solid", linewidth=1, plottype="columns"),
            {
                "kind": "palette",
                "key": "plot_00_palette",
                "label": "Plot Color 0 / Color 1",
                "show0_key": "show_plot_00_color0",
                "show1_key": "show_plot_00_color1",
                "defaults": {
                    "plot_00_color0": _norm_color("green"),
                    "plot_00_color1": _norm_color("red"),
                    "show_plot_00_color0": True,
                    "show_plot_00_color1": True,
                },
            },
            _plot_row("plot_01", "Plot", color="yellow", linestyle="solid", linewidth=4, plottype="circles"),
            *OUTPUT_FIELDS,
        ],
    },
    "gainz": {
        "title": "GainzAlgo Pro",
        "inputs": [
            {
                "key": "candle_stability",
                "label": "Candle Stability Index",
                "type": "float",
                "default": 0.5,
                "min": 0.0,
                "max": 1.0,
                "section": "TECHNICAL",
                "info": "Minimum body-to-range ratio required before a candle can print a signal.",
            },
            {
                "key": "rsi_index",
                "label": "RSI Index",
                "type": "int",
                "default": 50,
                "min": 0,
                "max": 100,
                "info": "RSI threshold used to confirm the signal direction.",
            },
            {
                "key": "candle_delta_len",
                "label": "Candle Delta Length",
                "type": "int",
                "default": 5,
                "min": 3,
                "info": "How many candles are compared when measuring the candle delta.",
            },
            {
                "key": "disable_repeating",
                "label": "Disable Repeating Signals",
                "type": "bool",
                "default": False,
                "info": "When on, a new signal is skipped while the previous signal is still in the same direction.",
            },
        ],
        "styles": [
            _plot_row(
                "plot_0",
                "BUY Signal",
                color="#1dff28",
                plottype="shape_label_up",
                simple=True,
                location="Absolute",
                locations=PRICE_LOCATIONS,
                shape_icon="label_up",
            ),
            _plot_row(
                "plot_1",
                "SELL Signal",
                color="#ff0000",
                plottype="shape_label_down",
                simple=True,
                location="Absolute",
                locations=PRICE_LOCATIONS,
                shape_icon="label_down",
            ),
            *OUTPUT_FIELDS,
        ],
    },
    "aieng": {
        "title": "EngulfingCandle",
        "inputs": [
            {
                "key": "rsi_source",
                "label": "rsi Source",
                "type": "choice",
                "default": "close",
                "choices": SOURCE_CHOICES,
            },
            {"key": "rsi_len", "label": "rsi Length", "type": "int", "default": 14, "min": 1},
            {"key": "ob", "label": "rsi Overbought Level", "type": "int", "default": 70},
            {"key": "os_", "label": "rsi Oversold Level", "type": "int", "default": 30},
        ],
        "styles": [
            _plot_row(
                "bullish",
                "Bullish",
                color="#4CAF50",
                plottype="shape_triangle_up",
                simple=True,
                location="Below bar",
                locations=PRICE_LOCATIONS,
                shape_icon="triangle_up",
            ),
            _plot_row(
                "bearish",
                "Bearish",
                color="#FF5252",
                plottype="shape_triangle_down",
                simple=True,
                location="Above bar",
                locations=PRICE_LOCATIONS,
                shape_icon="triangle_down",
            ),
            *OUTPUT_FIELDS,
        ],
    },
    "utbot": {
        "title": "UT Bot Alerts",
        "inputs": [
            {
                "key": "key_value",
                "label": "Key Vaule.",
                "type": "float",
                "default": 1.0,
                "info": "Sensitivity of the trailing stop. Higher values produce fewer signals.",
            },
            {"key": "atr_period", "label": "ATR Period", "type": "int", "default": 10, "min": 1},
            {
                "key": "heikin_ashi",
                "label": "Signals from Heikin Ashi Candles",
                "type": "bool",
                "default": False,
            },
        ],
        "styles": [
            {
                "kind": "bar_color",
                "key": "bar_color",
                "label": "Bar Color",
                "show_key": "show_bar_color",
                "color0_key": "bar_up",
                "color1_key": "bar_down",
                "show0_key": "show_bar_up",
                "show1_key": "show_bar_down",
                "defaults": {
                    "show_bar_color": True,
                    "show_bar_up": True,
                    "show_bar_down": True,
                    "bar_up": _norm_color("green"),
                    "bar_down": _norm_color("red"),
                },
            },
            _plot_row(
                "plot_1",
                "BUY",
                color="#4CAF50",
                plottype="shape_label_up",
                simple=True,
                location="Below bar",
                locations=PRICE_LOCATIONS,
                shape_icon="label_up",
            ),
            _plot_row(
                "plot_2",
                "SELL",
                color="#FF5252",
                plottype="shape_label_down",
                simple=True,
                location="Above bar",
                locations=PRICE_LOCATIONS,
                shape_icon="label_down",
            ),
            *OUTPUT_FIELDS,
        ],
    },
}

# Attach visibility to every schema + expand style defaults into flat keys
for _schema in SCHEMAS.values():
    _schema["visibility"] = list(VISIBILITY_FIELDS)
    flat_defaults: Dict[str, Any] = {}
    for item in _schema.get("styles", []):
        if isinstance(item, dict) and "defaults" in item:
            flat_defaults.update(item["defaults"])
    _schema["_style_defaults"] = flat_defaults


# Legacy key aliases so old user_settings.json / compute modules keep working
LEGACY_ALIASES: Dict[str, Dict[str, str]] = {
    "matrix": {
        "candle_up": "candle_color2",
        "candle_down": "candle_color1",
        "show_plot_up": "show_plot_00",
        "plot_up_color": "plot_00_color",
        "show_plot_down": "show_plot_01",
        "plot_down_color": "plot_01_color",
        "show_up_shape": "show_plot_02",
        "up_shape_color": "plot_02_color",
        "show_down_shape": "show_plot_03",
        "down_shape_color": "plot_03_color",
        "show_resistance": "show_plot_04",
        "resistance_color": "plot_04_color",
        "show_support": "show_plot_05",
        "support_color": "plot_05_color",
        "line_width": "plot_00_linewidth",
        "plot_up_type": "plot_00_plottype",
        "plot_down_type": "plot_01_plottype",
        "resistance_type": "plot_04_plottype",
        "support_type": "plot_05_plottype",
    },
    "tcg": {
        "show_plot": "show_plot_00",
        "plot_color0": "plot_00_color0",
        "plot_color1": "plot_00_color1",
        "show_bb_cross_down": "show_plot_01",
        "bb_cross_down_color": "plot_01_color",
        "show_bb_cross_up": "show_plot_02",
        "bb_cross_up_color": "plot_02_color",
        "show_bg_up": "show_plot_03",
        "bg_up_color": "plot_03_color",
        "show_bg_down": "show_plot_04",
        "bg_down_color": "plot_04_color",
        "plot_type": "plot_00_plottype",
    },
    "vtx": {
        "show_plot_vi_minus": "show_plot_00",
        "vi_minus_color": "plot_00_color",
        "show_plot_vi_plus": "show_plot_01",
        "vi_plus_color": "plot_01_color",
        "show_sro": "show_plot_02",
        "sro_color": "plot_02_color",
        "line_width": "plot_02_linewidth",
        "vi_minus_type": "plot_00_plottype",
        "vi_plus_type": "plot_01_plottype",
        "sro_type": "plot_02_plottype",
    },
    "eagles": {
        "show_k": "show_stochK",
        "k_color": "stochK_color",
        "show_d": "show_stochD",
        "d_color": "stochD_color",
        "show_k2": "show_stochK2",
        "k2_color": "stochK2_color",
        "show_d2": "show_stochD2",
        "d2_color": "stochD2_color",
        "show_upper": "show_upper",
        "upper_color": "upper_color",
        "show_lower": "show_lower",
        "lower_color": "lower_color",
        "mid_color": "middle_color",
        "buy_strict_color": "strictBuy_color",
        "sell_strict_color": "strictSell_color",
        "buy_any_color": "anyBuy_color",
        "sell_any_color": "anySell_color",
        "show_bg_highlights": "show_background",
        "line_width": "stochK_linewidth",
        "k_type": "stochK_plottype",
        "d_type": "stochD_plottype",
        "k2_type": "stochK2_plottype",
        "d2_type": "stochD2_plottype",
    },
    "bvb": {
        "show_hist": "show_plot_00",
        "hist_up": "plot_00_color0",
        "hist_down": "plot_00_color1",
        "show_dots": "show_plot_01",
        "dots_color": "plot_01_color",
        "line_width": "plot_01_linewidth",
        "hist_type": "plot_00_plottype",
        "dots_type": "plot_01_plottype",
    },
    "gainz": {
        "show_buy": "show_plot_0",
        "buy_color": "plot_0_color",
        "show_sell": "show_plot_1",
        "sell_color": "plot_1_color",
    },
    "aieng": {
        "show_bullish": "show_bullish",
        "bullish_color": "bullish_color",
        "show_bearish": "show_bearish",
        "bearish_color": "bearish_color",
    },
    "utbot": {
        "show_buy": "show_plot_1",
        "buy_color": "plot_1_color",
        "show_sell": "show_plot_2",
        "sell_color": "plot_2_color",
    },
}


def _defaults_for(key: str) -> Dict[str, Any]:
    schema = SCHEMAS[key]
    out: Dict[str, Any] = {}
    for field in schema.get("inputs", []):
        if "default" in field:
            out[field["key"]] = field["default"]
    for field in schema.get("visibility", []):
        if field.get("kind") == "range":
            out[field["key"]] = field.get("default", True)
            out[field["from_key"]] = field.get("default_from", field.get("min", 1))
            out[field["to_key"]] = field.get("default_to", field.get("max", 1))
        elif "default" in field:
            out[field["key"]] = field["default"]
    for field in schema.get("styles", []):
        if field.get("kind") in ("plot", "candles", "palette", "bg", "bar_color", "band", "color_check") and "defaults" in field:
            out.update(field["defaults"])
        elif "key" in field and "default" in field:
            out[field["key"]] = field["default"]
    # also apply style flat defaults
    out.update(schema.get("_style_defaults") or {})
    return out


def marker_position(location: Any, default: str = "below") -> str:
    """Map a Chartix location label onto below / above / absolute."""
    text = str(location or "").strip().lower().replace("_", " ")
    if text in ("above bar", "abovebar", "above", "top"):
        return "above"
    if text in ("below bar", "belowbar", "below", "bottom"):
        return "below"
    if text in ("absolute", "in bar", "inbar"):
        return "absolute"
    return default


def marker_shape(plottype: Any, default: str = "arrowUp") -> str:
    """Map a Chartix shape id onto a lightweight-charts marker shape.

    A generic stored value of ``shape`` keeps the indicator's own glyph.
    """
    text = str(plottype or "").strip().lower()
    if text in ("", "shape"):
        return default
    if "down" in text:
        return "arrowDown"
    if "up" in text:
        return "arrowUp"
    return default


_VIS_GROUP_LEGACY = {
    "visible_minutes": ("visible_1min", "visible_5min", "visible_15min", "visible_30min"),
    "visible_hours": ("visible_1h", "visible_2h", "visible_3h", "visible_4h"),
    "visible_days": ("visible_1d",),
    "visible_weeks": ("visible_1w",),
    "visible_months": ("visible_1mon", "visible_1m"),
}


def _promote_user_keys(ind_key: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Copy legacy keys onto the dialog keys before defaults are merged.

    Defaults already contain every new key. If we merged first, a saved
    `show_plot_up: false` would lose to the default `show_plot_00: true`.
    """
    out = dict(user)
    for old, new in (LEGACY_ALIASES.get(ind_key) or {}).items():
        if old in out and new not in out:
            out[new] = out[old]
    for group, legacy_keys in _VIS_GROUP_LEGACY.items():
        if group in out:
            continue
        present = [out[k] for k in legacy_keys if k in out]
        if present:
            out[group] = all(bool(v) for v in present)
    return out


def coerce_choice(value: Any, choices: List[Any]) -> Any:
    """Keep a saved value when it matches a choice, including 1h→60 and close→Close."""
    opts = list(choices or [])
    if not opts:
        return value
    if value in opts:
        return value
    text = str(value).strip()
    for opt in opts:
        if str(opt).lower() == text.lower():
            return opt
    mapped = {
        "1h": "60",
        "2h": "120",
        "3h": "180",
        "4h": "240",
        "1d": "D",
        "d": "D",
        "1w": "W",
        "w": "W",
        "1mon": "M",
        "1m": "M",
        "60min": "60",
        "daily": "D",
    }.get(text.lower())
    if mapped in opts:
        return mapped
    return opts[0]


def _apply_legacy_aliases(ind_key: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Keep dialog keys and legacy compute keys identical. Dialog keys win."""
    aliases = LEGACY_ALIASES.get(ind_key) or {}
    out = dict(cfg)
    for old, new in aliases.items():
        if new in out:
            out[old] = out[new]
        elif old in out:
            out[new] = out[old]
    # convenience mirrors for compute
    if ind_key == "matrix":
        out.setdefault("candle_up", out.get("candle_color2", "#008000"))
        out.setdefault("candle_down", out.get("candle_color1", "#ff0000"))
        out.setdefault("plot_up_color", out.get("plot_00_color"))
        out.setdefault("plot_down_color", out.get("plot_01_color"))
        out.setdefault("up_shape_color", out.get("plot_02_color"))
        out.setdefault("down_shape_color", out.get("plot_03_color"))
        out.setdefault("resistance_color", out.get("plot_04_color"))
        out.setdefault("support_color", out.get("plot_05_color"))
        out.setdefault("show_plot_up", out.get("show_plot_00", True))
        out.setdefault("show_plot_down", out.get("show_plot_01", True))
        out.setdefault("show_up_shape", out.get("show_plot_02", True))
        out.setdefault("show_down_shape", out.get("show_plot_03", True))
        out.setdefault("show_resistance", out.get("show_plot_04", True))
        out.setdefault("show_support", out.get("show_plot_05", True))
        out.setdefault("line_width", out.get("plot_00_linewidth", 2))
    if ind_key == "tcg":
        out.setdefault("plot_color0", out.get("plot_00_color0", out.get("plot_00_color", "#ef5350")))
        out.setdefault("plot_color1", out.get("plot_00_color1", "#008000"))
        out.setdefault("bb_cross_down_color", out.get("plot_01_color"))
        out.setdefault("bb_cross_up_color", out.get("plot_02_color"))
        out.setdefault("bg_up_color", out.get("plot_03_color"))
        out.setdefault("bg_down_color", out.get("plot_04_color"))
        out.setdefault("show_bb_cross_down", out.get("show_plot_01", True))
        out.setdefault("show_bb_cross_up", out.get("show_plot_02", True))
        out.setdefault("show_bg_up", out.get("show_plot_03", True))
        out.setdefault("show_bg_down", out.get("show_plot_04", True))
        out.setdefault("show_plot", out.get("show_plot_00", True))
    if ind_key == "vtx":
        src = str(out.get("source", "Close"))
        out["source"] = src
        out.setdefault("show_plot_vi_minus", out.get("show_plot_00", True))
        out.setdefault("show_plot_vi_plus", out.get("show_plot_01", True))
        out.setdefault("show_sro", out.get("show_plot_02", True))
        out.setdefault("vi_minus_color", out.get("plot_00_color"))
        out.setdefault("vi_plus_color", out.get("plot_01_color"))
        out.setdefault("sro_color", out.get("plot_02_color"))
        out.setdefault("line_width", out.get("plot_02_linewidth", 2))
    if ind_key == "eagles":
        out.setdefault("show_k", out.get("show_stochK", True))
        out.setdefault("show_d", out.get("show_stochD", True))
        out.setdefault("k_color", out.get("stochK_color"))
        out.setdefault("d_color", out.get("stochD_color"))
        out.setdefault("show_k2", out.get("show_stochK2", True))
        out.setdefault("show_d2", out.get("show_stochD2", True))
        out.setdefault("k2_color", out.get("stochK2_color"))
        out.setdefault("d2_color", out.get("stochD2_color"))
        out.setdefault("upper_color", out.get("upper_color"))
        out.setdefault("lower_color", out.get("lower_color"))
        out.setdefault("mid_color", out.get("middle_color"))
        out.setdefault("buy_strict_color", out.get("strictBuy_color"))
        out.setdefault("sell_strict_color", out.get("strictSell_color"))
        out.setdefault("buy_any_color", out.get("anyBuy_color"))
        out.setdefault("sell_any_color", out.get("anySell_color"))
        out.setdefault("show_bg_highlights", out.get("show_background", True))
        out.setdefault("line_width", out.get("stochK_linewidth", 3))
        out.setdefault("k_type", out.get("stochK_plottype", "line"))
        out.setdefault("d_type", out.get("stochD_plottype", "line"))
    if ind_key == "bvb":
        out.setdefault("show_hist", out.get("show_plot_00", True))
        out.setdefault("hist_up", out.get("plot_00_color0", "#008000"))
        out.setdefault("hist_down", out.get("plot_00_color1", "#ff0000"))
        out.setdefault("show_dots", out.get("show_plot_01", True))
        out.setdefault("dots_color", out.get("plot_01_color", "#ffff00"))
        out.setdefault("line_width", out.get("plot_01_linewidth", 4))
        out.setdefault("hist_type", out.get("plot_00_plottype", "columns"))
    if ind_key == "gainz":
        out.setdefault("show_buy", out.get("show_plot_0", True))
        out.setdefault("buy_color", out.get("plot_0_color"))
        out.setdefault("show_sell", out.get("show_plot_1", True))
        out.setdefault("sell_color", out.get("plot_1_color"))
    if ind_key == "aieng":
        out.setdefault("show_bullish", out.get("show_bullish", True))
        out.setdefault("bullish_color", out.get("bullish_color"))
        out.setdefault("show_bearish", out.get("show_bearish", True))
        out.setdefault("bearish_color", out.get("bearish_color"))
    if ind_key == "utbot":
        out.setdefault("show_buy", out.get("show_plot_1", True))
        out.setdefault("buy_color", out.get("plot_1_color"))
        out.setdefault("show_sell", out.get("show_plot_2", True))
        out.setdefault("sell_color", out.get("plot_2_color"))
        # Keep trail if user/settings asked for it; Chartix dialog has no trail toggle.
        out.setdefault("show_trail", False)  # Chartix has Buy/Sell only, no trail plot
    return out


_TF_SLOT = {
    "1min": ("minutes", 1),
    "2min": ("minutes", 2),
    "3min": ("minutes", 3),
    "5min": ("minutes", 5),
    "10min": ("minutes", 10),
    "15min": ("minutes", 15),
    "30min": ("minutes", 30),
    "1h": ("hours", 1),
    "2h": ("hours", 2),
    "3h": ("hours", 3),
    "4h": ("hours", 4),
    "1d": ("days", 1),
    "d": ("days", 1),
    "1day": ("days", 1),
    "1w": ("weeks", 1),
    "w": ("weeks", 1),
    "1week": ("weeks", 1),
    "1mon": ("months", 1),
    "1m": ("months", 1),
    "m": ("months", 1),
    "1month": ("months", 1),
}


def _tf_slot(tf: str):
    t = (tf or "").lower()
    if t in _TF_SLOT:
        return _TF_SLOT[t]
    if t.endswith("min"):
        try:
            return ("minutes", int(t[:-3]))
        except ValueError:
            return ("minutes", 1)
    if t.endswith("h"):
        try:
            return ("hours", int(t[:-1]))
        except ValueError:
            return ("hours", 1)
    return None


def is_visible_on_tf(cfg: Dict[str, Any], tf: str) -> bool:
    """Map app TF labels onto Chartix interval groups and their from/to range."""
    slot = _tf_slot(tf)
    if slot is None:
        key = f"visible_{tf}"
        if key in cfg:
            return bool(cfg.get(key, True))
        return True
    group, value = slot
    if not bool(cfg.get(f"visible_{group}", True)):
        return False
    lo_lim, hi_lim = _VIS_LIMITS.get(group, (1, 10**9))
    try:
        lo = int(cfg.get(f"visible_{group}_from", lo_lim))
    except (TypeError, ValueError):
        lo = lo_lim
    try:
        hi = int(cfg.get(f"visible_{group}_to", hi_lim))
    except (TypeError, ValueError):
        hi = hi_lim
    if lo > hi:
        lo, hi = hi, lo
    return lo <= int(value) <= hi


def default_all() -> Dict[str, Dict[str, Any]]:
    return {key: _defaults_for(key) for key in SCHEMAS}


def load_settings() -> Dict[str, Dict[str, Any]]:
    base = default_all()
    if not SETTINGS_FILE.exists():
        return {k: _apply_legacy_aliases(k, v) for k, v in base.items()}
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {k: _apply_legacy_aliases(k, v) for k, v in base.items()}
    if not isinstance(raw, dict):
        return {k: _apply_legacy_aliases(k, v) for k, v in base.items()}
    for key, defaults in base.items():
        user = raw.get(key) or {}
        if not isinstance(user, dict):
            continue
        promoted = _promote_user_keys(key, user)
        merged = copy.deepcopy(defaults)
        for k, v in promoted.items():
            merged[k] = v
        base[key] = _apply_legacy_aliases(key, merged)
    return base


def save_settings(settings: Dict[str, Dict[str, Any]]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    clean = {}
    defaults = default_all()
    for key, vals in settings.items():
        if key not in defaults:
            continue
        # persist all known defaults keys + any style keys present
        keys = set(defaults[key].keys()) | set(vals.keys())
        clean[key] = {k: vals.get(k, defaults[key].get(k)) for k in keys if k in defaults[key] or k in vals}
    SETTINGS_FILE.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")


def schema_fields(key: str, section: str) -> List[Dict[str, Any]]:
    """Return fields for Inputs/Visibility (flat) or Style (structured rows)."""
    return list(SCHEMAS.get(key, {}).get(section, []))


def expand_style_widgets(ind_key: str) -> List[Dict[str, Any]]:
    """Flatten style schema into renderable widget descriptors for settings_ui."""
    items = []
    for field in schema_fields(ind_key, "styles"):
        kind = field.get("kind")
        if kind in ("plot", "candles", "palette", "bg", "bar_color", "band", "color_check"):
            items.append(field)
        else:
            items.append({"kind": "field", **field})
    return items
