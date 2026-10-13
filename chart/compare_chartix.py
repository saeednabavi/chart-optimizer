# -*- coding: utf-8 -*-
"""
Compare local indicator last values vs Chartix legend snapshots.

Chartix reference (OANDA_XAUUSD 1D, scraped live):
  MS: -205.46 / -153.94 / 310.89 / -269.16
  TCG: 0.00 (trend)
  VTX: 10.27
  Eagles: K≈16.39 D≈16.56 upper=80 lower=20 mid=50
  BvB: -23.26
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from chart import data_loader as dl
from chart import indicator_settings as iset
from chart.indicators import (
    ai_engulfing,
    bulls_v_bears,
    eagles_nest,
    gainzalgo_approx,
    matrix_series,
    tcg_ai_tools,
    ut_bot,
    vtx,
)

# Live Chartix legend values (XAUUSD 1D) — used for cross-check shape/order
CHARTIX_LEGEND = {
    "MS": {"params": "5 50 100 16 200 -200", "values": [-205.46, -205.46, -153.94, -153.94, 310.89, -269.16]},
    "TCG AI Tools": {"params": "close 20 2 70 30 14", "values": [0.0]},
    "VTX Oscillator": {"params": "14 Close", "values": [10.27]},
    "Eagles Nest - CHARTIX": {"params": "14 3 3 80 20", "values": [16.39, 16.56, 80.0, 20.0, 50.0]},
    "BvB": {"params": "14 120 80", "values": [-23.26]},
}


def _last_num(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return float(s.iloc[-1])


def run_on_symbol(ticker: str, tf: str = "1d", adj: str = "adjusted") -> dict:
    df = dl.load_ohlcv(ticker, tf, adj)
    settings = iset.load_settings()
    out = {"ticker": ticker, "tf": tf, "adj": adj, "bars": len(df), "indicators": {}}

    cases = [
        ("matrix", "MS", matrix_series),
        ("tcg", "TCG AI Tools", tcg_ai_tools),
        ("vtx", "VTX Oscillator", vtx),
        ("eagles", "Eagles Nest - CHARTIX", eagles_nest),
        ("bvb", "BvB", bulls_v_bears),
        ("gainz", "GainzAlgo Pro", gainzalgo_approx),
        ("aieng", "EngulfingCandle", ai_engulfing),
        ("utbot", "UT Bot Alerts", ut_bot),
    ]

    for key, title, mod in cases:
        cfg = iset._apply_legacy_aliases(key, dict(settings.get(key) or iset.default_all()[key]))
        res = mod.compute(df, cfg)
        vals = {}
        for line in res.get("lines") or []:
            data = line.get("data")
            if data is not None and not data.empty:
                cols = [c for c in data.columns if c != "time"]
                if cols:
                    vals[line["name"]] = _last_num(data[cols[0]])
        for hist in res.get("histograms") or []:
            data = hist.get("data")
            if data is not None and not data.empty:
                cols = [c for c in data.columns if c != "time"]
                if cols:
                    vals[hist["name"]] = _last_num(data[cols[0]])
        if res.get("candles") and res["candles"].get("data") is not None:
            c = res["candles"]["data"]
            if not c.empty:
                vals["candle_close"] = float(c["close"].iloc[-1])
        vals["markers"] = len(res.get("markers") or [])
        vals["title"] = res.get("title")
        ref = CHARTIX_LEGEND.get(title)
        compare = None
        if ref and title == "MS":
            ms = matrix_series.chartix_plots(df, cfg)
            local = [_last_num(ms[c]) for c in ("ms_up", "ms_down", "plot_01", "plot_00")]
            compare = {
                "chartix_sample_xauusd": ref["values"],
                "local_last": local,
                "note": "XAUUSD≠عیار — compare shape/order locally; absolute values differ by symbol",
            }
        if ref and title == "BvB":
            compare = {
                "chartix_sample_xauusd": ref["values"],
                "local_last": [_last_num(bulls_v_bears.chartix_plots(df, cfg)["plot_00"])],
                "note": "Different symbol; check sign/magnitude scale",
            }
        if ref and title == "VTX Oscillator":
            compare = {
                "chartix_sample_xauusd": ref["values"],
                "local_last": [_last_num(vtx.chartix_plots(df, cfg)["plot_02"])],
            }
        if ref and title == "Eagles Nest - CHARTIX":
            compare = {
                "chartix_sample_xauusd": ref["values"],
                "local_last": [vals.get("Eagles_K"), vals.get("Eagles_D")],
            }
        out["indicators"][title] = {"values": vals, "compare": compare, "ok": True}
    return out


def main():
    # Prefer عیار 1d (watchlist) — Chartix scrape was XAUUSD for reference only
    ticker = "BRS00927"
    try:
        result = run_on_symbol(ticker, "1d", "adjusted")
    except FileNotFoundError:
        # fallback any available
        names = dl.load_watchlist()
        ticker = names[0]["ticker"]
        result = run_on_symbol(ticker, "1d", "adjusted")

    # Schema parity quick check
    schema_ok = True
    expected_inputs = {
        "MS": ["Smoother", "SupResPeriod", "SupResPercentage", "PricePeriod", "Overbought", "Oversold", "Show OB/OS", "Dynamic zones"],
        "TCG AI Tools": ["Price", "Bollinger length", "Bollinger Multiplier", "Overbought", "Oversold", "Length"],
        "VTX Oscillator": ["Length", "Source"],
        "UT Bot Alerts": ["Key Vaule.", "ATR Period", "Signals from Heikin Ashi Candles"],
        "BvB": ["BvB Period", "Nomralized bars back", "Line Height"],
    }
    schema_report = {}
    for key, schema in iset.SCHEMAS.items():
        labels = [f["label"] for f in schema["inputs"]]
        title = schema["title"]
        exp = expected_inputs.get(title)
        miss = [x for x in (exp or []) if x not in labels]
        style_labels = []
        for f in schema["styles"]:
            if f.get("kind") in ("plot", "candles", "band", "bg", "bar_color") or f.get("key") in (
                "show_hlines_bg",
                "precision",
            ):
                style_labels.append(f.get("label"))
        schema_report[title] = {"inputs": labels, "missing": miss, "styles": style_labels}
        if miss:
            schema_ok = False

    result["schema_ok"] = schema_ok
    result["schema"] = schema_report

    out_path = Path(__file__).resolve().parent / "compare_report.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("schema_ok=", schema_ok)
    print("symbol=", result["ticker"], "bars=", result["bars"])
    for title, info in result["indicators"].items():
        vals = {k: v for k, v in info["values"].items() if k not in ("markers", "title")}
        print(f"- {title}: {vals} markers={info['values'].get('markers')}")
    print("wrote", out_path)


if __name__ == "__main__":
    main()
