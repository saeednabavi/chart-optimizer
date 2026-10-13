# -*- coding: utf-8 -*-
"""
Batch local chart screenshots: one indicator at a time, per symbol/TF.
Saves under chart/compare_shots/local/
Also builds a side-by-side HTML gallery if Chartix shots exist.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chart import app as chart_app
from chart import data_loader as dl

OUT = Path(__file__).resolve().parent / "compare_shots"
LOCAL_DIR = OUT / "local"
CHARTIX_DIR = OUT / "chartix"
GALLERY = OUT / "gallery.html"

# Manageable matrix for visual parity
JOBS: List[Tuple[str, str, str, str]] = [
    # (name, ticker, tf, indicator_key)
    ("عیار", "BRS00927", "1d", "matrix"),
    ("عیار", "BRS00927", "1d", "tcg"),
    ("عیار", "BRS00927", "1d", "vtx"),
    ("عیار", "BRS00927", "1d", "eagles"),
    ("عیار", "BRS00927", "1d", "bvb"),
    ("عیار", "BRS00927", "1d", "utbot"),
    ("عیار", "BRS00927", "1d", "gainz"),
    ("عیار", "BRS00927", "1d", "aieng"),
    ("عیار", "BRS00927", "1h", "matrix"),
    ("عیار", "BRS00927", "1h", "vtx"),
    ("عیار", "BRS00927", "1h", "eagles"),
    ("عیار", "BRS00927", "1h", "utbot"),
    ("اهرم", "BRS001195", "1d", "matrix"),
    ("اهرم", "BRS001195", "1d", "vtx"),
    ("اهرم", "BRS001195", "1d", "eagles"),
    ("اهرم", "BRS001195", "1d", "bvb"),
    ("طلا", "BRS00924", "1d", "matrix"),
    ("طلا", "BRS00924", "1d", "utbot"),
]

KEY_LABEL = {key: label for label, key, _, _ in chart_app.INDICATORS}


def _slug(name: str, tf: str, key: str, ticker: str = "") -> str:
    # Prefer ticker so filenames stay ASCII-safe across tools
    base = ticker or "".join(ch if (ch.isascii() and (ch.isalnum() or ch in "-_")) else "_" for ch in name)
    return f"{base}__{tf}__{key}"


def _ensure_dirs() -> None:
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    CHARTIX_DIR.mkdir(parents=True, exist_ok=True)


def _only_enable(key: str) -> None:
    for _, k, _, _ in chart_app.INDICATORS:
        chart_app.STATE.enabled[k] = k == key


def _screenshot_all_panes(chart) -> Optional[bytes]:
    """Capture main + visible subpanes and stitch vertically (PNG bytes)."""
    try:
        from io import BytesIO

        from PIL import Image
    except Exception:
        return None

    panes = [chart] + [chart_app.STATE.subcharts[p] for p in chart_app.OSC_PANES if p in chart_app.STATE.subcharts]
    images = []
    for pane in panes:
        try:
            # Skip collapsed panes
            h = float(getattr(pane, "_height", 1.0) or 0)
            if h < 0.02 and pane is not chart:
                continue
            raw = pane.screenshot()
            if not raw:
                continue
            images.append(Image.open(BytesIO(raw)).convert("RGB"))
        except Exception:
            continue
    if not images:
        return None
    width = max(im.width for im in images)
    height = sum(im.height for im in images)
    canvas = Image.new("RGB", (width, height), (19, 23, 34))
    y = 0
    for im in images:
        if im.width != width:
            im = im.resize((width, int(im.height * width / max(1, im.width))))
        canvas.paste(im, (0, y))
        y += im.height
    buf = BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def _zoom_recent(chart, tf: str) -> None:
    import pandas as pd

    try:
        keys = sorted(int(k) for k in chart_app.STATE.label_map.keys())
        if not keys:
            chart.fit()
            return
        keep = 120 if tf in ("1d", "1w", "1mon") else 180
        start_t = keys[-keep] if len(keys) > keep else keys[0]
        end_t = keys[-1]
        chart.set_visible_range(pd.to_datetime(start_t, unit="s"), pd.to_datetime(end_t, unit="s"))
    except Exception:
        try:
            chart.fit()
        except Exception:
            pass


def build_gallery() -> Path:
    import time

    bust = int(time.time())
    rows = []
    for name, ticker, tf, key in JOBS:
        slug = _slug(name, tf, key, ticker)
        loc = LOCAL_DIR / f"{slug}.png"
        chx = CHARTIX_DIR / f"{slug}.png"
        label = KEY_LABEL.get(key, key)
        left = (
            f'<img src="local/{slug}.png?v={bust}" alt="local"/>'
            if loc.exists()
            else "<div class='miss'>local missing</div>"
        )
        right = (
            f'<img src="chartix/{slug}.png?v={bust}" alt="chartix"/>'
            if chx.exists()
            else "<div class='miss'>chartix missing</div>"
        )
        rows.append(
            f"""
            <section>
              <h2>{name} / {ticker} / {tf} / {label}</h2>
              <div class="pair" dir="ltr">
                <figure><figcaption>Local</figcaption>{left}</figure>
                <figure><figcaption>Chartix</figcaption>{right}</figure>
              </div>
            </section>
            """
        )
    html = f"""<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"/>
