# -*- coding: utf-8 -*-
"""Chart of one optimizer result: candles, target tops/bottoms, optimized and default signals.

    python -m optimizer.viewer output/optimizer/<result>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from optimizer.search import Problem, RunConfig

SIG_COLOR = {"buy": "#00e676", "sell": "#ff1744"}


def main(path: str) -> None:
    from lightweight_charts import Chart

    res = json.loads(Path(path).read_text(encoding="utf-8"))
    cfg = RunConfig(**res["config"])
    prob = Problem(cfg)
    df = prob.df
    side = cfg.side
    sig_opt = prob.signal(res["optimized_params"])
    sig_def = prob.signal(res["default_params"])

    chart = Chart(toolbox=False, maximize=True,
                  title=f"{cfg.ticker} {cfg.tf} | {res['indicator_label']} | {cfg.side} | {cfg.level} | "
                        f"tops on High, bottoms on Low, signal price = Close")
    chart.legend(visible=True)
    chart.layout(background_color="#131722", text_color="#d1d4dc")
    chart.set(df[["time", "open", "high", "low", "close", "volume"]])

    times = df["time"]
    markers = []
    target = "bottom" if side == "buy" else "top"
    sw = prob.swings if cfg.level == "minor" else prob.swings[prob.swings["level"] == "major"]
    for r in sw.itertuples(index=False):
        is_target = r.kind == target
        markers.append({
            "time": times.iloc[r.bar],
            "position": "below" if r.kind == "bottom" else "above",
            "shape": "circle",
            "color": ("#ffd600" if r.confirmed else "#fff59d") if is_target else "#546e7a",
            "text": ("BOTTOM (Low)" if r.kind == "bottom" else "TOP (High)") if is_target else "",
        })
    pos = "below" if side == "buy" else "above"
    arrow = "arrow_up" if side == "buy" else "arrow_down"
    for i in np.flatnonzero(sig_def & ~sig_opt):
        markers.append({"time": times.iloc[i], "position": pos, "shape": "square", "color": "#9e9e9e",
                        "text": "default"})
    for i in np.flatnonzero(sig_opt):
        both = bool(sig_def[i])
        markers.append({"time": times.iloc[i], "position": pos, "shape": arrow, "color": SIG_COLOR[side],
                        "text": "OPT+default" if both else "OPT"})
    # vertical_span of this lightweight-charts build throws in JS, so the split is a marker
    split = prob.test.lo
    if 0 < split < len(df):
        markers.append({"time": times.iloc[split], "position": "above", "shape": "square", "color": "#2962ff",
                        "text": "TRAIN | TEST ->"})
    markers.sort(key=lambda m: pd.Timestamp(m["time"]))
    chart.marker_list(markers)

    m = res["metrics"]
    chart.watermark(
        f"train {m['default']['train']['score']:.2f} -> {m['optimized']['train']['score']:.2f}   "
        f"test {m['default']['test']['score']:.2f} -> {m['optimized']['test']['score']:.2f}",
        font_size=22, color="rgba(180,180,240,0.35)")
    chart.show(block=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m optimizer.viewer <result.json>")
        raise SystemExit(1)
    main(sys.argv[1])
