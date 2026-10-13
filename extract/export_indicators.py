# -*- coding: utf-8 -*-
"""
Export Chartix indicator values computed from the downloaded OHLCV CSVs.

Chartix computes its indicators in the browser (there is no server API for them),
so the values are produced by the exact Python port in chart/indicators/chartix_exact.py.

Output: data/indicator_data/<ticker>/<tf>_<adj>.csv — OHLCV + one column per plot,
named "<indicator>.<plot>". Signal columns are 1 on the signal bar and empty elsewhere.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chart import data_loader as dl  # noqa: E402
from chart import indicator_settings as iset  # noqa: E402
from chart.indicators import (  # noqa: E402
    ai_engulfing,
    bulls_v_bears,
    chartix_exact,
    eagles_nest,
    gainzalgo_approx,
    matrix_series,
    tcg_ai_tools,
    ut_bot,
    vtx,
)

OUT_DIR = PROJECT_ROOT / "data" / "indicator_data"

# settings key -> (module, {chartix plot id: exported column name}); unlisted ids are dropped.
INDICATORS = {
    "matrix": (
        matrix_series,
        {
            "ms_up": "up",
            "ms_down": "down",
            "candle_open": "candle_low",
            "candle_close": "candle_high",
            "candle_color": "candle_green",
            "plot_00": "zone_sup",
            "plot_01": "zone_res",
            "plot_02": "ob_mark",
            "plot_03": "os_mark",
            "plot_04": "ob_level",
            "plot_05": "os_level",
        },
    ),
    "tcg": (
        tcg_ai_tools,
        {
            "plot_00c": "trend_bull",
            "plot_01": "cross_upper_bb",
            "plot_02": "cross_lower_bb",
            "plot_03": "rsi_overbought",
            "plot_04": "rsi_oversold",
            "rsi": "rsi",
            "bb_upper": "bb_upper",
            "bb_lower": "bb_lower",
        },
    ),
    "vtx": (vtx, {"plot_02": "value", "plot_00": "cross_20", "plot_01": "cross_80"}),
    "eagles": (
        eagles_nest,
        {
            "stochK": "k",
            "stochD": "d",
            "stochK2": "k2",
            "stochD2": "d2",
            "strictBuy": "strict_buy",
            "strictSell": "strict_sell",
            "anyBuy": "any_buy",
            "anySell": "any_sell",
            "background": "background_buy",
        },
    ),
    "bvb": (bulls_v_bears, {"plot_00": "value", "plot_00c": "red", "plot_01": "level_dot"}),
    "gainz": (gainzalgo_approx, {"plot_0": "buy", "plot_1": "sell"}),
    "aieng": (ai_engulfing, {"bullish": "buy", "bearish": "sell", "rsi": "rsi"}),
    "utbot": (ut_bot, {"plot_0": "bar_red", "plot_1": "buy", "plot_2": "sell", "trail": "trail"}),
}

# Chartix encodes the plot markers above as "0 = drawn"; flip them to 1 so a signal is always 1.
_ZERO_MEANS_ON = {
    ("tcg", "plot_01"),
    ("tcg", "plot_02"),
    ("tcg", "plot_03"),
    ("tcg", "plot_04"),
}


def _htf_loader_for(ticker: str, adj: str):
    def load(res: str) -> Optional[pd.DataFrame]:
        tf = chartix_exact.resolution_to_tf(res)
        if not tf:
            return None
        try:
            return dl.load_ohlcv(ticker, tf, adj)
        except (FileNotFoundError, ValueError):
            return None

    return load


def indicator_frame(
    df: pd.DataFrame, ticker: str, tf: str, adj: str, settings: Dict[str, Dict], keys: List[str]
) -> pd.DataFrame:
    out = df[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True).copy()
    for key in keys:
        mod, columns = INDICATORS[key]
        cfg = iset._apply_legacy_aliases(key, dict(settings.get(key) or {}))
        cfg["_chart_tf"] = tf
        cfg["_htf_loader"] = _htf_loader_for(ticker, adj)
        plots = mod.chartix_plots(df, cfg).reset_index(drop=True)
        for pid, name in columns.items():
            values = plots[pid]
            if (key, pid) in _ZERO_MEANS_ON:
                values = values.where(values != 0, 1.0)
            out[f"{key}.{name}"] = values.to_numpy()
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Chartix indicator data to CSV")
    parser.add_argument("--tickers", nargs="*", help="tickers (default: every folder in data/csv_data)")
    parser.add_argument("--tf", nargs="*", help=f"timeframes (default: all). Choices: {' '.join(dl.TF_LABELS)}")
    parser.add_argument("--adj", nargs="*", default=None, help=f"adj modes (default: all). Choices: {' '.join(dl.ADJ_LABELS)}")
    parser.add_argument("--indicators", nargs="*", choices=list(INDICATORS), help="default: all 8")
    parser.add_argument("--defaults", action="store_true", help="use Chartix default inputs instead of chart/user_settings.json")
    parser.add_argument("--out", default=str(OUT_DIR), help="output folder")
    args = parser.parse_args()

    settings = iset.default_all() if args.defaults else iset.load_settings()
    keys = args.indicators or list(INDICATORS)
    out_root = Path(args.out)
    tickers = args.tickers
    if not tickers:
        tickers = sorted(p.name for p in dl.CSV_ROOT.iterdir() if p.is_dir()) if dl.CSV_ROOT.exists() else []
    names = dl.ticker_to_name()

    written = failed = 0
    for ticker in tickers:
        for tf, adj in dl.list_available_files(ticker):
            if args.tf and tf not in args.tf or args.adj and adj not in args.adj:
                continue
            try:
                df = dl.load_ohlcv(ticker, tf, adj)
                frame = indicator_frame(df, ticker, tf, adj, settings, keys)
                path = out_root / ticker / f"{tf}_{adj}.csv"
                path.parent.mkdir(parents=True, exist_ok=True)
                frame.to_csv(path, index=False, float_format="%.6f")
                written += 1
                print(f"[OK]   {ticker} {names.get(ticker, '')} {tf}_{adj}: {len(frame)} bars -> {path}", flush=True)
            except Exception as exc:  # keep going on bad files
                failed += 1
                print(f"[FAIL] {ticker} {tf}_{adj}: {exc}", flush=True)

    print(f"\nDone: {written} files written, {failed} failed. Folder: {out_root}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
