# -*- coding: utf-8 -*-
"""
Local lightweight-charts UI with symbol / timeframe / adj selectors
and per-indicator On/Off toggles.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from lightweight_charts import Chart
from lightweight_charts.abstract import SeriesCommon
from lightweight_charts.chart import PyWV
from webview.errors import JavascriptException

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UI_STATE_FILE = Path(__file__).resolve().parent / "ui_state.json"

from chart import data_loader as dl
from chart import indicator_settings as iset
from chart import pivots
from chart import session_scale
from chart import settings_ui
from chart import swings

SWINGS_LEVEL = "Swings"
PIVOT_CHOICES = ("Off",) + tuple(pivots.LEVELS) + (SWINGS_LEVEL,)
from chart.indicators import (
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
from chart.indicators.common import color_alpha


def _patch_lightweight_charts() -> None:
    """Fix Pandas3 us-time bug + stop JS errors from killing the webview loop."""

    def _df_datetime_format(self, df: pd.DataFrame, exclude_lowercase=None):
        df = df.copy()
        df.columns = self._format_labels(df, df.columns, df.index, exclude_lowercase)
        self._set_interval(df)
        if not pd.api.types.is_datetime64_any_dtype(df["time"]):
            df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df["time"] = (df["time"].astype("datetime64[ns]").astype("int64") // 10**9).astype("int64")
        return df

    SeriesCommon._df_datetime_format = _df_datetime_format

    def create_window(
        self, width, height, x, y, screen=None, on_top=False, maximize=False, title=""
    ):
        """Use the OS maximized state so the window fills the work area on any display.

        The library only copies screens[0] pixel size, which misses the taskbar and
        breaks under a different DPI or resolution.
        """
        import webview
        from lightweight_charts import abstract as lc_abstract

        target = webview.screens[screen] if screen is not None else None
        self.windows.append(
            webview.create_window(
                title,
                url=lc_abstract.INDEX,
                js_api=self.callback_api,
                width=width,
                height=height,
                x=x,
                y=y,
                screen=target,
                on_top=on_top,
                maximized=bool(maximize),
                background_color="#000000",
            )
        )
        self.windows[-1].events.loaded += lambda: self.loaded_event.set()

    PyWV.create_window = create_window

    def loop(self):
        while self.is_alive:
            i, arg = self.queue.get()

            if i == "start":
                import webview

                webview.start(debug=arg, func=self.loop)
                self.is_alive = False
                self.emit_queue.put("exit")
                return
            if i == "create_window":
                self.create_window(*arg)
                continue

            window = self.windows[i]
            if arg == "show":
                window.show()
            elif arg == "hide":
                window.hide()
            else:
                try:
                    if "_~_~RETURN~_~_" in arg:
                        self.return_queue.put(window.evaluate_js(arg[14:]))
                    else:
                        window.evaluate_js(arg)
                except JavascriptException as e:
                    # Never raise — raising kills the JS worker thread permanently.
                    try:
                        msg = e.args[0] if e.args else {}
                        if isinstance(msg, str):
                            try:
                                msg = eval(msg)
                            except Exception:
                                msg = {"message": msg}
                        name = msg.get("name", "JS") if isinstance(msg, dict) else "JS"
                        message = msg.get("message", str(msg)) if isinstance(msg, dict) else str(msg)
                        print(f"[js] {name}: {message}", flush=True)
                    except Exception:
                        print(f"[js] {e}", flush=True)
                except Exception as e:
                    print(f"[webview] {e}", flush=True)

    PyWV.loop = loop


_patch_lightweight_charts()

INDICATORS = [
    # (topbar label = Chartix name, settings key, module, default_on)
    # Defaults On so a fresh launch shows panes (Chartix-like workspace).
    ("MS", "matrix", matrix_series, True),
    ("TCG AI Tools", "tcg", tcg_ai_tools, True),
    ("VTX Oscillator", "vtx", vtx, True),
    ("Eagles Nest - CHARTIX", "eagles", eagles_nest, True),
    ("BvB", "bvb", bulls_v_bears, True),
    ("GainzAlgo Pro", "gainz", gainzalgo_approx, True),
    ("EngulfingCandle", "aieng", ai_engulfing, True),
    ("UT Bot Alerts", "utbot", ut_bot, True),
]

OSC_PANES = ("matrix", "tcg", "vtx", "eagles", "bvb")

# lightweight-charts struggles with hundreds of thousands of bars / markers
MAX_CHART_BARS = 12000
MAX_MARKERS = 250
# Default horizontal zoom: show last N bars (not the whole history)
DEFAULT_VISIBLE_BARS = 80

# Chartix download succeeded for these; 45min/2h/3h are absent for all symbols.
# 2min/3min/10min are built from 1min in data_loader.
CHART_TF_LABELS = [
    "1min",
    "2min",
    "3min",
    "5min",
    "10min",
    "15min",
    "30min",
    "1h",
    "1d",
    "1w",
    "1mon",
]


def load_ui_state() -> Dict[str, Any]:
    if not UI_STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(UI_STATE_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_ui_state() -> None:
    """Persist symbol / TF / adj / indicator On-Off / pane heights for next launch."""
    payload = {
        "name": STATE.name,
        "ticker": STATE.ticker,
        "tf": STATE.tf,
        "adj": STATE.adj,
        "enabled": {k: bool(v) for k, v in STATE.enabled.items()},
        "pane_heights": dict(STATE.pane_heights),
        "pivots": STATE.pivot_level,
    }
    try:
        UI_STATE_FILE.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as ex:
        print(f"ui_state save failed: {ex}", flush=True)


class AppState:
    def __init__(self) -> None:
        self.watchlist = dl.load_watchlist()
        self.name_map = dl.name_to_ticker(self.watchlist)
        self.ticker_map = dl.ticker_to_name(self.watchlist)
        try:
            name, ticker, tf, adj = dl.default_selection()
        except Exception:
            name = self.watchlist[0]["name"] if self.watchlist else ""
            ticker = self.watchlist[0]["ticker"] if self.watchlist else ""
            tf, adj = "1d", "adjusted"
        self.name = name
        self.ticker = ticker
        self.tf = tf
        self.adj = adj
        self.enabled: Dict[str, bool] = {key: default for _, key, _, default in INDICATORS}
        self.subcharts: Dict[str, Any] = {}
        self.line_objs: Dict[str, Any] = {}
        self.hist_objs: Dict[str, Any] = {}
        self.area_objs: Dict[str, Any] = {}
        self.series_kind: Dict[str, str] = {}
        self.series_pane: Dict[str, str] = {}
        self.series_times: Dict[str, set] = {}
        self.pending_markers: Dict[int, tuple] = {}
        self.busy = False
        self.real_to_synth: Dict[int, Any] = {}
        self.label_map: Dict[int, str] = {}
        self.settings: Dict[str, Dict[str, Any]] = iset.load_settings()
        self.pane_heights: Dict[str, float] = {}
        self.pending_reload = False
        self.pending_preserve = False
        self.data_mtime: Optional[float] = None
        self.pivot_level = "Off"
        self._restore_ui_state()

    def _restore_ui_state(self) -> None:
        saved = load_ui_state()
        if not saved:
            return
        name = saved.get("name")
        ticker = saved.get("ticker")
        if isinstance(name, str) and name in self.name_map:
            self.name = name
            self.ticker = self.name_map[name]
        elif isinstance(ticker, str) and ticker in self.ticker_map:
            self.ticker = ticker
            self.name = self.ticker_map[ticker]
        tf = saved.get("tf")
        if isinstance(tf, str) and tf in CHART_TF_LABELS:
            self.tf = tf
        adj = saved.get("adj")
        if isinstance(adj, str) and adj in getattr(dl, "ADJ_LABELS", ("adjusted", "unadjusted")):
            self.adj = adj
        enabled = saved.get("enabled")
        if isinstance(enabled, dict):
            for _, key, _, _ in INDICATORS:
                if key in enabled:
                    self.enabled[key] = bool(enabled[key])
        heights = saved.get("pane_heights")
        if isinstance(heights, dict):
            cleaned: Dict[str, float] = {}
            for k, v in heights.items():
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if 0.02 <= fv <= 1.0:
                    cleaned[str(k)] = fv
            self.pane_heights = cleaned
        if saved.get("pivots") in PIVOT_CHOICES:
            self.pivot_level = saved["pivots"]
        print(
            f"Restored UI: {self.name} | {self.tf} | {self.adj} | "
            f"on={[k for k, v in self.enabled.items() if v]}",
            flush=True,
        )


STATE = AppState()
CHART: Optional[Chart] = None


def _symbol_names() -> List[str]:
    return [s["name"] for s in STATE.watchlist]


def _timeframes_for_current() -> List[str]:
    tfs = dl.available_timeframes(STATE.ticker, STATE.adj)
    tfs = [t for t in tfs if t in CHART_TF_LABELS]
    # keep chart order
    tfs = [t for t in CHART_TF_LABELS if t in tfs]
    return tfs if tfs else ["1d"]


def _ensure_tf_available() -> None:
    tfs = _timeframes_for_current()
    if STATE.tf not in tfs:
        prev = STATE.tf
        STATE.tf = tfs[0]
        print(f"TF '{prev}' not available for {STATE.name}; using {STATE.tf}", flush=True)


def _set_series_visible(obj, visible: bool) -> None:
    try:
        if visible:
            obj.show_data()
        else:
            obj.hide_data()
    except Exception as ex:
        print(f"visibility failed: {ex}", flush=True)


def _safe_set_df(obj, frame: Optional[pd.DataFrame]) -> None:
    try:
        name = getattr(obj, "name", None) or "value"
        obj._has_live_data = False
        if frame is None or frame.empty:
            # Do NOT setData([]) — empty series + legend/crosshair → "Value is null" crash.
            _set_series_visible(obj, False)
            return
        out = frame.copy()
        if "time" in out.columns:
            out["time"] = pd.to_datetime(out["time"], errors="coerce").astype("datetime64[ns]")
            out = out.dropna(subset=["time"])
            out = out.drop_duplicates(subset=["time"], keep="last")
        if name not in out.columns:
            value_cols = [c for c in out.columns if c not in ("time", "color")]
            if value_cols:
                out = out.rename(columns={value_cols[0]: name})
        # Keep optional per-point color for histogram/line palettes (Chartix green/red bars).
        keep = ["time", name] + (["color"] if "color" in out.columns else [])
        out = out[[c for c in keep if c in out.columns]]
        # Drop NaN values (circle plots / sparse dots)
        out = out.dropna(subset=[name])
        if out.empty:
            _set_series_visible(obj, False)
            return
        obj.set(out)
        obj._has_live_data = True
        _set_series_visible(obj, True)
    except Exception as ex:
        print(f"set series failed: {ex}", flush=True)


def _hide_all_overlays() -> None:
    for obj in list(STATE.line_objs.values()):
        _set_series_visible(obj, False)
    for obj in list(STATE.hist_objs.values()):
        _set_series_visible(obj, False)
    for obj in list(STATE.area_objs.values()):
        _set_series_visible(obj, False)


def _layout_container(chart: Chart) -> None:
    """Stack panes in a column; body overflow:hidden otherwise clips subcharts."""
    try:
        chart.run_script(
            """
            (() => {
              const c = document.getElementById('container') || window.containerDiv;
              if (!c) return;
              c.style.display = 'flex';
              c.style.flexDirection = 'column';
              c.style.height = '100vh';
              c.style.width = '100vw';
              c.style.overflow = 'hidden';
              c.style.margin = '0';
              c.style.padding = '0';
            })();
            """
        )
    except Exception:
        pass


def _apply_default_zoom(
    chart: Chart,
    candle_df: Optional[pd.DataFrame] = None,
    n_bars: int = DEFAULT_VISIBLE_BARS,
) -> None:
    """Zoom into the most recent bars instead of fitting the entire history."""
    if candle_df is None or candle_df.empty or "time" not in candle_df.columns:
        return
    n = min(int(n_bars), len(candle_df))
    if n <= 1:
        return
    start = pd.to_datetime(candle_df["time"].iloc[-n], errors="coerce")
    end = pd.to_datetime(candle_df["time"].iloc[-1], errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return
    start_ts = int(start.timestamp())
    end_ts = int(end.timestamp())
    try:
        chart.set_visible_range(start, end)
    except Exception as ex:
        print(f"set_visible_range failed: {ex}", flush=True)
    # Reinforce after pane resize/sync (series.data() is unavailable in this LWC build)
    try:
        chart.run_script(
            f"""
            (() => {{
              const apply = () => {{
                try {{
                  const ts = {chart.id}.chart.timeScale();
                  ts.setVisibleRange({{ from: {start_ts}, to: {end_ts} }});
                  ts.applyOptions({{ rightOffset: 6, barSpacing: 12, minBarSpacing: 6 }});
                  if (window.__copyPaneLock) window.__copyPaneLock();
                }} catch (e) {{}}
              }};
              apply();
              setTimeout(apply, 80);
              setTimeout(apply, 250);
            }})();
            """
        )
        print(f"default zoom -> last {n} bars", flush=True)
    except Exception as ex:
        print(f"default zoom failed: {ex}", flush=True)


def _style_indicator_topbar(chart: Chart) -> None:
    """Row1: symbol/TF/adj/Load — Row2: each indicator Name|Off/On|gear."""
    parts = []
    for label, key, _, _ in INDICATORS:
        lbl = chart.topbar.get(f"lbl_{key}")
        sw = chart.topbar.get(key)
        gear = chart.topbar.get(f"cfg_{key}")
        if not lbl or not sw or not gear:
            continue
        # TextWidget id is the DOM node; switcher/button ids are objects with .elem
        parts.append(
            f"{{label:{lbl.id}, switcher:{sw.id}, gear:{gear.id}, name:{json.dumps(label)}}}"
        )
    if not parts:
        return
    arr = "[" + ",".join(parts) + "]"
    try:
        chart.run_script(
            f"""
            (() => {{
              if (!document.getElementById('ind-switch-colors')) {{
                const st = document.createElement('style');
                st.id = 'ind-switch-colors';
                st.textContent = `
                  .ind-group .switcher-button {{
                    font-weight: 700;
                    background: #3C434C;
                    color: #ffffff;
                  }}
                  .ind-group .switcher-button[data-ind-state="off"].active-switcher-button {{
                    background: #e53935 !important;
                    color: #ffffff !important;
                  }}
                  .ind-group .switcher-button[data-ind-state="on"].active-switcher-button {{
                    background: #2e7d32 !important;
                    color: #ffffff !important;
                  }}
                `;
                document.head.appendChild(st);
              }}
              const paintIndSwitch = (swEl) => {{
                if (!swEl || !swEl.querySelectorAll) return;
                swEl.querySelectorAll('.switcher-button').forEach(btn => {{
                  const t = (btn.innerText || '').trim().toLowerCase();
                  if (t === 'off' || t === 'on') btn.dataset.indState = t;
                }});
              }};
              const topbar = document.querySelector('.topbar');
              if (!topbar) return;
              topbar.style.display = 'flex';
              topbar.style.flexDirection = 'column';
              topbar.style.alignItems = 'stretch';
              topbar.style.height = 'auto';
              topbar.style.minHeight = '0';
              topbar.style.rowGap = '0';

              // Row 1: keep symbol / TF / adj (left) + Load (right) on one line
              let mainRow = topbar.querySelector('.topbar-main-row');
              if (!mainRow) {{
                mainRow = document.createElement('div');
                mainRow.className = 'topbar-main-row';
                mainRow.style.cssText = 'display:flex;flex-direction:row;justify-content:space-between;align-items:center;width:100%;min-height:34px;';
                const containers = Array.from(topbar.querySelectorAll(':scope > .topbar-container'));
                containers.forEach(el => mainRow.appendChild(el));
                topbar.insertBefore(mainRow, topbar.firstChild);
              }}

              // Row 2: indicator chips
              let indRow = topbar.querySelector('.ind-row');
              if (!indRow) {{
                indRow = document.createElement('div');
                indRow.className = 'ind-row';
                indRow.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;width:100%;gap:4px;padding:4px 6px 6px 6px;border-top:1px solid #2a2e39;box-sizing:border-box;';
                topbar.appendChild(indRow);
              }}

              const groups = {arr};
              groups.forEach(g => {{
                const labelEl = g.label && g.label.classList ? g.label : null;
                const swEl = g.switcher && g.switcher.elem ? g.switcher.elem : null;
                const gearEl = g.gear && g.gear.elem ? g.gear.elem : null;
                if (!labelEl || !swEl || !gearEl) return;
                let wrap = labelEl.closest('.ind-group');
                if (!wrap) {{
                  wrap = document.createElement('div');
                  wrap.className = 'ind-group';
                  wrap.style.cssText = 'display:inline-flex;align-items:center;gap:4px;margin:1px 2px;padding:2px 6px;border:1px solid #3C434C;border-radius:6px;background:#1a1e29;';
                  [labelEl, swEl, gearEl].forEach(el => {{
                    const prev = el.previousElementSibling;
                    if (prev && prev.classList && prev.classList.contains('topbar-seperator')) prev.remove();
                    const next = el.nextElementSibling;
                    if (next && next.classList && next.classList.contains('topbar-seperator')) next.remove();
                    wrap.appendChild(el);
                  }});
                  labelEl.style.cssText = 'margin:0;padding:0 4px;font-size:12px;white-space:nowrap;color:#d1d4dc;';
                  swEl.style.margin = '0';
                  gearEl.style.cssText = (gearEl.style.cssText||'') + ';margin:0;min-width:28px;padding:2px 6px;font-size:14px;';
                  gearEl.title = g.name + ' settings';
                }}
                if (wrap.parentElement !== indRow) indRow.appendChild(wrap);
                paintIndSwitch(swEl);
              }});

              // Force chart to account for taller two-row topbar
              try {{ if (window.handlerInFocus) {{ /* noop */ }} }} catch (e) {{}}
              document.querySelectorAll('.handler').forEach(h => {{
                // trigger resize via known handlers if present
              }});
            }})();
            """
        )
        # Resize main chart so the extra topbar row doesn't clip candles
        try:
            chart.run_script(f"try {{ {chart.id}.reSize(); }} catch (e) {{}}")
        except Exception:
            pass
    except Exception as ex:
        print(f"topbar group style failed: {ex}", flush=True)


def _install_pane_resizers(chart: Chart) -> None:
    """Drag handles between stock pane and indicator panes to resize heights."""
    entries = [("main", chart.id)]
    for pid in OSC_PANES:
        pane = STATE.subcharts.get(pid)
        if pane is not None:
            entries.append((pid, pane.id))
    # refs are JS identifiers like window.abcdef — embed without quotes
    refs_js = ",".join(
        f'{{id:{json.dumps(pid)}, handler:{ref}}}' for pid, ref in entries
    )
    try:
        chart.run_script(
            f"""
            (() => {{
              const panes = [{refs_js}];
              const container = document.getElementById('container') || window.containerDiv;
              if (!container) return;
              document.querySelectorAll('.pane-grip').forEach(g => g.remove());

              const visible = panes.filter(p => p.handler && p.handler.scale && p.handler.scale.height > 0.02);
              for (let i = 0; i < visible.length - 1; i++) {{
                const upper = visible[i];
                const lower = visible[i + 1];
                const grip = document.createElement('div');
                grip.className = 'pane-grip';
                grip.title = 'Drag to resize panes';
                grip.style.cssText = 'height:6px;width:100%;cursor:ns-resize;background:linear-gradient(#2a2e39,#3C434C,#2a2e39);flex:0 0 6px;z-index:20;';
                const lowerWrap = lower.handler.wrapper;
                if (!lowerWrap || !lowerWrap.parentElement) continue;
                lowerWrap.parentElement.insertBefore(grip, lowerWrap);

                grip.addEventListener('mousedown', (ev) => {{
                  ev.preventDefault();
                  const startY = ev.clientY;
                  const h1 = upper.handler.scale.height;
                  const h2 = lower.handler.scale.height;
                  const onMove = (e) => {{
                    const dy = (e.clientY - startY) / window.innerHeight;
                    let n1 = h1 + dy;
                    let n2 = h2 - dy;
                    const minH = 0.08;
                    if (n1 < minH) {{ n2 -= (minH - n1); n1 = minH; }}
                    if (n2 < minH) {{ n1 -= (minH - n2); n2 = minH; }}
                    if (n1 < minH || n2 < minH) return;
                    upper.handler.scale.height = n1;
                    lower.handler.scale.height = n2;
                    upper.handler.reSize();
                    lower.handler.reSize();
                  }};
                  const onUp = () => {{
                    document.removeEventListener('mousemove', onMove);
                    document.removeEventListener('mouseup', onUp);
                    const payload = {{}};
                    panes.forEach(p => {{
                      if (p.handler && p.handler.scale) payload[p.id] = p.handler.scale.height;
                    }});
                    try {{ window.callbackFunction('pane_heights_~_' + JSON.stringify(payload)); }} catch (e) {{}}
                    try {{ if (window.__copyPaneLock) window.__copyPaneLock(); }} catch (e) {{}}
                  }};
                  document.addEventListener('mousemove', onMove);
                  document.addEventListener('mouseup', onUp);
                }});
              }}
            }})();
            """
        )
    except Exception as ex:
        print(f"pane resizer install failed: {ex}", flush=True)


def _hide_base_candles(pane) -> None:
    """Oscillator panes ship with an empty candlestick series that breaks autoscale."""
    try:
        pane.run_script(
            f"""
            {pane.id}.series.applyOptions({{visible: false}});
            if ({pane.id}.volumeSeries) {pane.id}.volumeSeries.applyOptions({{visible: false}});
            """
        )
    except Exception:
        pass


def _show_base_candles(pane) -> None:
    try:
        pane.run_script(
            f"""
            {pane.id}.series.applyOptions({{visible: true}});
            if ({pane.id}.volumeSeries) {pane.id}.volumeSeries.applyOptions({{visible: false}});
            """
        )
    except Exception:
        pass


def _pane(chart: Chart, pane_id: str, height: float = 0.12):
    if pane_id == "main":
        return chart
    if pane_id not in STATE.subcharts:
        # Shrink main first so the new pane is not created below the clipped viewport.
        n_existing = len(STATE.subcharts)
        main_h = max(0.34, 0.92 - 0.12 * (n_existing + 1))
        try:
            chart.resize(1.0, main_h)
        except Exception:
            pass
        h = 0.18 if pane_id == "matrix" else height
        # position must be a valid CSS float (left/right). "bottom" is ignored and panes
        # get pushed under overflow:hidden → looks like "nothing is drawing".
        pane = chart.create_subchart(
            position="left",
            width=1.0,
            height=h,
            sync=True,
            scale_candles_only=False,
        )
        STATE.subcharts[pane_id] = pane
        if pane_id != "matrix":
            _hide_base_candles(pane)
        else:
            _show_base_candles(pane)
        _layout_container(chart)
        print(f"created subpane {pane_id} height={h}", flush=True)
    return STATE.subcharts[pane_id]


def _rebalance_panes(chart: Chart, active_pane_ids: set) -> None:
    """Keep main + active oscillator panes inside the visible stack; leave room to drag-resize."""
    _layout_container(chart)
    used = [p for p in OSC_PANES if p in active_pane_ids]
    # Collapse unused panes so they don't eat viewport height
    for pid, pane in list(STATE.subcharts.items()):
        if pid not in used:
            try:
                pane.resize(1.0, 0.001)
                _hide_base_candles(pane)
            except Exception:
                pass
            STATE.pane_heights.pop(pid, None)
    n = len(used)
    if n <= 0:
        try:
            chart.resize(1.0, 0.98)
        except Exception:
            pass
        STATE.pane_heights = {"main": 0.98}
        _install_pane_resizers(chart)
        return

    # Prefer saved heights when they cover the current pane set
    saved = STATE.pane_heights
    if saved and "main" in saved and all(pid in saved for pid in used):
        main_h = max(0.28, float(saved["main"]))
        heights = [max(0.08, float(saved[pid])) for pid in used]
        total = main_h + sum(heights)
        if total > 0.01:
            scale = 0.98 / total
            main_h *= scale
            heights = [h * scale for h in heights]
    else:
        # Keep price chart dominant; each osc pane stays compact (~10%)
        budget = min(0.42, 0.10 * n + 0.06)
        weights = [1.25 if pid == "matrix" else 1.0 for pid in used]
        wsum = sum(weights) or 1.0
        heights = [max(0.08, budget * (w / wsum)) for w in weights]
        scale = budget / (sum(heights) or 1.0)
        heights = [h * scale for h in heights]
        main_h = max(0.50, 0.98 - sum(heights))

    try:
        chart.resize(1.0, main_h)
    except Exception:
        pass
    for pid, h in zip(used, heights):
        pane = STATE.subcharts.get(pid)
        if pane is None:
            continue
        try:
            pane.resize(1.0, h)
        except Exception:
            pass
    STATE.pane_heights = {"main": main_h, **dict(zip(used, heights))}
    _install_pane_resizers(chart)
    print(f"pane layout main={main_h:.2f} subs={dict(zip(used, [round(h,2) for h in heights]))}", flush=True)


def _sync_toggle_ui(chart: Chart) -> None:
    """Keep Off/On switcher visuals matched to STATE.enabled."""
    if not getattr(chart.win, "loaded", False):
        return
    for _, key, _, _ in INDICATORS:
        want = "On" if STATE.enabled.get(key) else "Off"
        w = chart.topbar.get(key)
        if w is None:
            continue
        try:
            w.value = want
            w.run_script(
                f"""
                (() => {{
                  const root = {w.id};
                  if (!root || !root.intervalElements) return;
                  root.intervalElements.forEach(btn => {{
                    const label = (btn.innerText || '').trim();
                    const on = (label === '{want}');
                    btn.classList.toggle('active-switcher-button', on);
                    const key = label.toLowerCase();
                    if (key === 'off' || key === 'on') btn.dataset.indState = key;
                  }});
                }})();
                """
            )
        except Exception:
            pass


def _apply_pane_candles(chart: Chart, pane_id: str, candle_df: Optional[pd.DataFrame], up: str, down: str) -> None:
    pane = _pane(chart, pane_id)
    try:
        if candle_df is None or candle_df.empty:
            # Never setData([]) — just hide the base candle series.
            _hide_base_candles(pane)
            return
        out = candle_df[["time", "open", "high", "low", "close"]].copy()
        out = session_scale.remap_frame(out, STATE.real_to_synth)
        if out is None or out.empty:
            _hide_base_candles(pane)
            return
        wick = up
        border_u, border_d = up, down
        if candle_df is not None and not getattr(candle_df, "empty", True):
            if "__wick_color" in candle_df.columns:
                wick = str(candle_df["__wick_color"].iloc[0])
            if "__border_color" in candle_df.columns:
                border_u = border_d = str(candle_df["__border_color"].iloc[0])
        try:
            pane.candle_style(
                up_color=up,
                down_color=down,
                border_up_color=border_u,
                border_down_color=border_d,
                wick_up_color=wick,
                wick_down_color=wick,
            )
        except Exception:
            pass
        _show_base_candles(pane)
        pane.set(out)
    except Exception as ex:
        print(f"pane candles failed: {ex}", flush=True)


def _get_or_create_line(
    pane,
    key_name: str,
    color: str,
    width: int = 1,
    kind: str = "line",
    linestyle: str = "solid",
    chrome: Optional[Dict[str, Any]] = None,
    round_caps: bool = False,
    width_cap: int = 8,
):
    chrome = chrome or {}
    style = linestyle if linestyle in _LINE_STYLE_INDEX else "solid"
    price_label = bool(chrome.get("price_label", False))
    if key_name in STATE.line_objs:
        series = STATE.line_objs[key_name]
    else:
        short = key_name.split(":")[-1]
        series = pane.create_line(
            short,
            color=_js_color(color),
            style=style,
            width=int(width),
            price_line=False,
            price_label=price_label,
        )
        STATE.line_objs[key_name] = series
    _apply_series_chrome(
        series,
        color=color,
        width=width,
        linestyle=style,
        kind=kind,
        price_label=price_label,
        status_line=bool(chrome.get("status_line", True)),
        precision=chrome.get("precision"),
        round_caps=round_caps,
        width_cap=width_cap,
    )
    return series


def _promote_line_to_area(series, color: str, width: int) -> None:
    """Swap a line series for a real area series so the Area plot type fills."""
    safe = _js_color(color)
    top = _js_color(color_alpha(color, 0.28))
    w = max(1, min(8, int(width or 2)))
    chart_id = series._chart.id
    series.run_script(
        f"""
        (() => {{
          const holder = {series.id};
          const host = {chart_id};
          if (!holder || !host || !host.chart || holder.__isArea) return;
          const old = holder.series;
          const area = host.chart.addAreaSeries({{
            lineColor: '{safe}',
            topColor: '{top}',
            bottomColor: 'rgba(0,0,0,0)',
            lineWidth: {w},
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: true,
          }});
          if (host._seriesList) host._seriesList.push(area);
          const leg = host.legend;
          if (leg && leg._lines && old) {{
            const row = leg._lines.find(l => l.series === old);
            if (row) row.series = area;
          }}
          holder.series = area;
          holder.__isArea = true;
          try {{ host.chart.removeSeries(old); }} catch (e) {{}}
        }})();
        """
    )


def _get_or_create_area(
    pane,
    key_name: str,
    color: str,
    width: int,
    linestyle: str,
    chrome: Optional[Dict[str, Any]],
):
    chrome = chrome or {}
    if key_name in STATE.area_objs:
        series = STATE.area_objs[key_name]
    else:
        short = key_name.split(":")[-1]
        series = pane.create_line(
            short,
            color=_js_color(color),
            style="solid",
            width=max(1, min(8, int(width or 2))),
            price_line=False,
            price_label=bool(chrome.get("price_label", False)),
        )
        try:
            _promote_line_to_area(series, color, width)
        except Exception as ex:
            print(f"area series failed: {ex}", flush=True)
        STATE.area_objs[key_name] = series
    _apply_series_chrome(
        series,
        color=color,
        width=width,
        linestyle=linestyle,
        kind="area",
        price_label=bool(chrome.get("price_label", False)),
        status_line=bool(chrome.get("status_line", True)),
        precision=chrome.get("precision"),
    )
    return series


def _hide_other_buckets(key_name: str, bucket: str) -> None:
    if bucket != "line" and key_name in STATE.line_objs:
        _set_series_visible(STATE.line_objs[key_name], False)
    if bucket != "hist" and key_name in STATE.hist_objs:
        _set_series_visible(STATE.hist_objs[key_name], False)
    if bucket != "area" and key_name in STATE.area_objs:
        _set_series_visible(STATE.area_objs[key_name], False)


def _get_or_create_hist(
    pane,
    key_name: str,
    color: str = "#78909c",
    chrome: Optional[Dict[str, Any]] = None,
    precision_kind: str = "histogram",
):
    chrome = chrome or {}
    price_label = bool(chrome.get("price_label", False))
    if key_name in STATE.hist_objs:
        series = STATE.hist_objs[key_name]
    else:
        short = key_name.split(":")[-1]
        try:
            series = pane.create_histogram(short, color=_js_color(color), price_line=False, price_label=price_label)
        except Exception:
            series = pane.create_line(short, color=_js_color(color), width=1, price_line=False, price_label=price_label)
            STATE.line_objs[key_name] = series
            STATE.series_kind[key_name] = "line"
            _apply_series_chrome(
                series,
                color=color,
                width=1,
                linestyle="solid",
                kind="line",
                price_label=price_label,
                status_line=bool(chrome.get("status_line", True)),
                precision=chrome.get("precision"),
            )
            return series
        STATE.hist_objs[key_name] = series
    _apply_series_chrome(
        series,
        color=color,
        width=1,
        linestyle="solid",
        kind=precision_kind,
        price_label=price_label,
        status_line=bool(chrome.get("status_line", True)),
        precision=chrome.get("precision"),
    )
    return series


_LINE_STYLE_INDEX = {
    "solid": 0,
    "dotted": 1,
    "dashed": 2,
    "large_dashed": 3,
    "sparse_dotted": 4,
}


def _js_color(color: str) -> str:
    return str(color or "#888888").replace("\\", "").replace("'", "").replace('"', "").replace("\n", "")


def _chrome_for(ind_key: str) -> Dict[str, Any]:
    cfg = STATE.settings.get(ind_key) or {}
    prec = str(cfg.get("precision", "default"))
    precision = int(prec) if prec.isdigit() else None
    return {
        "price_label": bool(cfg.get("labels_on_price_scale", True)),
        "status_line": bool(cfg.get("values_in_status_line", True)),
        "precision": precision,
    }


def _normalize_plot_type(plot_type: str) -> str:
    pt = str(plot_type or "line").lower()
    if pt in ("histogram", "columns", "column"):
        return "histogram"
    if pt == "area":
        return "area"
    if pt in ("circles", "circle", "shape"):
        return "circles"
    if pt in ("cross", "x"):
        return "cross"
    return "line"


def _kind_bucket(kind: str) -> str:
    if kind == "histogram":
        return "hist"
    if kind == "area":
        return "area"
    return "line"


def _apply_series_chrome(
    series,
    *,
    color: str,
    width: int,
    linestyle: str,
    kind: str,
    price_label: bool,
    status_line: bool,
    precision: Optional[int],
    round_caps: bool = False,
    width_cap: int = 8,
) -> None:
    """Push color, line style, width, price-scale label, precision, and legend visibility."""
    safe = _js_color(color)
    ls = _LINE_STYLE_INDEX.get(str(linestyle or "solid").lower(), 0)
    # Ordinary plots stay thin. TCG's solid bar asks for the Chartix pixel width
    # (about 40) plus a round cap of half that width: the ellipse at each end.
    cap = 8
    if round_caps:
        try:
            cap = int(width_cap)
        except (TypeError, ValueError):
            cap = 64
        cap = max(8, min(64, cap))
    width = max(1, min(cap, int(width or 1)))
    circles = kind in ("circles", "cross")
    if round_caps and not circles:
        radius = width / 2.0
        show_points = True
        show_line = True
    else:
        radius = 2 if kind == "cross" else max(3, int(width) + 2)
        show_points = circles
        show_line = not circles
    prec = ""
    if precision is not None:
        p = max(0, min(8, int(precision)))
        step = 1 if p == 0 else 10 ** (-p)
        prec = f", priceFormat: {{type:'price', precision:{p}, minMove:{step}}}"
    label = "true" if price_label else "false"
    show_leg = "''" if status_line else "'none'"
    chart_id = series._chart.id
    if kind == "histogram":
        options = f"""
            color: '{safe}',
            lastValueVisible: {label},
            priceLineVisible: false
            {prec}
        """
    elif kind == "area":
        top = _js_color(color_alpha(color, 0.28))
        options = f"""
            color: '{safe}',
            lineColor: '{safe}',
            topColor: '{top}',
            bottomColor: 'rgba(0,0,0,0)',
            lineWidth: {width},
            lineStyle: {ls},
            lastValueVisible: {label},
            priceLineVisible: false
            {prec}
        """
    else:
        options = f"""
            color: '{safe}',
            lineWidth: {width},
            lineStyle: {ls},
            lineVisible: {"true" if show_line else "false"},
            pointMarkersVisible: {"true" if show_points else "false"},
            pointMarkersRadius: {radius},
            lastValueVisible: {label},
            priceLineVisible: false
            {prec}
        """
    try:
        series.run_script(
            f"""
            {series.id}.series.applyOptions({{{options}}});
            (() => {{
              const leg = {chart_id}.legend;
              if (!leg || !leg._lines) return;
              const row = leg._lines.find(l => l.series === {series.id}.series);
              if (row && row.row) row.row.style.display = {show_leg};
            }})();
            """
        )
    except Exception as ex:
        print(f"series style failed: {ex}", flush=True)


def _get_series_for_plot(
    pane,
    key_name: str,
    color: str,
    width: int,
    plot_type: str,
    linestyle: str = "solid",
    chrome: Optional[Dict[str, Any]] = None,
    round_caps: bool = False,
    width_cap: int = 8,
):
    """Create/reuse series; switch between line/histogram/area/circles when plot_type changes."""
    kind = _normalize_plot_type(plot_type)
    # Columns cannot draw dashes. A non-solid style becomes a real stroked line.
    if kind == "histogram" and str(linestyle or "solid").lower() not in ("solid", ""):
        kind = "line"
    chrome = chrome or {}
    bucket = _kind_bucket(kind)
    _hide_other_buckets(key_name, bucket)
    STATE.series_kind[key_name] = kind
    if kind == "histogram":
        return _get_or_create_hist(pane, key_name, color, chrome=chrome, precision_kind=kind)
    if kind == "area":
        return _get_or_create_area(pane, key_name, color, width, linestyle, chrome)
    return _get_or_create_line(
        pane,
        key_name,
        color,
        width,
        kind=kind,
        linestyle=linestyle,
        chrome=chrome,
        round_caps=round_caps and kind == "line",
        width_cap=width_cap,
    )


def _clip_df_for_chart(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) <= MAX_CHART_BARS:
        return df
    return df.iloc[-MAX_CHART_BARS:].reset_index(drop=True)


def _install_session_labels(chart: Chart, label_map: Dict[int, str]) -> None:
    """Show real Iranian-session timestamps on every pane, not only the stock."""
    import json

    payload = json.dumps({str(k): v for k, v in label_map.items()}, ensure_ascii=False)
    ids = [chart.id] + [pane.id for pane in STATE.subcharts.values()]
    targets = ",".join(ids)
    chart.run_script(
        f"""
        window.__sessionLabels = {payload};
        window.__sessionLabelKeys = Object.keys(window.__sessionLabels).map(Number).sort((a,b)=>a-b);
        window.__sessionLabelFmt = function(t) {{
            if (t && typeof t === 'object' && 'year' in t) {{
                const m = String(t.month).padStart(2,'0');
                const d = String(t.day).padStart(2,'0');
                return `${{d}}/${{m}}/${{t.year}}`;
            }}
            const key = String(t);
            if (window.__sessionLabels && window.__sessionLabels[key]) {{
                return window.__sessionLabels[key];
            }}
            const keys = window.__sessionLabelKeys || [];
            let lo = 0, hi = keys.length - 1, ans = null;
            const target = Number(t);
            while (lo <= hi) {{
                const mid = (lo + hi) >> 1;
                const v = keys[mid];
                if (v <= target) {{ ans = v; lo = mid + 1; }}
                else {{ hi = mid - 1; }}
            }}
            if (ans != null && window.__sessionLabels[String(ans)]) {{
                return window.__sessionLabels[String(ans)];
            }}
            return key;
        }};
        [{targets}].forEach(h => {{
            if (!h || !h.chart) return;
            h.chart.applyOptions({{
                localization: {{
                    timeFormatter: (t) => window.__sessionLabelFmt(t),
                }},
                timeScale: {{
                    timeVisible: true,
                    secondsVisible: false,
                    tickMarkFormatter: (t, tickMarkType, locale) => window.__sessionLabelFmt(t),
                }},
            }});
        }});
        """
    )


def _anchor_subchart_times(candle_df: pd.DataFrame) -> None:
    """Give every indicator pane one hidden point per stock bar.

    Sparse plots (TCG crosses, RSI washes) otherwise build a shorter time scale.
    Logical-range sync then slides those panes onto different dates than the candles.
    """
    if candle_df is None or getattr(candle_df, "empty", True) or "time" not in candle_df.columns:
        return
    frame = pd.DataFrame(
        {
            "time": pd.to_datetime(candle_df["time"], errors="coerce"),
            "TimeAnchor": 0.0,
        }
    ).dropna(subset=["time"])
    if frame.empty:
        return
    for pid, pane in list(STATE.subcharts.items()):
        try:
            series = _get_or_create_line(
                pane,
                f"{pid}:TimeAnchor",
                "rgba(0,0,0,0)",
                1,
                chrome={"price_label": False, "status_line": False, "precision": 2},
            )
            _safe_set_df(series, frame)
            series.run_script(
                f"""
                {series.id}.series.applyOptions({{
                  visible: false,
                  priceLineVisible: false,
                  lastValueVisible: false,
                  crosshairMarkerVisible: false,
                }});
                """
            )
        except Exception as ex:
            print(f"time anchor failed for {pid}: {ex}", flush=True)


def _reset_stale_series(candle_df: pd.DataFrame, active_keys: set) -> None:
    """Re-point every inactive series at the current bars, hidden.

    Hidden series still feed their old points into the pane time scale. After a
    TF switch those stale timestamps interleave with the new ones, so the
    logical-range lock lands the pane on old dates and real plots go off-screen.
    """
    if candle_df is None or getattr(candle_df, "empty", True) or "time" not in candle_df.columns:
        return
    times = pd.to_datetime(candle_df["time"], errors="coerce")
    ohlc = candle_df[["time", "open", "high", "low", "close"]].copy()
    ohlc["time"] = times
    ohlc = ohlc.dropna(subset=["time"])
    if ohlc.empty:
        return
    buckets = (("line", STATE.line_objs), ("hist", STATE.hist_objs), ("area", STATE.area_objs))
    for bucket, objs in buckets:
        for name, obj in list(objs.items()):
            if str(name).endswith(":TimeAnchor"):
                continue
            live = (
                name in active_keys
                and _kind_bucket(STATE.series_kind.get(name, "line")) == bucket
                and getattr(obj, "_has_live_data", True)
            )
            if live:
                continue
            try:
                col = getattr(obj, "name", None) or "value"
                obj.set(pd.DataFrame({"time": ohlc["time"], col: 0.0}))
                _set_series_visible(obj, False)
            except Exception as ex:
                print(f"stale reset failed for {name}: {ex}", flush=True)
    for pid, pane in list(STATE.subcharts.items()):
        if f"{pid}:__candles__" in active_keys:
            continue
        try:
            pane.set(ohlc)
            _hide_base_candles(pane)
        except Exception as ex:
            print(f"stale candle reset failed for {pid}: {ex}", flush=True)


def _install_time_lock(chart: Chart) -> None:
    """Keep stock and indicator panes on one time axis: same bars, same dates."""
    ids = [chart.id] + [pane.id for pane in STATE.subcharts.values()]
    if len(ids) < 2:
        return
    targets = ",".join(ids)
    chart.run_script(
        f"""
        (() => {{
          const sameRange = (a, b) => a && b
            && Math.abs(a.from - b.from) < 1e-4
            && Math.abs(a.to - b.to) < 1e-4;
          window.__alignPaneScales = function() {{
            const charts = window.__paneLockCharts || [];
            let w = 48;
            charts.forEach(h => {{
              try {{
                const pw = h.chart.priceScale('right').width();
                if (pw > w) w = pw;
              }} catch (e) {{}}
            }});
            const target = Math.ceil(w);
            charts.forEach(h => {{
              try {{ h.chart.priceScale('right').applyOptions({{ minimumWidth: target }}); }} catch (e) {{}}
            }});
          }};
          window.__applyPaneLock = function(range, source) {{
            if (!range || window.__paneLockGuard) return;
            window.__paneLockGuard = true;
            try {{
              (window.__paneLockCharts || []).forEach(h => {{
                if (!h || h === source || !h.chart) return;
                const cur = h.chart.timeScale().getVisibleLogicalRange();
                if (sameRange(cur, range)) return;
                h.chart.timeScale().setVisibleLogicalRange(range);
              }});
            }} finally {{
              window.__paneLockGuard = false;
            }}
          }};
          window.__copyPaneLock = function() {{
            const charts = window.__paneLockCharts || [];
            if (!charts.length || !charts[0].chart) return;
            window.__alignPaneScales();
            const range = charts[0].chart.timeScale().getVisibleLogicalRange();
            window.__applyPaneLock(range, charts[0]);
          }};
          window.__paneLockCharts = [{targets}].filter(h => h && h.chart);
          window.__paneLockCharts.forEach(h => {{
            if (h.__paneLockOn) return;
            h.__paneLockOn = true;
            h.chart.timeScale().subscribeVisibleLogicalRangeChange(range => {{
              window.__applyPaneLock(range, h);
            }});
          }});
          window.__copyPaneLock();
        }})();
        """
    )


def _constant_hline_frame(times: pd.Series, price: float, col: str) -> pd.DataFrame:
    return pd.DataFrame({"time": times, col: float(price)})


def _marker_host(ind_key: str, pane_id: str, active_keys: Optional[set] = None):
    """A visible series on this indicator pane. Hidden pane candles cannot show markers."""
    prefix = f"{ind_key}:"
    named = []
    for name in sorted(active_keys or STATE.series_kind.keys()):
        if not str(name).startswith(prefix) or STATE.series_pane.get(name) != pane_id:
            continue
        obj = _live_obj(name)
        if obj is not None and getattr(obj, "_has_live_data", False):
            named.append((str(name), obj))
    for name, obj in named:
        if ":HL" not in name:
            return obj
    if named:
        return named[0][1]
    return STATE.subcharts.get(pane_id)


def _live_obj(name: str):
    bucket = {"line": STATE.line_objs, "hist": STATE.hist_objs, "area": STATE.area_objs}
    return bucket[_kind_bucket(STATE.series_kind.get(name, "line"))].get(name)


def _marker_host_at(ind_key: str, pane_id: str, t_unix: int, active_keys: set):
    """An active, visible series of this indicator that has a value on this bar.

    lightweight-charts anchors a marker to its host series value at that bar;
    a host with no point there leaves the marker unplaced.
    """
    prefix = f"{ind_key}:"
    fallback = None
    # Prefer line plots so markers sit on the oscillator, not a background wash.
    order = sorted(active_keys, key=lambda n: (STATE.series_kind.get(n) == "histogram", n))
    for name in order:
        if not name.startswith(prefix) or STATE.series_pane.get(name) != pane_id:
            continue
        if t_unix not in STATE.series_times.get(name, ()):
            continue
        obj = _live_obj(name)
        if obj is None:
            continue
        if ":HL" not in name:
            return obj
        fallback = fallback or obj
    return fallback


def _queue_marker(target, marker: Dict[str, Any]) -> None:
    slot = STATE.pending_markers.setdefault(id(target), (target, []))
    slot[1].append(marker)


def _flush_markers() -> None:
    """One sorted setMarkers per host: the renderer binary-searches markers by time."""
    for target, items in STATE.pending_markers.values():
        items.sort(key=lambda mk: mk["time"])
        try:
            target.markers = {target.win._id_gen.generate(): mk for mk in items}
            target._update_markers()
        except Exception as ex:
            print(f"markers failed: {ex}", flush=True)
    STATE.pending_markers = {}


def _apply_indicator_result(chart: Chart, key: str, result: Dict[str, Any], active_keys: set) -> None:
    candles = result.get("candles")
    if candles:
        data = candles.get("data")
        up = "#26a69a"
        down = "#ef5350"
        if data is not None and not getattr(data, "empty", True):
            if "__up_color" in data.columns:
                up = str(data["__up_color"].iloc[0])
            if "__down_color" in data.columns:
                down = str(data["__down_color"].iloc[0])
        _apply_pane_candles(chart, candles.get("pane", key), data, up, down)
        active_keys.add(f"{key}:__candles__")

    series_specs: List[Dict[str, Any]] = []
    for line in result.get("lines") or []:
        series_specs.append({**line, "plot_type": line.get("plot_type", "line")})
    for hist in result.get("histograms") or []:
        series_specs.append({**hist, "plot_type": hist.get("plot_type", "histogram")})

    # Reference lines (mid/OB/OS) as constant series so they actually render
    ref_times = None
    for spec in series_specs:
        data = spec.get("data")
        if data is not None and not getattr(data, "empty", True) and "time" in data.columns:
            ref_times = data["time"]
            break
    for i, hl in enumerate(result.get("hline") or []):
        if ref_times is None:
            break
        price = hl.get("price")
        if price is None:
            continue
        col = f"HL{i}"
        series_specs.append(
            {
                "name": col,
                "pane": hl.get("pane", key),
                "data": _constant_hline_frame(ref_times, float(price), col),
                "color": hl.get("color", "#787b86"),
                "width": int(hl.get("width", 1) or 1),
                "plot_type": hl.get("plot_type", "line"),
                "linestyle": hl.get("linestyle", "dashed" if i else "solid"),
            }
        )

    chrome = _chrome_for(key)
    for spec in series_specs:
        pane = _pane(chart, spec.get("pane", "main"))
        name = f"{key}:{spec['name']}"
        active_keys.add(name)
        plot_type = spec.get("plot_type", "line")
        series = _get_series_for_plot(
            pane,
            name,
            spec.get("color", "#2196f3"),
            int(spec.get("width", 1) or 1),
            plot_type,
            linestyle=str(spec.get("linestyle", "solid")),
            chrome=chrome,
            round_caps=bool(spec.get("round_caps")),
            width_cap=int(spec.get("width_cap", 8) or 8),
        )
        data = spec.get("data")
        if data is not None and not data.empty and len(data) > MAX_CHART_BARS:
            data = data.iloc[-MAX_CHART_BARS:]
        if data is not None and not getattr(data, "empty", True):
            data = data.copy()
            value_col = spec["name"] if spec["name"] in data.columns else next(
                (c for c in data.columns if c not in ("time", "color")), None
            )
            # Auto green/red palette when indicator provides color_neg/color_pos
            if (
                value_col
                and "color" not in data.columns
                and (spec.get("color_neg") or spec.get("color_pos"))
            ):
                pos_c = spec.get("color_pos", spec.get("color", "#26a69a"))
                neg_c = spec.get("color_neg", spec.get("color", "#ef5350"))
                data["color"] = np.where(
                    pd.to_numeric(data[value_col], errors="coerce") >= 0, pos_c, neg_c
                )
        data = session_scale.remap_frame(data, STATE.real_to_synth)
        _safe_set_df(series, data)
        STATE.series_pane[name] = spec.get("pane", "main")
        STATE.series_times[name] = set()
        if getattr(series, "_has_live_data", False) and data is not None and not data.empty:
            vcol = spec["name"] if spec["name"] in data.columns else next(
                (c for c in data.columns if c not in ("time", "color")), None
            )
            if vcol:
                live = data.dropna(subset=[vcol])
                STATE.series_times[name] = set(
                    (pd.to_datetime(live["time"]).astype("datetime64[ns]").astype("int64") // 10**9).tolist()
                )

    # Do not fitContent() here — it undoes the default recent-bars zoom on synced panes.

    # Optional fixed pane scale (TCG ribbon stays a mid-band like TV linewidth=40 at 0)
    fixed = result.get("fixed_scale") or {}
    if fixed.get("pane") and fixed.get("min") is not None and fixed.get("max") is not None:
        pane = _pane(chart, str(fixed["pane"]))
        lo = float(fixed["min"])
        hi = float(fixed["max"])
        try:
            # Prefer series autoscaleInfoProvider (supported across LWC builds)
            for key_name, series in (
                list(STATE.hist_objs.items()) + list(STATE.line_objs.items()) + list(STATE.area_objs.items())
            ):
                if not str(key_name).startswith("tcg:"):
                    continue
                series.run_script(
                    f"""
                    {series.id}.series.applyOptions({{
                      autoscaleInfoProvider: () => ({{
                        priceRange: {{ minValue: {lo}, maxValue: {hi} }},
                      }}),
                    }});
                    """
                )
            pane.run_script(
                f"""
                try {{
                  {pane.id}.chart.priceScale('right').applyOptions({{
                    scaleMargins: {{ top: 0.08, bottom: 0.08 }},
                  }});
                }} catch (e) {{}}
                """
            )
        except Exception:
            pass

    timed = []
    for m in result.get("markers") or []:
        synth_t = session_scale.remap_time_value(m.get("time"), STATE.real_to_synth)
        if synth_t is not None:
            timed.append((int(pd.Timestamp(synth_t).value // 10**9), m))
    timed.sort(key=lambda tm: tm[0])
    if len(timed) > MAX_MARKERS:
        timed = timed[-MAX_MARKERS:]
    for t_unix, m in timed:
        shape = m.get("shape", "circle")
        if shape in ("arrow_up", "arrowUp"):
            shape = "arrowUp"
        elif shape in ("arrow_down", "arrowDown"):
            shape = "arrowDown"
        elif shape == "cross":
            shape = "square"
        pane_id = m.get("pane", "main")
        if pane_id == "main":
            target = chart
        else:
            # Subpane candles are hidden, so markers on them never show.
            target = (
                _marker_host_at(key, pane_id, t_unix, active_keys)
                or _marker_host(key, pane_id, active_keys)
                or _pane(chart, pane_id)
            )
        pos = m.get("position", "below")
        if pos in ("above", "top", "aboveBar"):
            pos = "aboveBar"
        elif pos in ("inBar", "inside", "absolute", "Absolute", "center"):
            pos = "inBar"
        else:
            pos = "belowBar"
        _queue_marker(
            target,
            {
                "time": t_unix,
                "position": pos,
                "color": m.get("color", "#ffffff"),
                "shape": shape,
                "text": m.get("text", ""),
            },
        )


def _sync_timeframe_menu(chart: Chart) -> None:
    """Refresh timeframe menu to only TFs that exist on disk for this symbol/adj."""
    tfs = _timeframes_for_current()
    _ensure_tf_available()
    widget = chart.topbar.get("timeframe")
    if widget is None:
        return
    try:
        if hasattr(widget, "update_items"):
            widget.update_items(*tfs)
        if STATE.tf in getattr(widget, "options", tfs):
            widget.value = STATE.tf
            try:
                widget.run_script(f'{widget.id}.elem.innerText = "{STATE.tf}"')
            except Exception:
                pass
    except Exception as ex:
        print(f"timeframe menu sync failed: {ex}", flush=True)


def _capture_visible_range(chart: Chart) -> Optional[tuple]:
    """Read the current time scale so a settings reload does not jump the zoom."""
    if not getattr(chart.win, "loaded", False):
        return None
    script = f"""
            (() => {{
              try {{
                const r = {chart.id}.chart.timeScale().getVisibleRange();
                if (!r || r.from == null || r.to == null) return '';
                return String(r.from) + ',' + String(r.to);
              }} catch (e) {{ return ''; }}
            }})()
            """
    try:
        # A reply that missed an earlier timeout would otherwise be read as this one.
        try:
            while not chart.win._return_q.empty():
                chart.win._return_q.get_nowait()
        except Exception:
            pass
        chart.win.run_script(f"_~_~RETURN~_~_{script}")
        raw = chart.win._return_q.get(timeout=0.8)
    except Exception:
        return None
    text = str(raw or "").strip()
    if "," not in text:
        return None
    left, right = text.split(",", 1)
    try:
        return float(left), float(right)
    except ValueError:
        return None


def _restore_visible_range(chart: Chart, span: tuple) -> None:
    start, end = span
    try:
        chart.run_script(
            f"""
            (() => {{
              try {{
                {chart.id}.chart.timeScale().setVisibleRange({{ from: {start}, to: {end} }});
                if (window.__copyPaneLock) window.__copyPaneLock();
              }} catch (e) {{}}
            }})();
            """
        )
    except Exception as ex:
        print(f"restore zoom failed: {ex}", flush=True)


def _overlay_bar_colors(df: pd.DataFrame, results: List[tuple]) -> pd.DataFrame:
    """UT Bot 'Bar Color' paints the main candles. Later indicators override earlier ones."""
    painted = None
    for _label, _key, result in results:
        bc = (result or {}).get("bar_colors") or {}
        data = bc.get("data") if isinstance(bc, dict) else None
        if bc.get("enabled") and data is not None and not getattr(data, "empty", True):
            painted = data
    if painted is None or "time" not in df.columns:
        return df
    colors = painted.copy()
    colors["time"] = pd.to_datetime(colors["time"], errors="coerce").astype("datetime64[ns]")
    colors = colors.dropna(subset=["time"]).drop_duplicates(subset=["time"], keep="last")
    base = df.copy()
    base["time"] = pd.to_datetime(base["time"], errors="coerce").astype("datetime64[ns]")
    merged = base.merge(colors[["time", "color"]], on="time", how="left")
    return merged


def _htf_loader_for(ticker: str, adj: str):
    """Other-timeframe bars for indicators with a resolution input (Eagles Nest)."""

    def load(res: str) -> Optional[pd.DataFrame]:
        tf = chartix_exact.resolution_to_tf(res)
        if not tf:
            return None
        try:
            return dl.load_ohlcv(ticker, tf, adj)
        except (FileNotFoundError, ValueError):
            return None

    return load


def _candle_plot_frame(candle_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["time", "open", "high", "low", "close"]
    if "volume" in candle_df.columns:
        cols.append("volume")
    out = candle_df[cols].copy()
    if "color" in candle_df.columns:
        c = candle_df["color"]
        out["color"] = c
        out["borderColor"] = c
        out["wickColor"] = c
    return out


def reload_chart(chart: Chart, force: bool = False, preserve_view: bool = False) -> None:
    if STATE.busy:
        # Queue even plain reloads: a TF/symbol/toggle change must not be dropped.
        # Keep the zoom only if every queued reload asked for it (a TF change must not).
        if STATE.pending_reload:
            STATE.pending_preserve = STATE.pending_preserve and preserve_view
        else:
            STATE.pending_preserve = preserve_view
        STATE.pending_reload = True
        return
    STATE.busy = True
    STATE.pending_reload = False
    keep_range = None
    try:
        if preserve_view:
            keep_range = _capture_visible_range(chart)
        _hide_all_overlays()
        try:
            chart.clear_markers()
        except Exception:
            pass
        for pane in list(STATE.subcharts.values()):
            try:
                pane.clear_markers()
            except Exception:
                pass
        for obj in list(STATE.line_objs.values()) + list(STATE.hist_objs.values()) + list(STATE.area_objs.values()):
            try:
                obj.clear_markers()
            except Exception:
                pass

        _ensure_tf_available()

        try:
            STATE.data_mtime = dl.data_mtime(STATE.ticker, STATE.tf, STATE.adj)
            df_full = dl.load_ohlcv(STATE.ticker, STATE.tf, STATE.adj)
        except FileNotFoundError as e:
            print(e, flush=True)
            tfs = _timeframes_for_current()
            if tfs and STATE.tf not in tfs:
                STATE.tf = tfs[0]
                print(f"Falling back to {STATE.tf}", flush=True)
                try:
                    STATE.data_mtime = dl.data_mtime(STATE.ticker, STATE.tf, STATE.adj)
                    df_full = dl.load_ohlcv(STATE.ticker, STATE.tf, STATE.adj)
                except FileNotFoundError:
                    chart.watermark("NO DATA", color="rgba(255,80,80,0.5)")
                    return
            else:
                chart.watermark(f"NO DATA: {STATE.tf}", color="rgba(255,80,80,0.5)")
                return

        total = len(df_full)
        df = _clip_df_for_chart(df_full)
        df = df.copy()
        df["time"] = pd.to_datetime(df["time"], errors="coerce").astype("datetime64[ns]")
        df = df.dropna(subset=["time"]).drop_duplicates(subset=["time"], keep="last").reset_index(drop=True)

        active_keys: set = set()
        indicator_results: List[tuple] = []
        for label, key, mod, _ in INDICATORS:
            if not STATE.enabled.get(key):
                continue
            try:
                cfg = iset._apply_legacy_aliases(key, dict(STATE.settings.get(key) or {}))
                if not iset.is_visible_on_tf(cfg, STATE.tf):
                    print(f"skip {label}: hidden on TF {STATE.tf}", flush=True)
                    continue
                cfg["_chart_tf"] = STATE.tf
                cfg["_htf_loader"] = _htf_loader_for(STATE.ticker, STATE.adj)
                indicator_results.append((label, key, mod.compute(df, cfg)))
            except Exception as ex:
                print(f"Indicator {label} failed: {ex}", flush=True)
                traceback.print_exc()

        df = _overlay_bar_colors(df, indicator_results)
        candle_df, label_map, real_to_synth = session_scale.compress_session(df, STATE.tf)
        STATE.label_map = label_map
        STATE.real_to_synth = real_to_synth

        chart.set(_candle_plot_frame(candle_df))
        _install_session_labels(chart, label_map)

        shown = len(df)
        note = f"{STATE.name} | {STATE.tf} | {STATE.adj}"
        if shown < total:
            note += f" | last {shown}/{total}"
        on_inds = [lab for lab, k, _, __ in INDICATORS if STATE.enabled.get(k)]
        if on_inds:
            note += " | " + ",".join(on_inds)
        chart.watermark(note, color="rgba(180,180,240,0.35)")

        STATE.pending_markers = {}
        for label, key, result in indicator_results:
            _apply_indicator_result(chart, key, result, active_keys)
        if STATE.pivot_level in pivots.LEVELS:
            try:
                piv = pivots.find_pivots(df, STATE.pivot_level)
                _apply_indicator_result(chart, "pivots", {"markers": piv}, active_keys)
                print(f"pivots ({STATE.pivot_level}): {len(piv)}", flush=True)
            except Exception:
                print("pivots failed:", flush=True)
                traceback.print_exc()
        elif STATE.pivot_level == SWINGS_LEVEL:
            try:
                piv = swings.chart_markers(df, swings.load_config(STATE.tf))
                _apply_indicator_result(chart, "pivots", {"markers": piv}, active_keys)
                print(f"swings: {len(piv)}", flush=True)
            except Exception:
                print("swings failed:", flush=True)
                traceback.print_exc()
        _flush_markers()

        # Which oscillator panes got data this round
        active_panes = set()
        for name in active_keys:
            if name.endswith(":__candles__"):
                active_panes.add(name.split(":")[0])
                continue
            # series keys look like "tcg:TCG_Trend" — pane is from result; infer by indicator key
            ind = name.split(":")[0]
            if ind in OSC_PANES:
                active_panes.add(ind)
        _rebalance_panes(chart, active_panes)

        _reset_stale_series(candle_df, active_keys)

        _sync_toggle_ui(chart)
        _style_indicator_topbar(chart)
        _anchor_subchart_times(candle_df)
        _install_session_labels(chart, label_map)
        _install_time_lock(chart)
        if preserve_view:
            if keep_range:
                _restore_visible_range(chart, keep_range)
        else:
            _apply_default_zoom(chart, candle_df)
        try:
            print(
                f"Loaded {STATE.ticker} {STATE.tf} {STATE.adj} bars={shown}/{total} "
                f"indicators={len(indicator_results)} series={len(active_keys)} panes={sorted(active_panes)}",
                flush=True,
            )
        except Exception:
            print(
                f"Loaded bars={shown}/{total} indicators={len(indicator_results)} series={len(active_keys)}",
                flush=True,
            )
    except Exception:
        print("reload_chart error:", flush=True)
        traceback.print_exc()
    finally:
        STATE.busy = False
        if STATE.pending_reload:
            again = bool(STATE.pending_preserve)
            STATE.pending_reload = False
            STATE.pending_preserve = False
            reload_chart(chart, force=True, preserve_view=again)


def on_symbol(chart: Chart) -> None:
    name = chart.topbar["symbol"].value
    print(f"symbol -> {name}", flush=True)
    if name not in STATE.name_map:
        print(f"unknown symbol: {name}", flush=True)
        return
    STATE.name = name
    STATE.ticker = STATE.name_map[name]
    save_ui_state()
    _sync_timeframe_menu(chart)
    reload_chart(chart)


def on_timeframe(chart: Chart) -> None:
    STATE.tf = chart.topbar["timeframe"].value
    print(f"timeframe -> {STATE.tf}", flush=True)
    save_ui_state()
    reload_chart(chart)


def on_adj(chart: Chart) -> None:
    STATE.adj = chart.topbar["adj"].value
    print(f"adj -> {STATE.adj}", flush=True)
    save_ui_state()
    _sync_timeframe_menu(chart)
    reload_chart(chart)


def on_pivots(chart: Chart) -> None:
    STATE.pivot_level = chart.topbar["pivots"].value
    print(f"pivots -> {STATE.pivot_level}", flush=True)
    save_ui_state()
    reload_chart(chart, force=True, preserve_view=True)


def make_toggle_handler(key: str):
    def _handler(chart: Chart) -> None:
        val = chart.topbar[key].value
        STATE.enabled[key] = val == "On"
        print(f"toggle {key} -> {val}", flush=True)
        save_ui_state()
        reload_chart(chart)

    return _handler


def make_settings_handler(key: str):
    def _handler(chart: Chart) -> None:
        open_indicator_settings(chart, focus_key=key)

    return _handler


def open_indicator_settings(chart: Chart, focus_key: Optional[str] = None) -> None:
    print(f"Opening settings ({focus_key or 'default'})…", flush=True)
    try:
        _open_indicator_settings(chart, focus_key)
    except Exception:
        print("settings dialog failed:", flush=True)
        traceback.print_exc()


def _open_indicator_settings(chart: Chart, focus_key: Optional[str] = None) -> None:

    def _apply(updated: Dict[str, Dict[str, Any]], applied_key: Optional[str] = None) -> None:
        STATE.settings = updated
        target = applied_key or focus_key
        # Auto-enable the indicator being edited so Style/Inputs actually show
        if target:
            STATE.enabled[target] = True
            w = chart.topbar.get(target)
            if w is not None:
                try:
                    w.value = "On"
                    w.run_script(
                        f"""
                        (() => {{
                          const root = {w.id};
                          if (!root || !root.intervalElements) return;
                          root.intervalElements.forEach(btn => {{
                            if ((btn.innerText || '').trim() === 'On') {{
                              root.intervalElements.forEach(b => b.classList.remove('active-switcher-button'));
                              btn.classList.add('active-switcher-button');
                            }}
                          }});
                        }})();
                        """
                    )
                except Exception:
                    pass
            print(f"Enabled {target} from settings", flush=True)
        save_ui_state()
        print("Settings applied — reloading chart…", flush=True)
        reload_chart(chart, force=True, preserve_view=True)

    updated = settings_ui.open_settings_dialog(
        STATE.settings, on_apply=_apply, focus_key=focus_key
    )
    if updated is not None:
        STATE.settings = updated


def _on_pane_heights_msg(args: str) -> None:
    try:
        data = json.loads(args)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    cleaned: Dict[str, float] = {}
    for k, v in data.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0.02:
            cleaned[str(k)] = fv
    if cleaned:
        STATE.pane_heights = cleaned
        save_ui_state()
        print(f"pane heights saved: { {k: round(v, 3) for k, v in cleaned.items()} }", flush=True)


def _on_data_poll(*_args) -> None:
    """Redraw when the background updater rewrote the CSV currently on screen."""
    if CHART is None or STATE.busy or STATE.data_mtime is None:
        return
    mtime = dl.data_mtime(STATE.ticker, STATE.tf, STATE.adj)
    if mtime is None or mtime == STATE.data_mtime:
        return
    print(f"New data for {STATE.ticker} {STATE.tf} {STATE.adj} — refreshing chart", flush=True)
    reload_chart(CHART, force=True, preserve_view=True)


def main() -> None:
    global CHART
    if not STATE.watchlist:
        print("Watchlist empty:", dl.WATCHLIST_FILE)
        return

    from extract.auto_update import start_background_update

    start_background_update("chart")

    chart = Chart(toolbox=True, maximize=True, title="New Andicator")
    CHART = chart
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

    names = _symbol_names()
    if STATE.tf not in CHART_TF_LABELS:
        STATE.tf = "1d"
    if STATE.name not in names and names:
        STATE.name = names[0]
        STATE.ticker = STATE.name_map[STATE.name]
    _ensure_tf_available()

    chart.topbar.switcher("symbol", tuple(names), default=STATE.name, func=on_symbol)
    # menu supports update_items when symbol/adj changes
    chart.topbar.menu("timeframe", tuple(_timeframes_for_current()), default=STATE.tf, func=on_timeframe)
    chart.topbar.switcher("adj", tuple(dl.ADJ_LABELS), default=STATE.adj, func=on_adj)

    # Each indicator: Name | Off/On | ⚙  (one compact group)
    for label, key, _, default in INDICATORS:
        chart.topbar.textbox(f"lbl_{key}", label, align="left")
        chart.topbar.switcher(
            key,
            ("Off", "On"),
            default="On" if STATE.enabled.get(key, default) else "Off",
            func=make_toggle_handler(key),
        )
        chart.topbar.button(
            f"cfg_{key}",
            "⚙",
            separator=True,
            align="left",
            func=make_settings_handler(key),
        )

    def _on_reload_click(chart: Chart) -> None:
        print("manual reload…", flush=True)
        reload_chart(chart, force=True)

    chart.topbar.textbox("lbl_pivots", "Pivots", align="right")
    chart.topbar.switcher(
        "pivots",
        PIVOT_CHOICES,
        default=STATE.pivot_level,
        align="right",
        func=on_pivots,
    )
    chart.topbar.button("reload", "Load", separator=True, align="right", func=_on_reload_click)
    # Do NOT draw indicators before the webview exists — subpanes get clipped.
    # Load once immediately after show() via a short delayed callback from JS.
    def _bootstrap(chart: Chart) -> None:
        _layout_container(chart)
        _style_indicator_topbar(chart)
        reload_chart(chart, force=True)

    # Exposed as handler name "bootstrap" — invoked from JS after webview load.
    chart.win.handlers["bootstrap"] = lambda *_args: _bootstrap(chart)
    chart.win.handlers["pane_heights"] = _on_pane_heights_msg
    chart.win.handlers["data_poll"] = _on_data_poll
    chart.run_script(
        "setTimeout(() => { try { window.callbackFunction('bootstrap_~_1'); } catch (e) { console.error(e); } }, 400);",
        run_last=True,
    )
    chart.run_script(
        "setInterval(() => { try { window.callbackFunction('data_poll_~_1'); } catch (e) {} }, 10000);",
        run_last=True,
    )
    print("Chart ready. Use topbar to change symbol / TF / adj / indicators.", flush=True)
    print("Each indicator has Name + Off/On + gear (⚙) for settings.", flush=True)
    print("Drag the thin bars between panes to resize stock vs indicators.", flush=True)
    print("UI state saved to chart/ui_state.json; settings to chart/user_settings.json.", flush=True)
    print("If panes are empty, click Load once.", flush=True)
    # Capture current defaults once so first-ever launch still has a restore point.
    save_ui_state()
    chart.show(block=True)


if __name__ == "__main__":
    main()
