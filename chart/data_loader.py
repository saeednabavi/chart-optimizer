# -*- coding: utf-8 -*-
"""Load watchlist metadata and OHLCV CSV files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_FILE = PROJECT_ROOT / "symbols" / "watchlist.json"
CSV_ROOT = PROJECT_ROOT / "data" / "csv_data"

TF_LABELS = [
    "1min",
    "2min",
    "3min",
    "5min",
    "10min",
    "15min",
    "30min",
    "45min",
    "1h",
    "2h",
    "3h",
    "1d",
    "1w",
    "1mon",
]

ADJ_LABELS = ["adjusted", "unadjusted", "performance"]

# Chartix has no 2/3/10-minute history; build these from the 1min CSV (left-labelled, like its 5min bars).
DERIVED_TF_MINUTES = {"2min": 2, "3min": 3, "10min": 10}
_DERIVED_SOURCE_TF = "1min"
_derived_cache: Dict[Tuple[str, str, str], Tuple[float, pd.DataFrame]] = {}


def load_watchlist() -> List[Dict[str, str]]:
    if not WATCHLIST_FILE.exists():
        return []
    data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    return list(data.get("symbols") or [])


def name_to_ticker(watchlist: Optional[List[Dict[str, str]]] = None) -> Dict[str, str]:
    wl = watchlist if watchlist is not None else load_watchlist()
    return {s["name"]: s["ticker"] for s in wl if s.get("name") and s.get("ticker")}


def ticker_to_name(watchlist: Optional[List[Dict[str, str]]] = None) -> Dict[str, str]:
    wl = watchlist if watchlist is not None else load_watchlist()
    return {s["ticker"]: s["name"] for s in wl if s.get("name") and s.get("ticker")}


def list_available_files(ticker: str) -> List[Tuple[str, str]]:
    """Return list of (tf, adj) available for ticker."""
    folder = CSV_ROOT / ticker
    if not folder.exists():
        return []
    out: List[Tuple[str, str]] = []
    for p in folder.glob("*.csv"):
        if p.name.lower() == "info.csv":
            continue
        stem = p.stem  # e.g. 1d_adjusted
        if "_" not in stem:
            continue
        tf, adj = stem.rsplit("_", 1)
        if adj in ADJ_LABELS:
            out.append((tf, adj))
    have = set(out)
    for adj in ADJ_LABELS:
        if (_DERIVED_SOURCE_TF, adj) in have:
            for tf in DERIVED_TF_MINUTES:
                if (tf, adj) not in have:
                    out.append((tf, adj))
    return sorted(out)


def available_timeframes(ticker: str, adj: str = "adjusted") -> List[str]:
    files = list_available_files(ticker)
    tfs = sorted({tf for tf, a in files if a == adj}, key=lambda x: TF_LABELS.index(x) if x in TF_LABELS else 99)
    return tfs


def _resample_minutes(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    out = (
        df.set_index("time")
        .resample(f"{minutes}min", closed="left", label="left")
        .agg(agg)
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )
    out["time"] = out["time"].astype("datetime64[ns]")
    return out


def _load_derived(ticker: str, timeframe: str, adj: str) -> pd.DataFrame:
    src = CSV_ROOT / ticker / f"{_DERIVED_SOURCE_TF}_{adj}.csv"
    if not src.exists():
        raise FileNotFoundError(f"CSV not found: {src} (needed to build {timeframe})")
    key = (ticker, timeframe, adj)
    mtime = src.stat().st_mtime
    cached = _derived_cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1].copy()
    df = _resample_minutes(load_ohlcv(ticker, _DERIVED_SOURCE_TF, adj), DERIVED_TF_MINUTES[timeframe])
    _derived_cache[key] = (mtime, df)
    return df.copy()


def data_mtime(ticker: str, timeframe: str, adj: str = "adjusted") -> Optional[float]:
    """Modification time of the CSV behind this series (the 1min file for derived TFs)."""
    path = CSV_ROOT / ticker / f"{timeframe}_{adj}.csv"
    if not path.exists() and timeframe in DERIVED_TF_MINUTES:
        path = CSV_ROOT / ticker / f"{_DERIVED_SOURCE_TF}_{adj}.csv"
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def load_ohlcv(ticker: str, timeframe: str, adj: str = "adjusted") -> pd.DataFrame:
    path = CSV_ROOT / ticker / f"{timeframe}_{adj}.csv"
    if not path.exists():
        if timeframe in DERIVED_TF_MINUTES:
            return _load_derived(ticker, timeframe, adj)
        raise FileNotFoundError(f"CSV not found: {path}")
    df = pd.read_csv(path)
    if "time" not in df.columns:
        raise ValueError(f"No time column in {path}")
    # Force ns resolution — Pandas 3 defaults to us, which breaks lightweight-charts time math
    df["time"] = pd.to_datetime(df["time"], errors="coerce").astype("datetime64[ns]")
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time")
    df = df.drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)
    return df


def default_selection() -> Tuple[str, str, str, str]:
    """Return (display_name, ticker, timeframe, adj)."""
    wl = load_watchlist()
    if not wl:
        raise RuntimeError("Watchlist is empty")
    name = wl[0]["name"]
    ticker = wl[0]["ticker"]
    adj = "adjusted"
    tfs = available_timeframes(ticker, adj)
    if not tfs:
        # try any adj
        files = list_available_files(ticker)
        if files:
            tf, adj = files[0]
            return name, ticker, tf, adj
        return name, ticker, "1d", adj
    # prefer 1d then 1h then first
    for prefer in ("1d", "1h", "30min"):
        if prefer in tfs:
            return name, ticker, prefer, adj
    return name, ticker, tfs[0], adj
