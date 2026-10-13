# -*- coding: utf-8 -*-
"""Chartix-identical Settings dialog: single indicator, Inputs / Style / Visibility."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from typing import Any, Callable, Dict, Optional

from chart import indicator_settings as iset


# Chartix / TradingView dark dialog palette
_BG = "#1e222d"
_BG2 = "#2a2e39"
_FG = "#d1d4dc"
_MUTED = "#787b86"
_ACCENT = "#2962ff"
_BORDER = "#363a45"
_OK = "#2962ff"


def open_settings_dialog(
    current: Dict[str, Dict[str, Any]],
    on_apply: Optional[Callable[..., None]] = None,
    focus_key: Optional[str] = None,
) -> Optional[Dict[str, Dict[str, Any]]]:
    """
    Open a Chartix-style properties dialog for ONE indicator.
    Matches: title, Inputs/Style/Visibility tabs, Defaults/Cancel/Ok footer.
    """
    original = copy.deepcopy(current)
    working = copy.deepcopy(current)
    for k in list(working.keys()):
        working[k] = iset._apply_legacy_aliases(k, working[k])
    result_holder: Dict[str, Any] = {"value": None, "dirty": False}
    live_job: Dict[str, Any] = {"id": None}
    suspend_live = {"on": False}

    keys = list(iset.SCHEMAS.keys())
    active = focus_key if focus_key in keys else keys[0]

    root = tk.Tk()
    root.title(iset.SCHEMAS[active]["title"])
    root.minsize(420, 520)
    root.configure(bg=_BG)
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    # Center on screen
    win_w, win_h = 560, 680
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = max(0, (sw - win_w) // 2)
    y = max(0, (sh - win_h) // 2)
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(".", background=_BG, foreground=_FG, fieldbackground=_BG2)
    style.configure("TFrame", background=_BG)
    style.configure("TLabel", background=_BG, foreground=_FG)
    style.configure("TCheckbutton", background=_BG, foreground=_FG)
    style.configure("TButton", background=_BG2, foreground=_FG, padding=6)
    style.configure("Ok.TButton", background=_OK, foreground="#ffffff", padding=8)
    style.map("Ok.TButton", background=[("active", "#1e4fd6")])
    style.configure("TNotebook", background=_BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=_BG, foreground=_MUTED, padding=[16, 8])
    style.map(
        "TNotebook.Tab",
        background=[("selected", _BG)],
        foreground=[("selected", "#ffffff")],
    )
    style.configure("TEntry", fieldbackground=_BG2, foreground=_FG)
    style.configure(
        "TCombobox",
        fieldbackground=_BG2,
        background=_BG2,
        foreground=_FG,
        arrowcolor=_FG,
        bordercolor=_BORDER,
        lightcolor=_BG2,
        darkcolor=_BG2,
        insertcolor=_FG,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", _BG2), ("focus", _BG2), ("disabled", _BG2)],
        foreground=[("readonly", _FG), ("focus", "#ffffff"), ("disabled", _MUTED)],
        selectbackground=[("readonly", _BG2), ("focus", _ACCENT)],
        selectforeground=[("readonly", _FG), ("focus", "#ffffff")],
        background=[("readonly", _BG2)],
        arrowcolor=[("readonly", _FG)],
    )
    root.option_add("*TCombobox*Listbox.background", _BG2)
    root.option_add("*TCombobox*Listbox.foreground", _FG)
    root.option_add("*TCombobox*Listbox.selectBackground", _ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    style.configure("Muted.TLabel", background=_BG, foreground=_MUTED)
    style.configure("Section.TLabel", background=_BG, foreground=_MUTED, font=("Segoe UI", 8, "bold"))

    outer = ttk.Frame(root, padding=(14, 10, 14, 10))
    outer.pack(fill=tk.BOTH, expand=True)

    # Header: title only (each indicator opens its own settings via gear button)
    head = ttk.Frame(outer)
    head.pack(fill=tk.X, pady=(0, 4))
    title_var = tk.StringVar(value=iset.SCHEMAS[active]["title"])
    title_lbl = ttk.Label(head, textvariable=title_var, font=("Segoe UI", 14, "bold"))
    title_lbl.pack(side=tk.LEFT, anchor="w")

    # Footer Chartix order: Defaults left, Cancel + Ok right
    footer = ttk.Frame(outer)
    footer.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
    sep = tk.Frame(footer, height=1, bg=_BORDER)
    sep.pack(fill=tk.X, pady=(0, 8))
    btn_row = ttk.Frame(footer)
    btn_row.pack(fill=tk.X)

    tabs = ttk.Notebook(outer)
    tabs.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

    inp_tab = ttk.Frame(tabs)
    sty_tab = ttk.Frame(tabs)
    vis_tab = ttk.Frame(tabs)
    tabs.add(inp_tab, text="Inputs")
    tabs.add(sty_tab, text="Style")
    tabs.add(vis_tab, text="Visibility")

    def _scrollable(parent):
        canvas = tk.Canvas(parent, bg=_BG, highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(4, 6, 18, 6))
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _stretch(_evt=None):
            canvas.itemconfigure(win, width=max(280, canvas.winfo_width()))

        canvas.bind("<Configure>", _stretch)
        canvas.configure(yscrollcommand=sb.set)

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        return inner

    inp_inner = _scrollable(inp_tab)
    sty_inner = _scrollable(sty_tab)
    vis_inner = _scrollable(vis_tab)

    widgets: Dict[str, Any] = {}
    active_key = {"k": active}

    def _clear(frame):
        for child in frame.winfo_children():
            child.destroy()

    def _swatch(parent, var: tk.StringVar, row: int, col: int = 2):
        # Tk rejects rgba()/named chart colors. Show a hex chip; keep the real value in the variable.
        shown = iset._norm_color(var.get(), "#888888")
        try:
            sw = tk.Label(parent, width=3, background=shown, relief=tk.SOLID, bd=1)
        except tk.TclError:
            shown = "#888888"
            sw = tk.Label(parent, width=3, background=shown, relief=tk.SOLID, bd=1)

        def _pick(v=var, s=sw):
            initial = iset._norm_color(v.get(), "#888888")
            try:
                _, hx = colorchooser.askcolor(color=initial, parent=root)
            except tk.TclError:
                _, hx = colorchooser.askcolor(color="#888888", parent=root)
            if hx:
                v.set(hx)
                try:
                    s.configure(background=hx)
                except tk.TclError:
                    pass

        sw.bind("<Button-1>", lambda e: _pick())
        sw.grid(row=row, column=col, padx=4, sticky="w")

    def _schedule_live(*_args):
        if suspend_live["on"] or on_apply is None:
            return
        if live_job["id"] is not None:
            try:
                root.after_cancel(live_job["id"])
            except Exception:
                pass
        live_job["id"] = root.after(160, _push_live)

    def _push_live():
        live_job["id"] = None
        if suspend_live["on"] or on_apply is None:
            return
        try:
            _flush()
        except Exception:
            return
        updated = {k: iset._apply_legacy_aliases(k, copy.deepcopy(v)) for k, v in working.items()}
        try:
            on_apply(updated, active_key["k"])
            result_holder["dirty"] = True
        except Exception as ex:
            print(f"live settings apply failed: {ex}", flush=True)

    def _bind(fkey: str, kind: str, var, field=None):
        if field is not None:
            widgets[fkey] = (kind, var, field)
        else:
            widgets[fkey] = (kind, var)
        try:
            var.trace_add("write", _schedule_live)
        except Exception:
            pass

    def _chip(parent, var: tk.StringVar):
        shown = iset._norm_color(var.get(), "#888888")
        try:
            sw = tk.Label(parent, width=3, background=shown, relief=tk.SOLID, bd=1, cursor="hand2")
        except tk.TclError:
            shown = "#888888"
            sw = tk.Label(parent, width=3, background=shown, relief=tk.SOLID, bd=1, cursor="hand2")

        def _pick(v=var, s=sw):
            initial = iset._norm_color(v.get(), "#888888")
            try:
                _, hx = colorchooser.askcolor(color=initial, parent=root)
            except tk.TclError:
                _, hx = colorchooser.askcolor(color="#888888", parent=root)
            if hx:
                v.set(hx)
                try:
                    s.configure(background=hx)
                except tk.TclError:
                    pass

        sw.bind("<Button-1>", lambda e: _pick())
        sw.pack(side=tk.LEFT, padx=3)
        return sw

    def _info_badge(parent, text: str):
        c = tk.Canvas(parent, width=16, height=16, bg=_BG, highlightthickness=0, cursor="hand2")
        c.create_oval(1, 1, 15, 15, outline=_MUTED)
        c.create_text(8, 8, text="i", fill=_MUTED, font=("Segoe UI", 8, "bold"))
        tip = {"win": None}

        def _show(_e=None):
            if tip["win"] is not None:
                return
            tw = tk.Toplevel(root)
            tw.wm_overrideredirect(True)
            try:
                tw.attributes("-topmost", True)
            except Exception:
                pass
            lbl = tk.Label(
                tw, text=text, bg=_BG2, fg=_FG, wraplength=260, justify="left", padx=8, pady=6
            )
            lbl.pack()
            tw.geometry(f"+{c.winfo_rootx() + 18}+{c.winfo_rooty() - 4}")
            tip["win"] = tw

        def _hide(_e=None):
            if tip["win"] is not None:
                try:
                    tip["win"].destroy()
                except Exception:
                    pass
                tip["win"] = None

        c.bind("<Enter>", _show)
        c.bind("<Leave>", _hide)
        return c

    def _draw_line(canvas, color, style, width):
        canvas.delete("all")
        hx = iset._norm_color(color, "#d1d4dc")
        try:
            w = max(1, min(4, int(float(width))))
        except (TypeError, ValueError):
            w = 2
        dash = ()
        if str(style) == "dotted":
            dash = (1, 2)
        elif str(style) == "dashed":
            dash = (4, 3)
        try:
            canvas.create_line(6, 12, 36, 12, fill=hx, width=w, dash=dash, capstyle="round")
        except tk.TclError:
            canvas.create_line(6, 12, 36, 12, fill="#d1d4dc", width=w, dash=dash, capstyle="round")

    def _draw_ptype(canvas, kind: str):
        canvas.delete("all")
        c = _FG
        k = str(kind)
        if k == "histogram":
            for x, h in ((6, 8), (13, 14), (20, 6), (27, 11)):
                canvas.create_rectangle(x, 18 - h, x + 5, 18, outline=c)
        elif k == "circles":
            canvas.create_oval(7, 8, 13, 14, outline=c)
            canvas.create_oval(15, 5, 21, 11, outline=c)
            canvas.create_oval(20, 12, 26, 18, outline=c)
        elif k == "cross":
            canvas.create_line(8, 7, 16, 15, fill=c)
            canvas.create_line(16, 7, 8, 15, fill=c)
            canvas.create_line(20, 8, 28, 16, fill=c)
            canvas.create_line(28, 8, 20, 16, fill=c)
        elif k == "columns":
            canvas.create_rectangle(7, 9, 14, 18, outline=c)
            canvas.create_rectangle(16, 5, 23, 18, outline=c)
            canvas.create_rectangle(25, 11, 32, 18, outline=c)
        elif k == "area":
            canvas.create_polygon(4, 16, 12, 8, 20, 12, 34, 5, 34, 18, 4, 18, outline=c, fill="")
        else:
            canvas.create_line(4, 14, 12, 8, 18, 13, 26, 6, 36, 11, fill=c, smooth=True)

    def _draw_shape(canvas, icon: str):
        canvas.delete("all")
        c = _FG
        if icon in ("label_down", "triangle_down"):
            canvas.create_polygon(8, 6, 28, 6, 18, 18, outline=c, fill="")
        elif icon in ("label_up", "triangle_up"):
            canvas.create_polygon(18, 5, 28, 17, 8, 17, outline=c, fill="")
        else:
            canvas.create_oval(10, 6, 26, 18, outline=c)

    def _float_popup(widget):
        top = tk.Toplevel(root)
        top.overrideredirect(True)
        top.configure(bg=_BORDER)
        try:
            top.attributes("-topmost", True)
        except Exception:
            pass
        inner = tk.Frame(top, bg=_BG)
        inner.pack(padx=1, pady=1)
        holder = {"id": None}

        def _outside(event):
            try:
                wx, wy = top.winfo_rootx(), top.winfo_rooty()
                ww, wh = top.winfo_width(), top.winfo_height()
            except tk.TclError:
                return
            if wx <= event.x_root <= wx + ww and wy <= event.y_root <= wy + wh:
                return
            close()

        def _arm():
            holder["id"] = root.bind_all("<Button-1>", _outside, add="+")

        def close(_e=None):
            if holder["id"] is not None:
                try:
                    root.unbind_all("<Button-1>")
                except Exception:
                    pass
                holder["id"] = None
            try:
                top.destroy()
            except Exception:
                pass

        root.after(120, _arm)
        top.bind("<Escape>", close)
        x = widget.winfo_rootx()
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        top.geometry(f"+{x}+{y}")
        return top, inner, close

    def _edit_line(widget, ls_var, lw_var, color_var, with_width: bool):
        top, inner, close = _float_popup(widget)
        tk.Label(inner, text="Line", bg=_BG, fg=_MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=8, pady=(6, 0))
        rowf = tk.Frame(inner, bg=_BG)
        rowf.pack(anchor="w", padx=6, pady=4)

        def pick(style):
            ls_var.set(style)
            close()

        for style in iset.LINESTYLE_CHOICES:
            c = tk.Canvas(rowf, width=42, height=24, bg=_BG2, highlightthickness=1, highlightbackground=_BORDER, cursor="hand2")
            width = lw_var.get() if lw_var is not None else 2
            _draw_line(c, color_var.get(), style, width)
            c.pack(side=tk.LEFT, padx=2, pady=2)
            c.bind("<Button-1>", lambda e, s=style: pick(s))
        if with_width and lw_var is not None:
            tk.Label(inner, text="Thickness", bg=_BG, fg=_MUTED, font=("Segoe UI", 8)).pack(anchor="w", padx=8)
            spin = tk.Spinbox(
                inner,
                from_=1,
                to=40,
                width=5,
                textvariable=lw_var,
                bg=_BG2,
                fg=_FG,
                buttonbackground=_BG2,
                justify="center",
            )
            spin.pack(anchor="w", padx=8, pady=(2, 8))

    def _edit_ptype(widget, pt_var):
        top, inner, close = _float_popup(widget)
        rowf = tk.Frame(inner, bg=_BG)
        rowf.pack(padx=4, pady=4)
        choices = [c for c in iset.PLOTTYPE_CHOICES if c != "shape"]

        def pick(name):
            pt_var.set(name)
            close()

        for name in choices:
            c = tk.Canvas(rowf, width=36, height=24, bg=_BG2, highlightthickness=1, highlightbackground=_BORDER, cursor="hand2")
            _draw_ptype(c, name)
            c.pack(side=tk.LEFT, padx=2, pady=2)
            c.bind("<Button-1>", lambda e, n=name: pick(n))

    def _line_button(parent, color_var, ls_var, lw_var=None, with_width: bool = True):
        box = tk.Canvas(
            parent, width=42, height=24, bg=_BG2, highlightthickness=1, highlightbackground=_BORDER, cursor="hand2"
        )

        def redraw(*_a):
            width = 2
            if lw_var is not None:
                try:
                    width = lw_var.get()
                except Exception:
                    width = 2
            _draw_line(box, color_var.get(), ls_var.get(), width)

        for var in (color_var, ls_var, lw_var):
            if var is None:
                continue
            try:
                var.trace_add("write", redraw)
            except Exception:
                pass
        redraw()
        box.bind(
            "<Button-1>",
            lambda e: _edit_line(box, ls_var, lw_var, color_var, with_width and lw_var is not None),
        )
        box.pack(side=tk.LEFT, padx=3)
        return box

    def _ptype_button(parent, pt_var):
        box = tk.Canvas(
            parent, width=36, height=24, bg=_BG2, highlightthickness=1, highlightbackground=_BORDER, cursor="hand2"
        )

        def redraw(*_a):
            _draw_ptype(box, pt_var.get())

        try:
            pt_var.trace_add("write", redraw)
        except Exception:
            pass
        redraw()
        box.bind("<Button-1>", lambda e: _edit_ptype(box, pt_var))
        box.pack(side=tk.LEFT, padx=3)
        return box

    def _shape_mark(parent, icon: str):
        box = tk.Canvas(
            parent, width=36, height=24, bg=_BG2, highlightthickness=1, highlightbackground=_BORDER
        )
        _draw_shape(box, icon)
        box.pack(side=tk.LEFT, padx=3)
        return box

    def _subcolor(frame, row: int, ind_key: str, label: str, show_key: str, color_key: str, indent: int = 28):
        """Checkbox plus swatch so one color inside a pair can be turned off."""
        show_var = tk.BooleanVar(value=bool(working[ind_key].get(show_key, True)))
        ttk.Checkbutton(frame, text=label, variable=show_var).grid(
            row=row, column=0, sticky="w", padx=(indent, 2), pady=3
        )
        _bind(show_key, "bool", show_var)
        box = _right(frame, row)
        cvar = tk.StringVar(value=str(working[ind_key].get(color_key, "#888888")))
        _chip(box, cvar)
        _bind(color_key, "color", cvar)
        return box

    def _right(frame, row: int):
        box = tk.Frame(frame, bg=_BG)
        box.grid(row=row, column=1, sticky="e", padx=(8, 2), pady=2)
        frame.columnconfigure(0, weight=1)
        return box

    def _line_vars(ind_key: str, item: Dict[str, Any]):
        ls_key = item["linestyle_key"]
        lw_key = item["linewidth_key"]
        pt_key = item["plottype_key"]
        pt_choices = [c for c in iset.PLOTTYPE_CHOICES if c != "shape"]
        ls_var = tk.StringVar(
            value=str(iset.coerce_choice(working[ind_key].get(ls_key, "solid"), iset.LINESTYLE_CHOICES))
        )
        pt_var = tk.StringVar(
            value=str(iset.coerce_choice(working[ind_key].get(pt_key, "line"), pt_choices))
        )
        try:
            lw_default = int(working[ind_key].get(lw_key, 2))
        except (TypeError, ValueError):
            lw_default = 2
        lw_var = tk.StringVar(value=str(lw_default))
        _bind(ls_key, "choice", ls_var)
        _bind(pt_key, "choice", pt_var)
        _bind(lw_key, "int", lw_var, {"min": 1, "max": 40})
        return ls_var, pt_var, lw_var

    def _add_inputs(frame, ind_key: str):
        row = 0
        seen_sections = set()
        frame.columnconfigure(0, weight=1)
        for field in iset.schema_fields(ind_key, "inputs"):
            section = field.get("section")
            if section and section not in seen_sections:
                seen_sections.add(section)
                ttk.Label(frame, text=section, style="Section.TLabel").grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(8, 4), padx=2
                )
                row += 1
            fkey = field["key"]
            val = working[ind_key].get(fkey, field.get("default"))
            ftype = field["type"]
            info = field.get("info")
            if ftype == "bool":
                var = tk.BooleanVar(value=bool(val))
                line = tk.Frame(frame, bg=_BG)
                line.grid(row=row, column=0, columnspan=2, sticky="w", pady=4, padx=2)
                ttk.Checkbutton(line, text=field["label"], variable=var).pack(side=tk.LEFT)
                if info:
                    _info_badge(line, info).pack(side=tk.LEFT, padx=(6, 0))
                _bind(fkey, "bool", var)
            else:
                left = tk.Frame(frame, bg=_BG)
                left.grid(row=row, column=0, sticky="w", pady=6, padx=(2, 12))
                ttk.Label(left, text=field["label"]).pack(side=tk.LEFT)
                if info:
                    _info_badge(left, info).pack(side=tk.LEFT, padx=(6, 0))
                if ftype == "choice":
                    choices = list(field.get("choices") or [])
                    labels = field.get("labels") or {}
                    cur = str(iset.coerce_choice(val, choices))
                    if labels:
                        display = [labels.get(c, str(c)) for c in choices]
                        var = tk.StringVar(value=labels.get(cur, cur))
                        ttk.Combobox(frame, textvariable=var, values=display, state="readonly", width=18).grid(
                            row=row, column=1, sticky="e"
                        )
                        widgets[fkey] = ("labeled_choice", var, {labels.get(c, str(c)): c for c in choices})
                        try:
                            var.trace_add("write", _schedule_live)
                        except Exception:
                            pass
                    else:
                        var = tk.StringVar(value=cur)
                        ttk.Combobox(frame, textvariable=var, values=choices, state="readonly", width=18).grid(
                            row=row, column=1, sticky="e"
                        )
                        _bind(fkey, "choice", var)
                elif ftype == "int":
                    var = tk.StringVar(value=str(int(val) if val is not None else 0))
                    ttk.Entry(frame, textvariable=var, width=14, justify="right").grid(row=row, column=1, sticky="e")
                    _bind(fkey, "int", var, field)
                else:
                    shown = val if val is not None else 0.0
                    try:
                        shown = float(shown)
                        text = str(int(shown)) if shown == int(shown) else str(shown)
                    except (TypeError, ValueError):
                        text = str(shown)
                    var = tk.StringVar(value=text)
                    ttk.Entry(frame, textvariable=var, width=14, justify="right").grid(row=row, column=1, sticky="e")
                    _bind(fkey, "float", var, field)
            row += 1

    def _add_visibility(frame, ind_key: str):
        # Chartix Visibility: checkbox, from, dual slider, to.
        for row, field in enumerate(iset.schema_fields(ind_key, "visibility")):
            if field.get("kind") != "range":
                fkey = field["key"]
                var = tk.BooleanVar(value=bool(working[ind_key].get(fkey, field.get("default", True))))
                ttk.Checkbutton(frame, text=field["label"], variable=var).grid(
                    row=row, column=0, sticky="w", pady=8, padx=4
                )
                _bind(fkey, "bool", var)
                continue
            lo, hi = int(field["min"]), int(field["max"])
            on = tk.BooleanVar(value=bool(working[ind_key].get(field["key"], True)))
            try:
                start = int(working[ind_key].get(field["from_key"], field["default_from"]))
            except (TypeError, ValueError):
                start = lo
            try:
                end = int(working[ind_key].get(field["to_key"], field["default_to"]))
            except (TypeError, ValueError):
                end = hi
            fv = tk.StringVar(value=str(max(lo, min(hi, start))))
            tv = tk.StringVar(value=str(max(lo, min(hi, end))))
            ttk.Checkbutton(frame, text=field["label"], variable=on).grid(
                row=row, column=0, sticky="w", pady=8, padx=(2, 8)
            )
            ttk.Entry(frame, textvariable=fv, width=5, justify="center").grid(row=row, column=1, padx=2)
            slider = tk.Canvas(frame, width=150, height=22, bg=_BG, highlightthickness=0)
            slider.grid(row=row, column=2, padx=4)
            ttk.Entry(frame, textvariable=tv, width=5, justify="center").grid(row=row, column=3, padx=2)
            _bind(field["key"], "bool", on)
            _bind(field["from_key"], "int", fv, {"min": lo, "max": hi})
            _bind(field["to_key"], "int", tv, {"min": lo, "max": hi})

            drag = {"which": None}

            def _vals(a=fv, b=tv, lo_=lo, hi_=hi):
                try:
                    left = int(float(a.get()))
                except (TypeError, ValueError):
                    left = lo_
                try:
                    right = int(float(b.get()))
                except (TypeError, ValueError):
                    right = hi_
                left = max(lo_, min(hi_, left))
                right = max(lo_, min(hi_, right))
                if left > right:
                    left, right = right, left
                return left, right

            def _x(val, lo_=lo, hi_=hi):
                span = max(1, hi_ - lo_)
                return 8 + (val - lo_) / span * 134

            def _val_at(x, lo_=lo, hi_=hi):
                span = max(1, hi_ - lo_)
                t = (x - 8) / 134
                return int(round(lo_ + max(0.0, min(1.0, t)) * span))

            def _paint(event=None, canvas=slider, vals=_vals, xpos=_x):
                canvas.delete("all")
                left, right = vals()
                canvas.create_line(8, 11, 142, 11, fill="#434651", width=4, capstyle="round")
                canvas.create_line(xpos(left), 11, xpos(right), 11, fill="#d1d4dc", width=4, capstyle="round")
                for x in (xpos(left), xpos(right)):
                    canvas.create_oval(x - 6, 5, x + 6, 17, fill="#ffffff", outline="#363a45")

            def _press(event, state=drag, vals=_vals, xpos=_x):
                left, right = vals()
                state["which"] = "from" if abs(event.x - xpos(left)) <= abs(event.x - xpos(right)) else "to"

            def _motion(event, a=fv, b=tv, state=drag, vals=_vals, vat=_val_at):
                if state["which"] is None:
                    return
                left, right = vals()
                val = vat(event.x)
                if state["which"] == "from":
                    a.set(str(min(val, right)))
                else:
                    b.set(str(max(val, left)))

            def _release(_event=None, state=drag):
                state["which"] = None

            slider.bind("<Button-1>", _press)
            slider.bind("<B1-Motion>", _motion)
            slider.bind("<ButtonRelease-1>", _release)
            fv.trace_add("write", _paint)
            tv.trace_add("write", _paint)
            _paint()

    def _add_style(frame, ind_key: str):
        row = 0
        saw_out = False
        style_items = iset.expand_style_widgets(ind_key)
        skip = set()
        for idx, item in enumerate(style_items):
            if idx in skip:
                continue
            nxt = style_items[idx + 1] if idx + 1 < len(style_items) else {}
            kind = item.get("kind")

            if kind == "field" and item.get("key") in (
                "precision",
                "labels_on_price_scale",
                "values_in_status_line",
            ):
                if not saw_out:
                    ttk.Label(frame, text="OUTPUTS", style="Section.TLabel").grid(
                        row=row, column=0, columnspan=4, sticky="w", pady=(14, 6), padx=2
                    )
                    row += 1
                    saw_out = True
                fkey = item["key"]
                ttk.Label(frame, text=item["label"]).grid(row=row, column=0, sticky="w", pady=5, padx=2)
                if item["type"] == "bool":
                    var = tk.BooleanVar(value=bool(working[ind_key].get(fkey, item.get("default", True))))
                    ttk.Checkbutton(frame, variable=var).grid(row=row, column=1, sticky="e")
                    _bind(fkey, "bool", var)
                else:
                    choices = list(item.get("choices") or ["default"])
                    # Chartix shows "Default" capitalized in UI
                    display = {c: ("Default" if c == "default" else c) for c in choices}
                    cur = str(working[ind_key].get(fkey, item.get("default", "default")))
                    var = tk.StringVar(value=display.get(cur, cur))
                    ttk.Combobox(
                        frame,
                        textvariable=var,
                        values=[display[c] for c in choices],
                        state="readonly",
                        width=12,
                    ).grid(row=row, column=1, sticky="e")
                    # store raw via wrapper
                    widgets[fkey] = ("precision_choice", var, choices)
                    try:
                        var.trace_add("write", _schedule_live)
                    except Exception:
                        pass
                row += 1
                continue

            if kind == "candles":
                show_key = item["show_key"]
                show_var = tk.BooleanVar(value=bool(working[ind_key].get(show_key, True)))
                ttk.Checkbutton(frame, text="Candles", variable=show_var).grid(
                    row=row, column=0, sticky="w", padx=2, pady=(8, 2)
                )
                _bind(show_key, "bool", show_var)
                row += 1
                ttk.Label(frame, text=item.get("body_label", "Body"), style="Muted.TLabel").grid(
                    row=row, column=0, sticky="w", padx=(20, 2)
                )
                row += 1
                for label, show_key, key in (
                    ("Color 1", item.get("show_color1_key"), item["color1_key"]),
                    ("Color 2", item.get("show_color2_key"), item["color2_key"]),
                ):
                    if show_key:
                        _subcolor(frame, row, ind_key, label, show_key, key, indent=36)
                    row += 1
                for label, key in (("Wick", item["wick_key"]), ("Border", item["border_key"])):
                    ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(20, 2), pady=3)
                    var = tk.StringVar(value=str(working[ind_key].get(key, "#888")))
                    _swatch(frame, var, row, 1)
                    _bind(key, "color", var)
                    row += 1
                continue

            if kind == "plot":
                show_key = item["show_key"]
                color_key = item["color_key"]
                show_var = tk.BooleanVar(value=bool(working[ind_key].get(show_key, True)))
                ttk.Checkbutton(frame, text=item["label"], variable=show_var).grid(
                    row=row, column=0, sticky="w", padx=2, pady=3
                )
                _bind(show_key, "bool", show_var)
                if nxt.get("kind") == "palette":
                    skip.add(idx + 1)
                    ls_var, pt_var, lw_var = _line_vars(ind_key, item)
                    color_keys = [k for k in nxt["defaults"] if "color" in str(k) and not str(k).startswith("show_")]
                    show_keys = [nxt.get("show0_key"), nxt.get("show1_key")]
                    for i, ck in enumerate(color_keys[:2]):
                        row += 1
                        show_key = show_keys[i] if i < len(show_keys) else None
                        if show_key:
                            box = _subcolor(frame, row, ind_key, f"Color {i}", show_key, ck, indent=28)
                        else:
                            ttk.Label(frame, text=f"Color {i}").grid(row=row, column=0, sticky="w", padx=(28, 2))
                            box = _right(frame, row)
                            cvar = tk.StringVar(value=str(working[ind_key].get(ck, nxt["defaults"][ck])))
                            _chip(box, cvar)
                            _bind(ck, "color", cvar)
                        _line_button(box, widgets[ck][1], ls_var, lw_var, with_width=True)
                        if i == 0:
                            _ptype_button(box, pt_var)
                    row += 1
                    continue
                if item.get("nested"):
                    row += 1
                    ttk.Label(frame, text=item.get("color_label") or "Color 0").grid(
                        row=row, column=0, sticky="w", padx=(28, 2)
                    )
                    box = _right(frame, row)
                    cvar = tk.StringVar(value=str(working[ind_key].get(color_key, "#888888")))
                    _chip(box, cvar)
                    _bind(color_key, "color", cvar)
                    row += 1
                    continue
                box = _right(frame, row)
                cvar = tk.StringVar(value=str(working[ind_key].get(color_key, "#2196f3")))
                _chip(box, cvar)
                _bind(color_key, "color", cvar)
                if item.get("location_key"):
                    _shape_mark(box, item.get("shape_icon") or "label_up")
                    choices = list(item.get("location_choices") or iset.PRICE_LOCATIONS)
                    cur = str(working[ind_key].get(item["location_key"], choices[0]))
                    if cur not in choices:
                        cur = choices[0]
                    loc_var = tk.StringVar(value=cur)
                    ttk.Combobox(box, textvariable=loc_var, values=choices, state="readonly", width=12).pack(
                        side=tk.LEFT, padx=3
                    )
                    _bind(item["location_key"], "choice", loc_var)
                elif not item.get("simple"):
                    ls_var, pt_var, lw_var = _line_vars(ind_key, item)
                    _line_button(box, cvar, ls_var, lw_var, with_width=True)
                    _ptype_button(box, pt_var)
                row += 1
                continue

            if kind == "band":
                show_key = item["show_key"]
                show_var = tk.BooleanVar(value=bool(working[ind_key].get(show_key, True)))
                ttk.Checkbutton(frame, text=item["label"], variable=show_var).grid(
                    row=row, column=0, sticky="w", padx=2, pady=4
                )
                _bind(show_key, "bool", show_var)
                box = _right(frame, row)
                cvar = tk.StringVar(value=str(working[ind_key].get(item["color_key"], "#888888")))
                _chip(box, cvar)
                _bind(item["color_key"], "color", cvar)
                ls_key = item.get("linestyle_key")
                if ls_key:
                    ls_var = tk.StringVar(
                        value=str(
                            iset.coerce_choice(
                                working[ind_key].get(ls_key, "dashed"), iset.LINESTYLE_CHOICES
                            )
                        )
                    )
                    _line_button(box, cvar, ls_var, None, with_width=False)
                    _bind(ls_key, "choice", ls_var)
                vvar = tk.StringVar(value=str(working[ind_key].get(item["value_key"], 0)))
                ttk.Entry(box, textvariable=vvar, width=8, justify="right").pack(side=tk.LEFT, padx=3)
                _bind(item["value_key"], "float", vvar, {"default": 0})
                row += 1
                continue

            if kind == "color_check":
                show_key = item["show_key"]
                show_var = tk.BooleanVar(value=bool(working[ind_key].get(show_key, True)))
                ttk.Checkbutton(frame, text=item["label"], variable=show_var).grid(
                    row=row, column=0, sticky="w", padx=2, pady=4
                )
                _bind(show_key, "bool", show_var)
                box = _right(frame, row)
                ckey = item["color_key"]
                cvar = tk.StringVar(value=str(working[ind_key].get(ckey, item["defaults"].get(ckey, "#787b86"))))
                _chip(box, cvar)
                _bind(ckey, "color", cvar)
                row += 1
                continue

            if kind == "bg":
                show_key = item["show_key"]
                show_var = tk.BooleanVar(value=bool(working[ind_key].get(show_key, True)))
                ttk.Checkbutton(frame, text=item["label"], variable=show_var).grid(
                    row=row, column=0, sticky="w", padx=2, pady=4
                )
                _bind(show_key, "bool", show_var)
                row += 1
                for label, show_key, key in (
                    ("Gold", item.get("show0_key"), item["color0_key"]),
                    ("Purple", item.get("show1_key"), item["color1_key"]),
                ):
                    if show_key:
                        _subcolor(frame, row, ind_key, label, show_key, key)
                    else:
                        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(28, 2))
                        var = tk.StringVar(value=str(working[ind_key].get(key, "#888")))
                        _swatch(frame, var, row, 1)
                        _bind(key, "color", var)
                    row += 1
                continue

            if kind == "bar_color":
                show_key = item["show_key"]
                show_var = tk.BooleanVar(value=bool(working[ind_key].get(show_key, True)))
                ttk.Checkbutton(frame, text=item["label"], variable=show_var).grid(
                    row=row, column=0, sticky="w", padx=2, pady=4
                )
                _bind(show_key, "bool", show_var)
                row += 1
                for label, show_key, key in (
                    ("Color 0", item.get("show0_key"), item["color0_key"]),
                    ("Color 1", item.get("show1_key"), item["color1_key"]),
                ):
                    if show_key:
                        _subcolor(frame, row, ind_key, label, show_key, key)
                    else:
                        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=(28, 2))
                        var = tk.StringVar(value=str(working[ind_key].get(key, "#008000")))
                        _swatch(frame, var, row, 1)
                        _bind(key, "color", var)
                    row += 1
                continue

            if kind == "field":
                fkey = item["key"]
                if item["type"] == "bool":
                    var = tk.BooleanVar(value=bool(working[ind_key].get(fkey, item.get("default", True))))
                    ttk.Checkbutton(frame, text=item["label"], variable=var).grid(
                        row=row, column=0, sticky="w", padx=2, pady=4
                    )
                    _bind(fkey, "bool", var)
                    row += 1

    def _flush():
        ind_key = active_key["k"]
        for fkey, meta in list(widgets.items()):
            try:
                kind = meta[0]
                if kind == "bool":
                    working[ind_key][fkey] = bool(meta[1].get())
                elif kind == "color":
                    working[ind_key][fkey] = str(meta[1].get()).strip() or working[ind_key].get(fkey)
                elif kind == "choice":
                    working[ind_key][fkey] = str(meta[1].get())
                elif kind == "labeled_choice":
                    raw = str(meta[1].get())
                    working[ind_key][fkey] = meta[2].get(raw, raw)
                elif kind == "precision_choice":
                    raw = str(meta[1].get())
                    working[ind_key][fkey] = "default" if raw.lower() == "default" else raw
                elif kind == "int":
                    v = int(float(meta[1].get()))
                    field = meta[2] if len(meta) > 2 else {}
                    if field.get("min") is not None:
                        v = max(int(field["min"]), v)
                    if field.get("max") is not None:
                        v = min(int(field["max"]), v)
                    working[ind_key][fkey] = v
                elif kind == "float":
                    v = float(meta[1].get())
                    field = meta[2] if len(meta) > 2 else {}
                    if field.get("min") is not None:
                        v = max(float(field["min"]), v)
                    if field.get("max") is not None:
                        v = min(float(field["max"]), v)
                    working[ind_key][fkey] = v
            except Exception:
                continue
        working[ind_key] = iset._apply_legacy_aliases(ind_key, working[ind_key])

    def _wire_links(ind_key: str) -> None:
        """Keep parent inputs and style rows in step so each checkbox changes the chart."""
        if ind_key != "eagles":
            return
        busy = {"on": False}

        def getb(key: str) -> bool:
            meta = widgets.get(key)
            return bool(meta[1].get()) if meta else False

        def setb(key: str, value: bool) -> None:
            meta = widgets.get(key)
            if not meta or meta[0] != "bool":
                return
            if bool(meta[1].get()) == bool(value):
                return
            meta[1].set(bool(value))

        # The 2nd stochastic is hidden until its input is on. Uncheck the style
        # rows so a ticked box is not sitting on an empty plot.
        if not (getb("show_2nd_stoch") or getb("use_2nd_on_current")):
            setb("show_stochK2", False)
            setb("show_stochD2", False)

        def guard(fn):
            def _on(*_args):
                if suspend_live["on"] or busy["on"]:
                    return
                busy["on"] = True
                try:
                    fn()
                finally:
                    busy["on"] = False

            return _on

        def styles_off() -> bool:
            return not getb("show_stochK2") and not getb("show_stochD2")

        def on_master() -> None:
            if getb("show_2nd_stoch"):
                if styles_off():
                    setb("show_stochK2", True)
                    setb("show_stochD2", True)
            else:
                setb("show_stochK2", False)
                setb("show_stochD2", False)
                setb("use_2nd_on_current", False)

        def on_style_show() -> None:
            if getb("show_stochK2") or getb("show_stochD2"):
                setb("show_2nd_stoch", True)
            else:
                setb("show_2nd_stoch", False)
                setb("use_2nd_on_current", False)

        def on_use_current() -> None:
            if not getb("use_2nd_on_current"):
                return
            setb("show_2nd_stoch", True)
            if styles_off():
                setb("show_stochK2", True)
                setb("show_stochD2", True)

        def on_alt() -> None:
            # The alternate timeframe only applies once chart resolution is off.
            setb("use_chart_resolution", False)

        def on_2nd_param() -> None:
            setb("show_2nd_stoch", True)
            setb("show_stochK2", True)
            setb("show_stochD2", True)

        def on_k2_look() -> None:
            setb("show_stochK2", True)
            setb("show_2nd_stoch", True)

        def on_d2_look() -> None:
            setb("show_stochD2", True)
            setb("show_2nd_stoch", True)

        def watch(key: str, fn) -> None:
            meta = widgets.get(key)
            if not meta:
                return
            try:
                meta[1].trace_add("write", guard(fn))
            except Exception:
                pass

        watch("show_2nd_stoch", on_master)
        watch("show_stochK2", on_style_show)
        watch("show_stochD2", on_style_show)
        watch("use_2nd_on_current", on_use_current)
        watch("alt_tf", on_alt)
        for key in ("second_tf", "stoch_len2", "smooth_k2", "smooth_d2"):
            watch(key, on_2nd_param)
        for key in ("stochK2_color", "stochK2_linestyle", "stochK2_linewidth", "stochK2_plottype"):
            watch(key, on_k2_look)
        for key in ("stochD2_color", "stochD2_linestyle", "stochD2_linewidth", "stochD2_plottype"):
            watch(key, on_d2_look)

    def _show(ind_key: str, flush: bool = True):
        suspend_live["on"] = True
        try:
            if flush:
                try:
                    _flush()
                except Exception:
                    pass
            active_key["k"] = ind_key
            title_var.set(iset.SCHEMAS[ind_key]["title"])
            root.title(iset.SCHEMAS[ind_key]["title"])
            _clear(inp_inner)
            _clear(sty_inner)
            _clear(vis_inner)
            widgets.clear()
            _add_inputs(inp_inner, ind_key)
            _add_style(sty_inner, ind_key)
            _add_visibility(vis_inner, ind_key)
            _wire_links(ind_key)
            tabs.select(0)
        finally:
            suspend_live["on"] = False

    def _cancel_live():
        if live_job["id"] is not None:
            try:
                root.after_cancel(live_job["id"])
            except Exception:
                pass
            live_job["id"] = None

    def do_ok():
        _cancel_live()
        suspend_live["on"] = True
        try:
            _flush()
        except Exception as ex:
            suspend_live["on"] = False
            messagebox.showerror("Invalid input", str(ex), parent=root)
            return
        updated = {k: iset._apply_legacy_aliases(k, copy.deepcopy(v)) for k, v in working.items()}
        iset.save_settings(updated)
        result_holder["value"] = updated
        focus = active_key["k"]
        if on_apply:
            try:
                on_apply(updated, focus)
            except TypeError:
                on_apply(updated)
            except Exception as ex:
                messagebox.showerror("Apply failed", str(ex), parent=root)
                return
        root.destroy()

    def do_cancel():
        _cancel_live()
        suspend_live["on"] = True
        if result_holder["dirty"] and on_apply:
            try:
                on_apply(original, active_key["k"])
            except Exception as ex:
                print(f"settings cancel restore failed: {ex}", flush=True)
        root.destroy()

    def do_defaults():
        if not messagebox.askyesno("Defaults", "Reset this indicator to defaults?", parent=root):
            return
        k = active_key["k"]
        working[k] = iset._apply_legacy_aliases(k, iset.default_all()[k])
        _show(k, flush=False)
        _push_live()

    defaults_mb = ttk.Menubutton(btn_row, text="Defaults")
    defaults_menu = tk.Menu(defaults_mb, tearoff=0, bg=_BG2, fg=_FG, activebackground=_ACCENT, activeforeground="#ffffff")
    defaults_menu.add_command(label="Reset settings", command=do_defaults)
    defaults_mb["menu"] = defaults_menu
    defaults_mb.pack(side=tk.LEFT)
    ttk.Button(btn_row, text="Ok", style="Ok.TButton", command=do_ok).pack(side=tk.RIGHT, padx=(6, 0))
    ttk.Button(btn_row, text="Cancel", command=do_cancel).pack(side=tk.RIGHT)

    _show(active)
    root.protocol("WM_DELETE_WINDOW", do_cancel)
    root.mainloop()
    return result_holder["value"]