<title>Local vs Chartix Indicator Shots</title>
<style>
body {{ margin:0; font-family: Tahoma, sans-serif; background:#0f1115; color:#e8e8e8; }}
h1 {{ padding:16px 20px; margin:0; background:#1a1f2b; }}
h2 {{ margin:0 0 10px; font-size:16px; }}
section {{ padding:16px 20px; border-bottom:1px solid #2a3142; }}
.pair {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
figure {{ margin:0; background:#151922; border:1px solid #2a3142; padding:8px; }}
figcaption {{ font-size:12px; color:#9aa4b2; margin-bottom:6px; font-weight:700; }}
img {{ width:100%; height:auto; display:block; background:#000; }}
.miss {{ min-height:220px; display:flex; align-items:center; justify-content:center; color:#f07178; }}
@media (max-width: 900px) {{ .pair {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<h1>مقایسه تصویری لوکال در برابر چارتیکس (Local چپ · Chartix راست)</h1>
{''.join(rows)}
</body>
</html>
"""
    GALLERY.write_text(html, encoding="utf-8")
    print(f"gallery -> {GALLERY}", flush=True)
    return GALLERY


async def _run_shots() -> None:
    _ensure_dirs()
    from lightweight_charts import Chart

    chart = Chart(toolbox=False, width=1400, height=900)
    chart_app.CHART = chart
    chart.legend(visible=True)
    chart.layout(background_color="#131722", text_color="#d1d4dc")
    chart.candle_style(
        up_color="#26a69a",
        down_color="#ef5350",
        border_up_color="#26a69a",
        border_down_color="#ef5350",
        wick_up_color="#26a69a",
        wick_down_color="#ef5350",
    )
    chart.volume_config(up_color="rgba(38,166,154,0.5)", down_color="rgba(239,83,80,0.5)")

    # minimal topbar so timeframe/symbol state still makes sense in watermark
    names = chart_app._symbol_names()
    chart.topbar.switcher("symbol", tuple(names), default=names[0] if names else "x")
    chart.topbar.menu("timeframe", tuple(chart_app.CHART_TF_LABELS), default="1d")
    chart.topbar.switcher("adj", tuple(dl.ADJ_LABELS), default="adjusted")

    chart.show(block=False)
    await asyncio.sleep(1.2)
    chart_app._layout_container(chart)

    done = 0
    for name, ticker, tf, key in JOBS:
        slug = _slug(name, tf, key, ticker)
        out_path = LOCAL_DIR / f"{slug}.png"
        try:
            # skip if no CSV
            dl.load_ohlcv(ticker, tf, "adjusted")
        except FileNotFoundError as e:
            print(f"SKIP no data {slug}: {e}", flush=True)
            continue
        try:
            chart_app.STATE.name = name
            chart_app.STATE.ticker = ticker
            chart_app.STATE.tf = tf
            chart_app.STATE.adj = "adjusted"
            _only_enable(key)
            # clear previous subpane heights by reloading
            chart_app.reload_chart(chart, force=True)
            await asyncio.sleep(1.0)
            _zoom_recent(chart, tf)
            await asyncio.sleep(0.6)
            # chart.screenshot() only captures the MAIN pane canvas — compose all panes.
            png = _screenshot_all_panes(chart)
            if not png:
                png = chart.screenshot()
            out_path.write_bytes(png)
            done += 1
            print(f"OK local {slug} ({done}/{len(JOBS)}) bytes={len(png)}", flush=True)
        except Exception:
            print(f"FAIL local {slug}", flush=True)
            traceback.print_exc()

    build_gallery()
    print(f"local shots done: {done}", flush=True)
    try:
        chart.exit()
    except Exception:
        pass


def main() -> None:
    asyncio.run(_run_shots())


if __name__ == "__main__":
    main()
