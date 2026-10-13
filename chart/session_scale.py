# -*- coding: utf-8 -*-
"""Compress calendar gaps so Iranian session bars sit edge-to-edge on the chart."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

# Nominal bar step used only for evenly spaced synthetic unix times
TF_SECONDS = {
    "1min": 60,
    "2min": 120,
    "3min": 180,
    "5min": 300,
    "10min": 600,
    "15min": 900,
    "30min": 1800,
    "45min": 2700,
    "1h": 3600,
    "2h": 7200,
    "3h": 10800,
    "1d": 86400,
    "1w": 604800,
    "1mon": 2_592_000,
}

# Fixed epoch so synthetic times stay far from 1970 if a label lookup misses
_SYNTH_BASE = 1_700_000_000


def _real_key(ts) -> int:
    return int(pd.Timestamp(ts).value)


def _format_label(ts: pd.Timestamp, tf: str) -> str:
    t = pd.Timestamp(ts)
    if tf in ("1d", "1w", "1mon"):
        return t.strftime("%d %b '%y")
    if tf in ("1h", "2h", "3h"):
        return t.strftime("%d %b '%y %H:%M")
    return t.strftime("%d %b '%y %H:%M")


def compress_session(
    df: pd.DataFrame, tf: str
) -> Tuple[pd.DataFrame, Dict[int, str], Dict[int, pd.Timestamp]]:
    """
    Replace wall-clock times with sequential synthetic times (no overnight/weekend gaps).

    Returns:
      compressed_df, label_map[synth_unix] -> display string,
      real_ns_key -> synthetic Timestamp
    """
    if df is None or df.empty:
        return df, {}, {}

    out = df.copy().reset_index(drop=True)
    real = pd.to_datetime(out["time"], errors="coerce").astype("datetime64[ns]")
    out = out.loc[real.notna()].copy()
    real = real.loc[real.notna()].reset_index(drop=True)
    out = out.reset_index(drop=True)

    step = int(TF_SECONDS.get(tf, 60))
    n = len(out)
    synth_unix = (_SYNTH_BASE + np.arange(n, dtype=np.int64) * step).astype(np.int64)
    synth_ts = pd.Series(pd.to_datetime(synth_unix, unit="s").astype("datetime64[ns]"), index=out.index)
    out["time"] = synth_ts

    label_map: Dict[int, str] = {}
    real_to_synth: Dict[int, pd.Timestamp] = {}
    for i in range(n):
        label_map[int(synth_unix[i])] = _format_label(real.iloc[i], tf)
        real_to_synth[_real_key(real.iloc[i])] = pd.Timestamp(synth_ts.iloc[i])

    return out, label_map, real_to_synth


def remap_frame(frame: Optional[pd.DataFrame], real_to_synth: Dict[int, pd.Timestamp]) -> Optional[pd.DataFrame]:
    if frame is None or frame.empty or not real_to_synth:
        return frame
    out = frame.copy()
    mapped = pd.to_datetime(out["time"], errors="coerce").map(
        lambda t: real_to_synth.get(_real_key(t)) if pd.notna(t) else None
    )
    out["time"] = mapped
    return out.dropna(subset=["time"]).reset_index(drop=True)


def remap_time_value(t, real_to_synth: Dict[int, pd.Timestamp]):
    if t is None or (isinstance(t, float) and np.isnan(t)):
        return None
    return real_to_synth.get(_real_key(t))
