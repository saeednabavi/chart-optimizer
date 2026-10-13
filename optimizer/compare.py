# -*- coding: utf-8 -*-
"""Rank the optimized results of several indicators (same symbol / level), grouped by timeframe and side.

The rank uses the score on the unseen test part (the aggregate over all top/bottom definitions when the
automatic top/bottom mode was on), because the train score is what the search maximised and is optimistic.
An indicator is "reliable" when it has test pivots, beats random signals on the test part and its test
score is not far below its train score; the recommendation of each (timeframe, side) group is the best
reliable one of that group.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from optimizer.search import LEVEL_FA, OUTPUT_DIR, SWING_MODE_FA, _fmt, _nan

OVERFIT_RATIO = 0.6

VERDICT_FA = {
    "reliable": "قابل اعتماد",
    "overfit": "احتمال overfit",
    "random": "بهتر از تصادفی نیست",
    "no_test": "بدون سقف/کف در آزمون",
    "error": "خطا",
}
ACT_FA = {"buy": "خرید", "sell": "فروش"}


def _row(res: Dict[str, Any]) -> Dict[str, Any]:
    m = res["metrics"]
    train, test = m["optimized"]["train"], m["optimized"]["test"]
    agg = m.get("aggregate")
    test_score = agg["optimized"]["test"] if agg else test["score"]
    train_score = agg["optimized"]["train"] if agg else train["score"]
    edge = test["score"] - test["random_baseline"]
    if test["pivots"] == 0:
        verdict = "no_test"
    elif edge <= 0:
        verdict = "random"
    elif test_score < OVERFIT_RATIO * train_score:
        verdict = "overfit"
    else:
        verdict = "reliable"
    cfg = res["config"]
    return {
        "ind": cfg["ind"], "tf": cfg["tf"], "side": cfg["side"], "label": res["indicator_label"],
        "verdict": verdict,
        "test_score": test_score, "train_score": train_score, "default_test": m["default"]["test"]["score"],
        "random": test["random_baseline"], "edge": edge, "signals": test["signals"],
        "caught": test["caught"], "pivots": test["pivots"], "hit_rate": test["hit_rate"],
        "lag": test["avg_lag_bars"], "dist": test["avg_dist_pct"], "res": res,
    }


def rank_results(results: List[Dict[str, Any]], errors: Dict[Tuple[str, str, str], str],
                 tfs: List[str], sides: List[str]) -> List[Dict[str, Any]]:
    """Rows grouped by (timeframe, side) in the order of ``tfs`` / ``sides``, best first inside each group.

    ``errors`` maps (tf, side, ind) -> indicator label. The best row of each group has ``recommended=True``
    and ``rank`` is the position inside its group.
    """
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for r in map(_row, results):
        groups.setdefault((r["tf"], r["side"]), []).append(r)
    for tf, side, _ in errors:
        groups.setdefault((tf, side), [])
    out: List[Dict[str, Any]] = []
    for tf in tfs:
        for side in sides:
            if (tf, side) not in groups:
                continue
            rows = groups[(tf, side)]
            rows.sort(key=lambda r: (r["verdict"] != "no_test", r["test_score"], r["edge"], r["train_score"]),
                      reverse=True)
            best = next((r for r in rows if r["verdict"] == "reliable"), rows[0] if rows else None)
            for r in rows:
                r["recommended"] = r is best
            for (etf, eside, ind), label in errors.items():
                if (etf, eside) == (tf, side):
                    rows.append({"ind": ind, "tf": tf, "side": side, "label": label, "verdict": "error",
                                 "recommended": False, "res": None})
            for n, r in enumerate(rows, 1):
                r["rank"] = n
            out.extend(rows)
    return out


def best_lines(rows: List[Dict[str, Any]]) -> List[str]:
    """One line per (timeframe, side) group with its recommended indicator."""
    lines = []
    for r in rows:
        if not r["recommended"]:
            continue
        warn = "" if r["verdict"] == "reliable" else f"  [هشدار: {VERDICT_FA[r['verdict']]}]"
        lines.append(f"پیشنهاد {ACT_FA[r['side']]} در {r['tf']}: {r['label']}  (امتیاز آزمون {r['test_score']:.3f}، "
                     f"تصادفی {r['random']:.3f}، شکار {r['caught']}/{r['pivots']}){warn}")
    return lines


def compare_lines(rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> List[str]:
    """``meta``: ticker, adj, level, depth, tfs, sides, swing_mode."""
    acts = " و ".join(ACT_FA[s] for s in meta["sides"])
    lines = [
        f"مقایسه‌ی اندیکاتورها برای {acts} | نماد: {meta['ticker']}   تایم‌فریم: {', '.join(meta['tfs'])}   "
        f"({meta['adj']})",
        f"سطح: {LEVEL_FA[meta['level']]}   دقت: {meta['depth']}   "
        f"تعریف سقف/کف: {SWING_MODE_FA.get(meta.get('swing_mode', 'manual'), '')}",
        "مبنای قیمت: سقف روی High و کف روی Low کندل؛ کیفیت سیگنال با Low (خرید) / High (فروش) کندل سیگنال؛ "
        "«فاصله %» = فاصله‌ی Close کندل سیگنال تا کف/سقف.",
        "",
    ]
    best = best_lines(rows)
    lines.extend(best or ["هیچ اندیکاتوری نتیجه نداد."])
    for r in rows:
        if r["recommended"]:
            opt = r["res"]["optimized_params"]
            lines.append(f"   ورودی‌های بهینه‌ی {ACT_FA[r['side']]} {r['tf']} ({r['label']}): "
                         + ", ".join(f"{k}={_fmt(v)}" for k, v in opt.items()))
    lines.append("")
    lines.append("رتبه‌بندی هر گروه (بر اساس امتیاز روی داده‌ی آزمون که در بهینه‌سازی دیده نشده):")
    group = None
    for r in rows:
        if (r["tf"], r["side"]) != group:
            group = (r["tf"], r["side"])
            lines.append(f"-- {ACT_FA[r['side']]} | {r['tf']} --")
        if r["verdict"] == "error":
            lines.append(f"   {r['rank']}. {r['label']}: خطا")
            continue
        lines.append(
            f"   {r['rank']}. {r['label']}: آزمون {r['test_score']:.3f} (پیش‌فرض {r['default_test']:.3f}، "
            f"تصادفی {r['random']:.3f}) | آموزش {r['train_score']:.3f} | سیگنال {r['signals']} | "
            f"شکار {r['caught']}/{r['pivots']} | سیگنال خوب {r['hit_rate'] * 100:.0f}% | "
            f"تأخیر {_nan(r['lag'], '{:+.1f}')} | فاصله Close {_nan(r['dist'], '{:.1f}')}% | "
            f"{VERDICT_FA[r['verdict']]}")
    return lines


def save_compare(rows: List[Dict[str, Any]], meta: Dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    tf = meta["tfs"][0] if len(meta["tfs"]) == 1 else "allTF"
    side = meta["sides"][0] if len(meta["sides"]) == 1 else "both"
    path = OUTPUT_DIR / f"{meta['ticker']}_{tf}_compare_{side}_{meta['level']}_{stamp}.txt"
    path.write_text("\n".join(compare_lines(rows, meta)), encoding="utf-8-sig")
    return path
