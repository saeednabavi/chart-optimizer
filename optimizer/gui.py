# -*- coding: utf-8 -*-
"""Window for the indicator input optimizer (run_optimizer.bat)."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import messagebox, ttk

from chart import data_loader as dl
from chart import indicator_settings as iset
from chart.swings import load_config
from optimizer.compare import ACT_FA, VERDICT_FA, best_lines, compare_lines, rank_results, save_compare
from optimizer.param_space import INDICATOR_LABELS
from optimizer.search import (DEPTHS, OUTPUT_DIR, PART_FA, PIVOT_PRICE_FA, RESULT_FA, Optimizer, RunConfig, fmt_price,
                              jalali_time, make_scenarios, parse_mults, save_result, summary_lines)

FONT = ("Tahoma", 10)
FONT_B = ("Tahoma", 10, "bold")
DEPTH_FA = {"fast": "سریع", "normal": "معمولی", "deep": "خیلی کامل (طولانی)"}
PHASE_FA = {
    "": "آماده‌سازی",
    "effect": "بررسی اثر هر ورودی",
    "grid": "جستجوی کامل همه‌ی ترکیب‌ها",
    "optuna": "جستجوی هوشمند (Optuna)",
    "refine": "جستجوی محلی از چند نقطه",
    "robust": "انتخاب جواب پایدار",
    "sensitivity": "حساسیت هر ورودی",
}
STATUS_FA = {"effective": "مؤثر", "no_effect": "بی‌اثر روی این سیگنال", "fixed": "ثابت (قانون کارفرما)"}
ALL_TF = "همه‌ی تایم‌فریم‌ها"
SWING_KEYS = ("pct", "min_bars", "atr_mult")
# Automatic top/bottom mode: 3 x 3 = 9 definitions around the timeframe default (ATR kept as is,
# because the default ATR multiple is 0 = off and scaling 0 changes nothing).
AUTO_PCT_MULTS = "0.75, 1, 1.33"
AUTO_BARS_MULTS = "0.7, 1, 1.4"
AUTO_ATR_MULTS = "1"
AUTO_AGG = "میانگین"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("بهینه‌ساز ورودی اندیکاتورها - سقف و کف")
        root.geometry("1320x820")
        try:
            root.state("zoomed")
        except tk.TclError:
            pass
        root.option_add("*Font", FONT)
        style = ttk.Style(root)
        style.configure("Treeview", font=FONT, rowheight=24)
        style.configure("Treeview.Heading", font=FONT_B)

        self.queue: "queue.Queue[tuple]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self.result: Optional[Dict[str, Any]] = None
        self.result_path: Optional[Path] = None

        self.watchlist = dl.load_watchlist()
        self.symbols = {f"{s['name']} ({s['ticker']})": s["ticker"] for s in self.watchlist}
        self.ind_by_label = {v: k for k, v in INDICATOR_LABELS.items()}

        self._build_form()
        self._build_tabs()
        self._on_symbol()
        self.root.after(200, self._poll)

    # ------------------------------------------------------------------ layout
    def _build_form(self) -> None:
        f = ttk.LabelFrame(self.root, text="انتخاب‌ها", padding=8)
        f.pack(side="right", fill="y", padx=6, pady=6)
        r = 0

        def label(text):
            nonlocal r
            ttk.Label(f, text=text).grid(row=r, column=1, sticky="e", pady=3)

        def place(widget):
            nonlocal r
            widget.grid(row=r, column=0, sticky="we", pady=3, padx=(0, 6))
            r += 1

        self.v_symbol = tk.StringVar(value=next(iter(self.symbols), ""))
        label("سهم")
        cb = ttk.Combobox(f, textvariable=self.v_symbol, values=list(self.symbols), state="readonly", width=28)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_symbol())
        place(cb)

        self.v_adj = tk.StringVar(value="adjusted")
        label("نوع داده")
        cb = ttk.Combobox(f, textvariable=self.v_adj, values=dl.ADJ_LABELS, state="readonly", width=28)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_symbol())
        place(cb)

        self.v_tf = tk.StringVar(value="1d")
        label("تایم‌فریم")
        self.cb_tf = ttk.Combobox(f, textvariable=self.v_tf, state="readonly", width=28)
        self.cb_tf.bind("<<ComboboxSelected>>", lambda e: self._on_tf())
        place(self.cb_tf)

        self.v_ind = tk.StringVar(value=INDICATOR_LABELS["vtx"])
        label("اندیکاتور")
        cb = ttk.Combobox(f, textvariable=self.v_ind, values=list(self.ind_by_label), state="readonly", width=28)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_indicator())
        place(cb)

        self.v_level = tk.StringVar(value="major")
        label("سقف/کف")
        lf = ttk.Frame(f)
        ttk.Radiobutton(lf, text="major (اساسی)", variable=self.v_level, value="major",
                        command=self._update_swing_state).pack(side="right")
        ttk.Radiobutton(lf, text="minor (جزئی)", variable=self.v_level, value="minor",
                        command=self._update_swing_state).pack(side="right")
        place(lf)

        self.v_side = tk.StringVar(value="buy")
        label("سیگنال")
        sf = ttk.Frame(f)
        ttk.Radiobutton(sf, text="خرید (کف‌ها)", variable=self.v_side, value="buy").pack(side="right")
        ttk.Radiobutton(sf, text="فروش (سقف‌ها)", variable=self.v_side, value="sell").pack(side="right")
        ttk.Radiobutton(sf, text="هر دو", variable=self.v_side, value="both").pack(side="right")
        place(sf)

        self.v_depth = tk.StringVar(value=DEPTH_FA["normal"])
        label("دقت جستجو")
        place(ttk.Combobox(f, textvariable=self.v_depth, values=[DEPTH_FA[d] for d in DEPTHS],
                           state="readonly", width=28))

        self.v_train = tk.IntVar(value=70)
        label("درصد داده‌ی آموزش")
        place(ttk.Spinbox(f, from_=40, to=95, increment=5, textvariable=self.v_train, width=8))

        self.v_maxbars = tk.IntVar(value=0)
        label("فقط N کندل آخر (0 = همه)")
        place(ttk.Spinbox(f, from_=0, to=1_000_000, increment=1000, textvariable=self.v_maxbars, width=10))

        self.v_vtx_levels = tk.BooleanVar(value=False)
        self.chk_vtx = ttk.Checkbutton(f, text="VTX: سطح ۳۰ و ۸۰ هم بهینه شود", variable=self.v_vtx_levels)
        self.chk_vtx.grid(row=r, column=0, columnspan=2, sticky="e", pady=3)
        r += 1

        sw = ttk.LabelFrame(f, text="تعریف سقف و کف هدف (حداقل حرکت / فاصله / ATR)", padding=6)
        sw.grid(row=r, column=0, columnspan=2, sticky="we", pady=8)
        r += 1
        self.v_swing_mode = tk.StringVar(value="manual")
        ttk.Radiobutton(sw, text="دستی (روشن): دقیقاً همین مقدارها استفاده شود", variable=self.v_swing_mode,
                        value="manual", command=self._on_swing_mode).grid(row=0, column=0, columnspan=4, sticky="e")
        grid = ttk.Frame(sw)
        grid.grid(row=1, column=0, columnspan=4, sticky="e", padx=(0, 18))
        self.sw_vars: Dict[str, tk.DoubleVar] = {}
        self.sw_widgets: Dict[str, ttk.Spinbox] = {}
        for i, name in enumerate(("minor", "major")):
            ttk.Label(grid, text=name, font=FONT_B).grid(row=0, column=2 - i)
        rows = (("pct", "حداقل حرکت %"), ("min_bars", "حداقل فاصله کندل"), ("atr_mult", "ضریب ATR (0=خاموش)"))
        for j, (key, text) in enumerate(rows, start=1):
            ttk.Label(grid, text=text).grid(row=j, column=3, sticky="e")
            for i, lvl in enumerate(("minor", "major")):
                v = tk.DoubleVar()
                self.sw_vars[f"{lvl}.{key}"] = v
                w = ttk.Spinbox(grid, from_=0, to=1000, increment=0.5, textvariable=v, width=7)
                w.grid(row=j, column=2 - i, padx=2, pady=2)
                self.sw_widgets[f"{lvl}.{key}"] = w

        ttk.Radiobutton(sw, text="خودکار (خاموش): بهینه‌ساز چند تعریف را خودش امتحان کند",
                        variable=self.v_swing_mode, value="auto", command=self._on_swing_mode).grid(
            row=2, column=0, columnspan=4, sticky="e", pady=(8, 0))
        self.v_advanced = tk.BooleanVar(value=False)
        self.chk_advanced = ttk.Checkbutton(sw, text="تنظیمات پیشرفته (لازم نیست تغییر کند)",
                                            variable=self.v_advanced, command=self._update_swing_state)
        self.chk_advanced.grid(row=3, column=0, columnspan=4, sticky="e", padx=(0, 18))
        auto = ttk.Frame(sw)
        auto.grid(row=4, column=0, columnspan=4, sticky="e", padx=(0, 18))
        self.auto_frame = auto
        self.v_pct_mults = tk.StringVar(value=AUTO_PCT_MULTS)
        self.v_bars_mults = tk.StringVar(value=AUTO_BARS_MULTS)
        self.v_atr_mults = tk.StringVar(value=AUTO_ATR_MULTS)
        self.auto_widgets = []
        for j, (var, text) in enumerate(((self.v_pct_mults, "ضرایب حداقل حرکت"),
                                         (self.v_bars_mults, "ضرایب حداقل فاصله کندل"),
                                         (self.v_atr_mults, "ضرایب ATR"))):
            ttk.Label(auto, text=text).grid(row=j, column=1, sticky="e")
            e = ttk.Entry(auto, textvariable=var, width=16, justify="left")
            e.grid(row=j, column=0, sticky="we", padx=(0, 6), pady=2)
            self.auto_widgets.append(e)
        self.v_agg = tk.StringVar(value=AUTO_AGG)
        ttk.Label(auto, text="امتیاز نهایی").grid(row=3, column=1, sticky="e")
        cb = ttk.Combobox(auto, textvariable=self.v_agg, values=["میانگین", "بدترین"], state="readonly", width=14)
        cb.grid(row=3, column=0, sticky="we", padx=(0, 6), pady=2)
        self.auto_widgets.append(cb)
        ttk.Button(auto, text="برگشت به مقدارهای پیشنهادی", command=self._reset_auto).grid(
            row=4, column=0, columnspan=2, sticky="e", pady=2)
        self.l_swing_note = ttk.Label(sw, foreground="#666", justify="right", wraplength=320)
        self.l_swing_note.grid(row=5, column=0, columnspan=4, sticky="e", pady=(6, 0))

        bf = ttk.Frame(f)
        bf.grid(row=r, column=0, columnspan=2, pady=10)
        self.btn_start = ttk.Button(bf, text="شروع بهینه‌سازی", command=self._start)
        self.btn_start.pack(side="right", padx=4)
        self.btn_stop = ttk.Button(bf, text="توقف", command=self._stop, state="disabled")
        self.btn_stop.pack(side="right", padx=4)
        r += 1
        self.btn_compare = ttk.Button(f, text="مقایسه‌ی همه‌ی اندیکاتورها و پیشنهاد بهترین", command=self._start_compare)
        self.btn_compare.grid(row=r, column=0, columnspan=2, sticky="we", pady=(0, 6))
        r += 1
        ttk.Label(f, foreground="#666", justify="right", wraplength=320, text=(
            "با «هر دو» یا «همه‌ی تایم‌فریم‌ها» همه‌ی حالت‌ها پشت سر هم اجرا می‌شوند و نتایج در تب "
            "«مقایسه‌ی اندیکاتورها» کنار هم نمایش داده می‌شوند.")).grid(row=r, column=0, columnspan=2, sticky="e")
        self._on_indicator()

    def _build_tabs(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        self.nb = nb

        # Progress
        p = ttk.Frame(nb, padding=8)
        nb.add(p, text="پیشرفت")
        self.l_phase = ttk.Label(p, text="-", font=FONT_B)
        self.l_phase.pack(anchor="e")
        self.pb = ttk.Progressbar(p, mode="determinate", maximum=1.0)
        self.pb.pack(fill="x", pady=4)
        self.l_best = ttk.Label(p, text="", justify="right")
        self.l_best.pack(anchor="e", fill="x")
        self.t_log = tk.Text(p, height=20, wrap="word", font=("Consolas", 9))
        self.t_log.pack(fill="both", expand=True, pady=4)

        # Results
        res = ttk.Frame(nb, padding=8)
        nb.add(res, text="نتایج")
        cols = ("key", "label", "default", "optimized", "status", "impact")
        heads = ("ورودی", "نام در اندیکاتور", "پیش‌فرض", "بهینه", "وضعیت", "اثر روی امتیاز")
        self.tv_inputs = ttk.Treeview(res, columns=cols, show="headings", height=12)
        for c, h, w in zip(cols, heads, (150, 260, 90, 90, 190, 110)):
            self.tv_inputs.heading(c, text=h)
            self.tv_inputs.column(c, width=w, anchor="center")
        self.tv_inputs.tag_configure("effective", background="#e8f5e9")
        self.tv_inputs.tag_configure("no_effect", background="#f5f5f5", foreground="#777")
        self.tv_inputs.tag_configure("fixed", background="#fff8e1")
        self.tv_inputs.tag_configure("display", background="#eceff1", foreground="#555")
        self.tv_inputs.pack(fill="x")

        mcols = ("row", "score", "random", "signals", "caught", "hit", "lag", "dist")
        mheads = ("", "امتیاز", "تصادفی", "تعداد سیگنال", "سقف/کف شکارشده", "سیگنال خوب", "تأخیر (کندل)",
                  "فاصله % (Close تا کف/سقف)")
        self.tv_metrics = ttk.Treeview(res, columns=mcols, show="headings", height=4)
        for c, h, w in zip(mcols, mheads, (170, 80, 80, 100, 130, 100, 100, 170)):
            self.tv_metrics.heading(c, text=h)
            self.tv_metrics.column(c, width=w, anchor="center")
        self.tv_metrics.pack(fill="x", pady=8)
        ttk.Label(res, foreground="#555", justify="right", text=(
            "امتیاز ۰ تا ۱: ۱ یعنی هر سیگنال دقیقاً روی سقف/کف و هر سقف/کف یک سیگنال دارد. "
            "«تصادفی» امتیاز همین تعداد سیگنال در جاهای تصادفی است.\n"
            "سیگنال خوب = سیگنالی که نزدیک‌تر از نصف همان موج به سقف/کف است. تأخیر منفی یعنی قبل از سقف/کف.\n"
            "مبنای قیمت: سقف روی High و کف روی Low کندل (سایه) پیدا می‌شود؛ کیفیت سیگنال با Low (خرید) / "
            "High (فروش) کندل سیگنال سنجیده می‌شود؛ «فاصله %» از قیمت Close کندل سیگنال تا کف/سقف است.")
        ).pack(anchor="e")

        bf = ttk.Frame(res)
        bf.pack(fill="x", pady=8)
        self.btn_chart = ttk.Button(bf, text="نمایش روی چارت", command=self._show_chart, state="disabled")
        self.btn_chart.pack(side="right", padx=4)
        self.btn_apply = ttk.Button(bf, text="ذخیره در تنظیمات چارت اصلی", command=self._apply, state="disabled")
        self.btn_apply.pack(side="right", padx=4)
        ttk.Button(bf, text="باز کردن پوشه‌ی نتایج", command=self._open_folder).pack(side="right", padx=4)

        # Summary
        s = ttk.Frame(nb, padding=8)
        nb.add(s, text="خلاصه")
        sb = ttk.Scrollbar(s, orient="vertical")
        sb.pack(side="left", fill="y")
        self.t_summary = tk.Text(s, wrap="word", font=("Tahoma", 11), yscrollcommand=sb.set)
        self.t_summary.pack(fill="both", expand=True)
        sb.configure(command=self.t_summary.yview)
        ts = self.t_summary
        ts.tag_configure("rtl", justify="right")
        ts.tag_configure("head", font=("Tahoma", 11, "bold"))
        ts.tag_configure("param", foreground="#d50000", font=("Tahoma", 12, "bold"))
        ts.tag_configure("warn", foreground="#e65100")
        ts.tag_configure("good", foreground="#1b5e20")
        ts.tag_configure("weak", foreground="#8d6e00")
        ts.tag_configure("bad", foreground="#b71c1c")
        ts.tag_configure("unconfirmed", foreground="#757575")

        # Trades of the optimized setting
        t = ttk.Frame(nb, padding=8)
        nb.add(t, text="خریدها / فروش‌ها")
        self.l_trades = ttk.Label(t, text="", font=FONT_B)
        self.l_trades.pack(anchor="e")
        tcols = ("n", "jtime", "time", "price", "touch", "part", "result", "pivot", "pprice", "dist", "lag")
        theads = ("#", "زمان (شمسی)", "زمان (میلادی)", "قیمت Close سیگنال", "Low/High کندل سیگنال", "بخش", "نتیجه",
                  "سقف/کف نزدیک", "قیمت سقف/کف (High/Low)", "فاصله Close %", "تأخیر (کندل)")
        tf_ = ttk.Frame(t)
        tf_.pack(fill="both", expand=True, pady=4)
        tsb = ttk.Scrollbar(tf_, orient="vertical")
        tsb.pack(side="left", fill="y")
        self.tv_trades = ttk.Treeview(tf_, columns=tcols, show="headings", yscrollcommand=tsb.set)
        tsb.configure(command=self.tv_trades.yview)
        for c, h, w in zip(tcols, theads, (50, 140, 140, 120, 130, 70, 230, 140, 150, 100, 90)):
            self.tv_trades.heading(c, text=h)
            self.tv_trades.column(c, width=w, anchor="center")
        for tag, bg in (("good", "#e8f5e9"), ("weak", "#fff8e1"), ("bad", "#ffebee"), ("unconfirmed", "#f5f5f5"),
                        ("missed", "#fce4ec")):
            self.tv_trades.tag_configure(tag, background=bg)
        self.tv_trades.tag_configure("catch", font=FONT_B)
        self.tv_trades.pack(fill="both", expand=True)
        ttk.Label(t, foreground="#555", justify="right", text=(
            "قیمت Close = قیمت پایانی کندلی که سیگنال در آن داده شد. Low/High کندل سیگنال = همان قیمتی که کیفیت "
            "سیگنال با آن سنجیده می‌شود (Low برای خرید، High برای فروش). سقف روی High و کف روی Low پیدا شده است.\n"
            "فاصله Close = اختلاف Close سیگنال با سقف/کف واقعی. تأخیر منفی یعنی قبل از سقف/کف. "
            "ردیف پررنگ = سیگنالی که آن سقف/کف را شکار کرده.")).pack(anchor="e")

        # Comparison of all indicators
        c = ttk.Frame(nb, padding=8)
        nb.add(c, text="مقایسه‌ی اندیکاتورها")
        self.cmp_tab = c
        self.l_best_ind = ttk.Label(c, text="", font=("Tahoma", 12, "bold"), foreground="#1b5e20",
                                    justify="right", wraplength=900)
        self.l_best_ind.pack(anchor="e", pady=(0, 6))
        ccols = ("rank", "tf", "side", "ind", "test", "default", "random", "train", "signals", "caught", "hit", "lag",
                 "dist", "verdict")
        cheads = ("رتبه", "تایم‌فریم", "سمت", "اندیکاتور", "امتیاز آزمون", "پیش‌فرض آزمون", "تصادفی", "امتیاز آموزش",
                  "سیگنال", "شکار", "سیگنال خوب", "تأخیر", "فاصله Close %", "وضعیت")
        cf = ttk.Frame(c)
        cf.pack(fill="both", expand=True)
        csb = ttk.Scrollbar(cf, orient="vertical")
        csb.pack(side="left", fill="y")
        self.tv_cmp = ttk.Treeview(cf, columns=ccols, show="headings", height=14, yscrollcommand=csb.set)
        csb.configure(command=self.tv_cmp.yview)
        for col, h, w in zip(ccols, cheads, (45, 70, 60, 220, 90, 95, 70, 90, 60, 70, 85, 60, 95, 140)):
            self.tv_cmp.heading(col, text=h)
            self.tv_cmp.column(col, width=w, anchor="center")
        for tag, bg in (("reliable", "#e8f5e9"), ("overfit", "#fff8e1"), ("random", "#ffebee"),
                        ("no_test", "#f5f5f5"), ("error", "#f5f5f5")):
            self.tv_cmp.tag_configure(tag, background=bg)
        self.tv_cmp.tag_configure("best", font=FONT_B, background="#c8e6c9")
        self.tv_cmp.bind("<Double-1>", self._on_cmp_open)
        self.tv_cmp.pack(fill="both", expand=True)
        ttk.Label(c, foreground="#555", justify="right", wraplength=900, text=(
            "هر اندیکاتور برای هر تایم‌فریم و هر سمت (خرید / فروش) جداگانه بهینه می‌شود و داخل گروه همان "
            "تایم‌فریم و سمت با امتیاز روی داده‌ی آزمون (بخشی که در بهینه‌سازی دیده نشده) رتبه می‌گیرد. "
            "«قابل اعتماد» = از سیگنال تصادفی بهتر است و امتیاز آزمونش خیلی کمتر از آموزش نیست. "
            "ردیف پررنگ با ★ = پیشنهاد هر گروه (بهترین اندیکاتور قابل اعتماد).\n"
            "فاصله Close % = فاصله‌ی Close کندل سیگنال تا کف (Low) یا سقف (High).\n"
            "روی هر ردیف دوبار کلیک کنید تا نتایج کامل همان اندیکاتور در تب‌های «نتایج»، «خلاصه» و «خریدها / فروش‌ها» "
            "باز شود (نمایش روی چارت و ذخیره هم از همان‌جا).")).pack(anchor="e", pady=6)
        self.cmp_rows: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ form events
    def _ticker(self) -> str:
        return self.symbols.get(self.v_symbol.get(), "")

    def _on_symbol(self) -> None:
        tfs = dl.available_timeframes(self._ticker(), self.v_adj.get())
        self.cb_tf["values"] = ([ALL_TF] if tfs else []) + tfs
        if self.v_tf.get() not in tfs and self.v_tf.get() != ALL_TF and tfs:
            self.v_tf.set("1d" if "1d" in tfs else tfs[0])
        self._on_tf()

    def _all_tf(self) -> bool:
        return self.v_tf.get() == ALL_TF

    def _on_tf(self) -> None:
        self._load_swing_defaults()
        self._update_swing_state()

    def _load_swing_defaults(self) -> None:
        cfg = load_config(None if self._all_tf() else self.v_tf.get()).to_dict()
        for lvl in ("minor", "major"):
            for key in SWING_KEYS:
                self.sw_vars[f"{lvl}.{key}"].set(cfg[lvl][key])
        self._atr_period = cfg["atr_period"]

    def _on_swing_mode(self) -> None:
        if self.v_swing_mode.get() == "auto":
            self._load_swing_defaults()
        self._update_swing_state()

    def _update_swing_state(self) -> None:
        manual = self.v_swing_mode.get() == "manual"
        level = self.v_level.get()
        editable = manual and not self._all_tf()
        for name, w in self.sw_widgets.items():
            w.configure(state="normal" if editable and name.startswith(level + ".") else "disabled")
        self.chk_advanced.configure(state="disabled" if manual else "normal")
        if manual or not self.v_advanced.get():
            self.auto_frame.grid_remove()
        else:
            self.auto_frame.grid()
        if manual:
            note = (f"فقط تعریف واردشده برای سطح {level} استفاده می‌شود و ورودی‌های اندیکاتور برای پیدا کردن "
                    "همین سقف/کف‌ها بهینه می‌شوند. سریع‌ترین حالت.")
        else:
            note = (f"پیشنهادی و بدون نیاز به تنظیم: از مقدار پیش‌فرض هر تایم‌فریم ۹ تعریف سقف/کف برای سطح {level} "
                    "ساخته می‌شود (حداقل حرکت کمی کمتر/همان/کمی بیشتر × حداقل فاصله کمتر/همان/بیشتر). "
                    "ورودی‌هایی انتخاب می‌شوند که به‌طور میانگین روی همه‌ی این تعریف‌ها خوب باشند، "
                    "پس نتیجه به یک عدد خاص وابسته نیست. زمان اجرا کمی بیشتر می‌شود.")
        if self._all_tf():
            note += ("\nبا «همه‌ی تایم‌فریم‌ها» هر تایم‌فریم مقدار پیش‌فرض خودش را از swing_settings.json می‌گیرد "
                     "(اعداد بالا فقط پیش‌فرض عمومی است و قابل ویرایش نیست).")
        self.l_swing_note.configure(text=note)

    def _reset_auto(self) -> None:
        self.v_pct_mults.set(AUTO_PCT_MULTS)
        self.v_bars_mults.set(AUTO_BARS_MULTS)
        self.v_atr_mults.set(AUTO_ATR_MULTS)
        self.v_agg.set(AUTO_AGG)

    def _on_indicator(self) -> None:
        self.chk_vtx.configure(state="normal" if self.ind_by_label.get(self.v_ind.get()) == "vtx" else "disabled")

    # ------------------------------------------------------------------ run
    def _targets(self) -> tuple:
        """(timeframes, sides) selected in the form."""
        tfs = [t for t in self.cb_tf["values"] if t != ALL_TF] if self._all_tf() else [self.v_tf.get()]
        side = self.v_side.get()
        return list(tfs), (["buy", "sell"] if side == "both" else [side])

    def _swing_for(self, tf: str) -> tuple:
        """(swing, scenarios) used for one timeframe."""
        level = self.v_level.get()
        if self.v_swing_mode.get() == "manual" and not self._all_tf():
            swing = {"atr_period": getattr(self, "_atr_period", 50)}
            for lvl in ("minor", "major"):
                swing[lvl] = {
                    "pct": float(self.sw_vars[f"{lvl}.pct"].get()),
                    "min_bars": int(self.sw_vars[f"{lvl}.min_bars"].get()),
                    "atr_mult": float(self.sw_vars[f"{lvl}.atr_mult"].get()),
                }
        else:
            swing = load_config(tf).to_dict()
        scenarios = []
        if self.v_swing_mode.get() == "auto":
            scenarios = make_scenarios(swing, level, parse_mults(self.v_pct_mults.get()),
                                       parse_mults(self.v_bars_mults.get()), parse_mults(self.v_atr_mults.get()))
        return swing, scenarios

    def _run_config(self, tf: str, side: str) -> RunConfig:
        depth = next(k for k, v in DEPTH_FA.items() if v == self.v_depth.get())
        swing, scenarios = self._swing_for(tf)
        return RunConfig(
            ticker=self._ticker(), tf=tf, adj=self.v_adj.get(),
            ind=self.ind_by_label[self.v_ind.get()], side=side, level=self.v_level.get(),
            depth=depth, train_frac=max(0.4, min(0.95, self.v_train.get() / 100)),
            optimize_vtx_levels=bool(self.v_vtx_levels.get()), max_bars=int(self.v_maxbars.get() or 0),
            swing=swing, swing_scenarios=scenarios,
            scenario_agg="min" if self.v_agg.get() == "بدترین" else "mean",
            swing_mode=self.v_swing_mode.get(),
        )

    def _batch_configs(self) -> Optional[list]:
        """One RunConfig per (timeframe, side), or None after showing an error."""
        tfs, sides = self._targets()
        if not tfs:
            messagebox.showerror("خطا", "برای این سهم داده‌ای پیدا نشد.")
            return None
        try:
            return [self._run_config(tf, side) for tf in tfs for side in sides]
        except (tk.TclError, ValueError) as ex:
            messagebox.showerror("خطا", f"ورودی نامعتبر: {ex}")
            return None

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        cfgs = self._batch_configs()
        if not cfgs:
            return
        if len(cfgs) > 1:
            self._start_batch(cfgs, [cfgs[0].ind])
            return
        cfg = cfgs[0]
        self.stop_event.clear()
        self.result = None
        self.t_log.delete("1.0", "end")
        self._set_running()
        self._log(f"شروع: {cfg.ticker} {cfg.tf} {cfg.ind} {cfg.side} {cfg.level} دقت={cfg.depth}")
        self.worker = threading.Thread(target=self._work, args=(cfg,), daemon=True)
        self.worker.start()

    def _set_running(self) -> None:
        self.btn_start.configure(state="disabled")
        self.btn_compare.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_chart.configure(state="disabled")
        self.btn_apply.configure(state="disabled")
        self.nb.select(0)

    def _start_compare(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        cfgs = self._batch_configs()
        if cfgs:
            self._start_batch(cfgs, list(INDICATOR_LABELS))

    def _start_batch(self, cfgs: list, inds: list) -> None:
        tfs = list(dict.fromkeys(c.tf for c in cfgs))
        sides = list(dict.fromkeys(c.side for c in cfgs))
        total = len(cfgs) * len(inds)
        acts = " و ".join(ACT_FA[s] for s in sides)
        what = (f"همه‌ی {len(inds)} اندیکاتور" if len(inds) > 1 else f"اندیکاتور {INDICATOR_LABELS[inds[0]]}")
        if not messagebox.askyesno("مقایسه", f"{what} برای {acts} در {len(tfs)} تایم‌فریم ({', '.join(tfs)}) "
                                              f"یکی‌یکی بهینه و مقایسه می‌شوند.\nتعداد کل اجراها: {total} "
                                              f"(زمان حدود {total} برابر یک بهینه‌سازی؛ دقت «سریع» زودتر تمام "
                                              f"می‌شود). ادامه؟"):
            return
        c0 = cfgs[0]
        meta = {"ticker": c0.ticker, "adj": c0.adj, "level": c0.level, "depth": c0.depth, "tfs": tfs,
                "sides": sides, "swing_mode": c0.swing_mode}
        self.stop_event.clear()
        self.result = None
        self.t_log.delete("1.0", "end")
        self.tv_cmp.delete(*self.tv_cmp.get_children())
        self.cmp_rows = {}
        self.l_best_ind.configure(text="")
        self._set_running()
        self._log(f"شروع مقایسه: {c0.ticker} تایم‌فریم‌ها={','.join(tfs)} سمت={','.join(sides)} {c0.level} "
                  f"دقت={c0.depth} تعداد اجرا={total}")
        self.worker = threading.Thread(target=self._work_batch, args=(cfgs, inds, meta), daemon=True)
        self.worker.start()

    def _work_batch(self, cfgs: list, inds: list, meta: Dict[str, Any]) -> None:
        results, paths, errors = [], {}, {}
        jobs = [(cfg, ind) for cfg in cfgs for ind in inds]
        for n, (cfg, ind) in enumerate(jobs, 1):
            if self.stop_event.is_set():
                break
            label = INDICATOR_LABELS[ind]
            prefix = f"[{n}/{len(jobs)} | {cfg.tf} | {ACT_FA[cfg.side]} | {label}] "
            self.queue.put(("progress", {"phase": "", "msg": prefix + "شروع", "evals": 0, "best": -1,
                                         "elapsed": 0.0}))

            def progress(info, prefix=prefix):
                self.queue.put(("progress", {**info, "msg": prefix + info["msg"]}))

            key = (cfg.tf, cfg.side, ind)
            try:
                one = replace(cfg, ind=ind, optimize_vtx_levels=cfg.optimize_vtx_levels and ind == "vtx")
                res = Optimizer(one, progress, self.stop_event).run()
                paths[key] = save_result(res)
                results.append(res)
                m = res["metrics"]["optimized"]["test"]
                self.queue.put(("log", f"{prefix}تمام شد: امتیاز آزمون {m['score']:.3f}"))
            except Exception:
                errors[key] = label
                self.queue.put(("log", prefix + "خطا:\n" + traceback.format_exc()))
        try:
            rows = rank_results(results, errors, meta["tfs"], meta["sides"])
            path = save_compare(rows, meta) if rows else None
            self.queue.put(("compare_done", (rows, paths, path, meta)))
        except Exception:
            self.queue.put(("error", traceback.format_exc()))

    def _work(self, cfg: RunConfig) -> None:
        try:
            res = Optimizer(cfg, lambda info: self.queue.put(("progress", info)), self.stop_event).run()
            path = save_result(res)
            self.queue.put(("done", (res, path)))
        except Exception:
            self.queue.put(("error", traceback.format_exc()))

    def _stop(self) -> None:
        self.stop_event.set()
        self._log("توقف درخواست شد؛ بهترین جواب تا الان گزارش می‌شود...")

    def _poll(self) -> None:
        last_progress = None
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    last_progress = payload
                    if payload.get("done") in (None, payload.get("total")):
                        self._log(payload["msg"])
                elif kind == "done":
                    if last_progress:
                        self._show_progress(last_progress)
                        last_progress = None
                    self._finish(*payload)
                elif kind == "log":
                    self._log(payload)
                elif kind == "compare_done":
                    if last_progress:
                        self._show_progress(last_progress)
                        last_progress = None
                    self._finish_compare(*payload)
                elif kind == "error":
                    self._log(payload)
                    messagebox.showerror("خطا", payload[-1500:])
                    self._reset_buttons()
        except queue.Empty:
            pass
        if last_progress:
            self._show_progress(last_progress)
        self.root.after(200, self._poll)

    def _show_progress(self, info: Dict[str, Any]) -> None:
        phase = PHASE_FA.get(info.get("phase", ""), info.get("phase", ""))
        self.l_phase.configure(text=f"{phase}  |  {info['msg']}")
        done, total = info.get("done"), info.get("total")
        self.pb["value"] = (done / total) if done and total else 0
        best = info.get("best", -1)
        params = ", ".join(f"{k}={v}" for k, v in (info.get("best_params") or {}).items())
        self.l_best.configure(text=(f"بهترین امتیاز آموزش تا الان: {best:.4f}   |   ارزیابی‌ها: {info['evals']:,}   |   "
                                    f"زمان: {info['elapsed']:.0f} ثانیه\n{params}") if best >= 0 else "")

    def _log(self, text: str) -> None:
        self.t_log.insert("end", text + "\n")
        self.t_log.see("end")

    def _reset_buttons(self) -> None:
        self.btn_start.configure(state="normal")
        self.btn_compare.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    # ------------------------------------------------------------------ results
    def _finish(self, res: Dict[str, Any], path: Path) -> None:
        self._reset_buttons()
        self._log(f"تمام شد. ذخیره شد: {path}")
        self._show_result(res, path)
        self.nb.select(1)

    def _finish_compare(self, rows, paths: Dict[tuple, Path], path: Optional[Path], meta: Dict[str, Any]) -> None:
        self._reset_buttons()
        tv = self.tv_cmp
        tv.delete(*tv.get_children())
        self.cmp_rows = {}
        for r in rows:
            head = (r["rank"], r["tf"], ACT_FA[r["side"]])
            if r["verdict"] == "error":
                tv.insert("", "end", values=head + (r["label"],) + ("-",) * 9 + (VERDICT_FA["error"],),
                          tags=("error",))
                continue
            iid = tv.insert("", "end", values=head + (
                ("★ " if r["recommended"] else "") + r["label"], f"{r['test_score']:.3f}",
                f"{r['default_test']:.3f}", f"{r['random']:.3f}", f"{r['train_score']:.3f}", r["signals"],
                f"{r['caught']}/{r['pivots']}", f"{r['hit_rate'] * 100:.0f}%", _num(r["lag"], "{:+.1f}"),
                _num(r["dist"], "{:.1f}"), VERDICT_FA[r["verdict"]]),
                tags=("best",) if r["recommended"] else (r["verdict"],))
            self.cmp_rows[iid] = {"res": r["res"], "path": paths.get((r["tf"], r["side"], r["ind"]))}
        best = best_lines(rows)
        self.l_best_ind.configure(text="\n".join(best) if best else "هیچ اندیکاتوری نتیجه نداد.")
        self._log("\n".join(compare_lines(rows, meta)))
        if path:
            self._log(f"مقایسه ذخیره شد: {path}")
        first = next((r for r in rows if r["recommended"]), None)
        if first:
            self._show_result(first["res"], paths.get((first["tf"], first["side"], first["ind"])))
        self.nb.select(self.cmp_tab)

    def _on_cmp_open(self, event) -> None:
        item = self.cmp_rows.get(self.tv_cmp.identify_row(event.y))
        if item:
            self._show_result(item["res"], item["path"])
            self.nb.select(1)

    def _show_result(self, res: Dict[str, Any], path: Optional[Path]) -> None:
        self.result, self.result_path = res, path
        self.btn_chart.configure(state="normal" if path else "disabled")
        self.btn_apply.configure(state="normal")

        tv = self.tv_inputs
        tv.delete(*tv.get_children())
        for i in res["inputs"]:
            sens = i.get("sensitivity") or {}
            impact = f"{sens['impact']:.3f}" if sens else "-"
            status = STATUS_FA[i["status"]]
            if sens and sens["max"] - sens["min"] < 1e-12:
                status = "بی‌اثر با بقیه‌ی تنظیمات"
            tv.insert("", "end", values=(i["key"], i["label"], i["default"], i["optimized"], status, impact),
                      tags=(i["status"],))
        for k in res["display_inputs"]:
            tv.insert("", "end", values=(k, "", "", "", "نمایشی", "-"), tags=("display",))
        if res["style_labels"]:
            tv.insert("", "end", values=("Style", "همه‌ی تنظیمات تب Style", "", "", "نمایشی", "-"), tags=("display",))

        tm = self.tv_metrics
        tm.delete(*tm.get_children())
        m = res["metrics"]
        for name, which, part in (("پیش‌فرض / آموزش", "default", "train"), ("بهینه / آموزش", "optimized", "train"),
                                  ("پیش‌فرض / آزمون", "default", "test"), ("بهینه / آزمون", "optimized", "test")):
            d = m[which][part]
            tm.insert("", "end", values=(
                name, f"{d['score']:.3f}", f"{d['random_baseline']:.3f}", d["signals"],
                f"{d['caught']}/{d['pivots']}", f"{d['hit_rate'] * 100:.0f}%",
                _num(d["avg_lag_bars"], "{:+.1f}"), _num(d["avg_dist_pct"], "{:.1f}")))

        self.t_summary.delete("1.0", "end")
        for text, tag in summary_lines(res):
            self.t_summary.insert("end", text + "\n", ("rtl", tag) if tag else "rtl")
        self._fill_trades(res)

    def _fill_trades(self, res: Dict[str, Any]) -> None:
        buy = res["config"]["side"] == "buy"
        act, pivot_fa = ("خرید", "کف") if buy else ("فروش", "سقف")
        ext = PIVOT_PRICE_FA["buy" if buy else "sell"]
        trades = res.get("trades") or []
        missed = res.get("missed_pivots") or []
        tv = self.tv_trades
        tv.heading("touch", text=f"{ext} کندل سیگنال")
        tv.heading("pivot", text=f"{pivot_fa} نزدیک")
        tv.heading("pprice", text=f"قیمت {pivot_fa} ({ext})")
        tv.heading("dist", text=f"فاصله Close تا {pivot_fa} %")
        tv.delete(*tv.get_children())
        for n, t in enumerate(trades, 1):
            result = RESULT_FA[t["result"]] + (f" - شکار {pivot_fa}" if t["catch"] else "")
            has_pivot = bool(t["pivot_time"])
            tv.insert("", "end", values=(
                n, jalali_time(t["time"]), t["time"][:16], fmt_price(t["price"]), fmt_price(t.get("touch")),
                PART_FA[t["part"]], result,
                jalali_time(t["pivot_time"]) if has_pivot else "-",
                fmt_price(t["pivot_price"]) if has_pivot else "-",
                f"{t['dist_pct']:+.2f}" if has_pivot else "-",
                f"{t['lag_bars']:+d}" if has_pivot else "-"),
                tags=(t["result"],) + (("catch",) if t["catch"] else ()))
        for p in missed:
            tv.insert("", "end", values=(
                "-", "", "", "", "", PART_FA[p["part"]], f"{pivot_fa} بدون {act} خوب",
                jalali_time(p["time"]), fmt_price(p["price"]), "-", "-"), tags=("missed",))
        good = sum(t["result"] == "good" for t in trades)
        cfg = res["config"]
        self.l_trades.configure(text=f"{cfg['tf']} | {res['indicator_label']} | {len(trades)} {act} با تنظیمات بهینه | "
                                     f"خوب: {good} | {pivot_fa} شکارنشده: {len(missed)} | "
                                     f"{pivot_fa} روی {ext}، قیمت سیگنال = Close")

    def _show_chart(self) -> None:
        if not self.result_path:
            return
        subprocess.Popen([sys.executable, "-m", "optimizer.viewer", str(self.result_path)], cwd=str(ROOT))

    def _apply(self) -> None:
        res = self.result
        if not res:
            return
        ind = res["config"]["ind"]
        side = "فروش" if res["config"]["side"] == "sell" else "خرید"
        if not messagebox.askyesno("ذخیره", f"ورودی‌های بهینه‌ی {side} در تنظیمات اندیکاتور {res['indicator_label']} "
                                            f"در چارت اصلی نوشته شود؟\n(تنظیمات فعلی این اندیکاتور عوض می‌شود)"):
            return
        settings = iset.load_settings()
        cfg = settings.setdefault(ind, {})
        for i in res["inputs"]:
            if not i["rule_only"]:
                cfg[i["key"]] = i["optimized"]
        if ind == "vtx":
            opt = res["optimized_params"]
            cfg["oversold_value"] = float(opt.get("buy_level", 30))
            cfg["overbought_value"] = float(opt.get("sell_level", 80))
        iset.save_settings(settings)
        messagebox.showinfo("ذخیره", "ذخیره شد. چارت اصلی را دوباره باز کنید یا Load بزنید.")

    def _open_folder(self) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(OUTPUT_DIR))


def _num(v, fmt: str) -> str:
    try:
        return "-" if v is None or v != v else fmt.format(v)
    except (TypeError, ValueError):
        return "-"


def main() -> None:
    from extract.auto_update import start_background_update

    start_background_update("optimizer")
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
