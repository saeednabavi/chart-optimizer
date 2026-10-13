# -*- coding: utf-8 -*-
"""How close a set of signal bars lands to the real tops (sell) or bottoms (buy).

Each target pivot owns a zone: from the middle of the leg before it to the middle of the leg after it.
A signal inside a zone scores how near its bar came to the pivot price (low for buy, high for sell),
relative to the size of the leg the signal sits on:

    buy  : q = 1 - (low / bottom - 1) / (REACH * (top / bottom - 1))
    sell : q = 1 - (top / high - 1)   / (REACH * (top / bottom - 1))

So q = 1 at the exact extreme and 0 once price is REACH (half) of the leg away. A signal outside every
target zone scores 0.
Signals near the still-unconfirmed last pivot are ignored (neither good nor bad).

precision = mean q of all signals, coverage = mean over pivots of the best q in its zone,
score = 2 * precision * coverage / (precision + coverage).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

HIT_Q = 0.5
REACH = 0.5


@dataclass
class Segment:
    lo: int
    hi: int  # exclusive


class Scorer:
    def __init__(self, df: pd.DataFrame, swings: pd.DataFrame, level: str, side: str):
        """``swings`` from chart.swings.find_swings; level 'major' or 'minor'; side 'buy' or 'sell'."""
        self.n = len(df)
        self.side = side
        self.close = df["close"].to_numpy(dtype=float)
        touch = df["low" if side == "buy" else "high"].to_numpy(dtype=float)
        sw = swings if level == "minor" else swings[swings["level"] == "major"]
        sw = sw.reset_index(drop=True)
        target_kind = "bottom" if side == "buy" else "top"

        self.quality = np.zeros(self.n)          # q of a signal on each bar
        self.zone = np.full(self.n, -1, dtype=np.int64)  # target pivot index owning the bar
        self.pivot_bar = []
        self.pivot_price = []
        bars = sw["bar"].to_numpy(dtype=np.int64)
        kinds = sw["kind"].to_numpy()
        prices = sw["price"].to_numpy(dtype=float)
        confirmed = sw["confirmed"].to_numpy(dtype=bool)

        for i in range(len(sw)):
            if kinds[i] != target_kind:
                continue
            b, px = int(bars[i]), float(prices[i])
            prev_b = int(bars[i - 1]) if i > 0 else None
            next_b = int(bars[i + 1]) if i + 1 < len(sw) else None
            start = (prev_b + b) // 2 + 1 if prev_b is not None else 0
            end = (b + next_b) // 2 if next_b is not None else self.n - 1
            if not confirmed[i]:
                self.quality[start:end + 1] = np.nan
                continue
            pid = len(self.pivot_bar)
            self.pivot_bar.append(b)
            self.pivot_price.append(px)
            for lo, hi, other in ((start, b, prices[i - 1] if prev_b is not None else None),
                                  (b, end, prices[i + 1] if next_b is not None else None)):
                if hi < lo:
                    continue
                seg = slice(lo, hi + 1)
                c = touch[seg]
                if other is None:
                    # No neighbour pivot: measure against the farthest price reached on that side.
                    other = c.max() if side == "buy" else c.min()
                if side == "buy":
                    leg = other / px - 1
                    dist = c / px - 1
                else:
                    leg = px / other - 1
                    dist = px / c - 1
                q = 1 - dist / (REACH * leg) if leg > 0 else np.zeros_like(c)
                self.quality[seg] = np.clip(q, 0.0, 1.0)
                self.zone[seg] = pid
        self.pivot_bar = np.asarray(self.pivot_bar, dtype=np.int64)
        self.pivot_price = np.asarray(self.pivot_price, dtype=float)

    def segment_pivots(self, seg: Segment) -> np.ndarray:
        return np.flatnonzero((self.pivot_bar >= seg.lo) & (self.pivot_bar < seg.hi))

    def score(self, signal: np.ndarray, seg: Optional[Segment] = None) -> float:
        return self.evaluate(signal, seg, detail=False)["score"]

    def evaluate(self, signal: np.ndarray, seg: Optional[Segment] = None, detail: bool = True) -> Dict[str, float]:
        seg = seg or Segment(0, self.n)
        idx = np.flatnonzero(signal[seg.lo:seg.hi]) + seg.lo
        q = self.quality[idx]
        keep = ~np.isnan(q)
        idx, q = idx[keep], q[keep]
        piv = self.segment_pivots(seg)
        n_sig, n_piv = len(idx), len(piv)
        best = np.zeros(len(self.pivot_bar))
        best_bar = np.full(len(self.pivot_bar), -1, dtype=np.int64)
        z = self.zone[idx]
        for s, zz, qq in zip(idx, z, q):
            if zz >= 0 and qq > best[zz]:
                best[zz] = qq
                best_bar[zz] = s
        precision = float(q.mean()) if n_sig else 0.0
        coverage = float(best[piv].mean()) if n_piv else 0.0
        score = 2 * precision * coverage / (precision + coverage) if precision + coverage > 0 else 0.0
        out = {"score": score, "precision": precision, "coverage": coverage}
        if not detail:
            return out
        caught = piv[best[piv] >= HIT_Q]
        lags = best_bar[caught] - self.pivot_bar[caught]
        sig_close = self.close[best_bar[caught]]
        px = self.pivot_price[caught]
        dist = (sig_close / px - 1) * 100 if self.side == "buy" else (px / sig_close - 1) * 100
        out.update({
            "signals": n_sig,
            "pivots": n_piv,
            "caught": int(len(caught)),
            "good_signals": int((q >= HIT_Q).sum()),
            "hit_rate": float((q >= HIT_Q).mean()) if n_sig else 0.0,
            "avg_lag_bars": float(lags.mean()) if len(lags) else float("nan"),
            "avg_dist_pct": float(dist.mean()) if len(dist) else float("nan"),
            "random_baseline": self.random_baseline(n_sig, seg),
        })
        return out

    def details(self, signal: np.ndarray) -> Tuple[List[Dict[str, Any]], List[int]]:
        """Every signal bar (bar, q, owning pivot, whether it is the catch of that pivot) and the
        indices of the target pivots no signal caught (q >= HIT_Q)."""
        idx = np.flatnonzero(signal)
        best = np.zeros(len(self.pivot_bar))
        best_bar = np.full(len(self.pivot_bar), -1, dtype=np.int64)
        for s in idx:
            z, q = int(self.zone[s]), self.quality[s]
            if z >= 0 and not np.isnan(q) and q > best[z]:
                best[z], best_bar[z] = q, s
        rows = []
        for s in idx:
            z, q = int(self.zone[s]), float(self.quality[s])
            rows.append({"bar": int(s), "quality": None if np.isnan(q) else q, "pivot": z,
                         "catch": bool(z >= 0 and best_bar[z] == s and best[z] >= HIT_Q)})
        missed = [int(p) for p in range(len(self.pivot_bar)) if best[p] < HIT_Q]
        return rows, missed

    def random_baseline(self, n_signals: int, seg: Optional[Segment] = None, draws: int = 50) -> float:
        """Mean score of the same number of signals placed on random bars of the segment."""
        seg = seg or Segment(0, self.n)
        span = seg.hi - seg.lo
        if n_signals <= 0 or span <= 0:
            return 0.0
        rng = np.random.default_rng(12345)
        total = 0.0
        for _ in range(draws):
            sig = np.zeros(self.n, dtype=bool)
            sig[rng.choice(span, size=min(n_signals, span), replace=False) + seg.lo] = True
            total += self.score(sig, seg)
        return total / draws
