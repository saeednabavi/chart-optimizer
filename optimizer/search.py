# -*- coding: utf-8 -*-
"""Search every calculation input of one indicator for signals closest to the real tops / bottoms.

Steps
-----
1. Effect check: every input is varied on several random base settings; an input that never changes
   the signal bars is frozen at its default and reported as "no effect on this signal".
2. Search on the train part only: full grid when the space is small enough, otherwise Optuna TPE
   (seeded with the defaults and a coarse grid).
3. Local refinement: coordinate descent over the full range of every input until nothing improves.
4. Robust pick: among the best results (not worse than the defaults) the one whose one-step neighbours
   also score well is chosen, so the answer is not a lonely spike.
5. Sensitivity of every input around the final answer + train / test metrics vs the defaults.

CLI (for testing):
    python -m optimizer.search BRS001195 1d eagles sell major --depth fast
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import random
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from chart.data_loader import PROJECT_ROOT, load_ohlcv
from chart.swings import SwingConfig, find_swings
from optimizer.param_space import IndicatorSpace, Param, build_space, style_labels
from chart.indicators.common import gregorian_to_jalali
from optimizer.scoring import HIT_Q, Scorer, Segment
from optimizer.signals import Context, compute_signal

OUTPUT_DIR = PROJECT_ROOT / "output" / "optimizer"

DEPTHS = {
    # grid_limit: largest space searched exhaustively; trials: Optuna trials otherwise;
    # starts: local searches started from the best results (top) and from random points (random)
    "fast": {"grid_limit": 3_000, "trials": 1_500, "bases": 5, "top_starts": 4, "random_starts": 4},
    "normal": {"grid_limit": 30_000, "trials": 6_000, "bases": 8, "top_starts": 10, "random_starts": 12},
    "deep": {"grid_limit": 200_000, "trials": 25_000, "bases": 12, "top_starts": 25, "random_starts": 40},
}


@dataclass
class RunConfig:
    ticker: str
    tf: str
    adj: str
    ind: str
    side: str  # "buy" | "sell"
    level: str  # "major" | "minor"
    depth: str = "normal"
    train_frac: float = 0.7
    optimize_vtx_levels: bool = False
    max_bars: int = 0  # 0 = all bars
    swing: Dict[str, Any] = field(default_factory=lambda: SwingConfig().to_dict())
    workers: int = 0  # 0 = all cores but one
    # Extra top/bottom definitions; the score of a setting is aggregated over `swing` + these.
    swing_scenarios: List[Dict[str, Any]] = field(default_factory=list)
    scenario_agg: str = "mean"  # "mean" | "min"
    # "manual": `swing` exactly as entered; "auto": timeframe defaults + `swing_scenarios` around them
    swing_mode: str = "manual"


MAX_SCENARIOS = 27


def make_scenarios(swing: Dict[str, Any], level: str, pct_mults: Sequence[float],
                   bars_mults: Sequence[float], atr_mults: Sequence[float]) -> List[Dict[str, Any]]:
    """Copies of ``swing`` with the target level's pct / min_bars / atr_mult scaled (base excluded)."""
    base = SwingConfig.from_dict(swing).to_dict()
    lv = base[level]
    seen = {(float(lv["pct"]), int(lv["min_bars"]), float(lv["atr_mult"]))}
    out = []
    for pm, bm, am in itertools.product(pct_mults or [1.0], bars_mults or [1.0], atr_mults or [1.0]):
        new = {"pct": round(max(0.1, lv["pct"] * pm), 3), "min_bars": max(1, int(round(lv["min_bars"] * bm))),
               "atr_mult": round(max(0.0, lv["atr_mult"] * am), 3)}
        key = (new["pct"], new["min_bars"], new["atr_mult"])
        if key in seen:
            continue
        seen.add(key)
        out.append({**base, level: {**lv, **new}})
        if len(out) >= MAX_SCENARIOS:
            break
    return out


def parse_mults(text: str) -> List[float]:
    vals = [float(x) for x in text.replace("،", ",").replace(" ", ",").split(",") if x.strip()]
    if any(v < 0 for v in vals):
        raise ValueError("ضریب منفی مجاز نیست")
    return vals or [1.0]


# ---------------------------------------------------------------- shared evaluation state

class Problem:
    """Data, pivots and scorer of one run (built once per process)."""

    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        df = load_ohlcv(cfg.ticker, cfg.tf, cfg.adj)
        if cfg.max_bars and len(df) > cfg.max_bars:
            df = df.iloc[-cfg.max_bars:].reset_index(drop=True)
        self.df = df
        self.swings = find_swings(df, SwingConfig.from_dict(cfg.swing))
        self.scorer = Scorer(df, self.swings, cfg.level, cfg.side)
        self.scorers = [self.scorer] + [
            Scorer(df, find_swings(df, SwingConfig.from_dict(s)), cfg.level, cfg.side) for s in cfg.swing_scenarios]
        self.ctx = Context(cfg.ticker, cfg.tf, cfg.adj)
        self.space = build_space(cfg.ind, cfg.ticker, cfg.tf, cfg.adj, cfg.optimize_vtx_levels)
        split = int(len(df) * cfg.train_frac)
        self.train = Segment(0, split)
        self.test = Segment(split, len(df))
        # A definition without target pivots in a segment can't be scored there, so it is left out.
        self._active = {id(seg): [s for s in self.scorers if len(s.segment_pivots(seg))] or [self.scorer]
                        for seg in (self.train, self.test)}

    def signal(self, params: Dict[str, Any]) -> np.ndarray:
        return compute_signal(self.cfg.ind, self.df, params, self.cfg.side, self.ctx)

    def score(self, sig: np.ndarray, seg: Segment) -> float:
        """Score over all top/bottom definitions (mean or worst)."""
        scores = [s.score(sig, seg) for s in self._active[id(seg)]]
        return float(min(scores)) if self.cfg.scenario_agg == "min" else float(np.mean(scores))

    def evaluate(self, params: Dict[str, Any]) -> Tuple[float, float, str]:
        sig = self.signal(params)
        digest = hashlib.md5(np.packbits(sig).tobytes()).hexdigest()
        return self.score(sig, self.train), self.score(sig, self.test), digest


_PROBLEM: Optional[Problem] = None


def _init_worker(cfg_dict: Dict[str, Any]) -> None:
    global _PROBLEM
    import warnings
    warnings.filterwarnings("ignore")
    _PROBLEM = Problem(RunConfig(**cfg_dict))


def _eval_worker(params: Dict[str, Any]) -> Tuple[float, float, str]:
    try:
        return _PROBLEM.evaluate(params)
    except Exception:
        return 0.0, 0.0, "error"


# ---------------------------------------------------------------- optimizer

ProgressFn = Callable[[Dict[str, Any]], None]


def _key(params: Dict[str, Any]) -> Tuple:
    return tuple(sorted(params.items()))


class Optimizer:
    def __init__(self, cfg: RunConfig, progress: Optional[ProgressFn] = None,
                 stop: Optional[threading.Event] = None):
        self.cfg = cfg
        self.progress = progress or (lambda info: None)
        self.stop = stop or threading.Event()
        self.problem = Problem(cfg)
        self.space: IndicatorSpace = self.problem.space
        self.depth = DEPTHS.get(cfg.depth, DEPTHS["normal"])
        self.cache: Dict[Tuple, Tuple[float, float, str]] = {}
        self.best_params: Dict[str, Any] = {}
        self.best_score = -1.0
        self.evals = 0
        self.phase = ""
        self.t0 = time.time()

    # -- plumbing
    def _log(self, msg: str, **extra) -> None:
        info = {"phase": self.phase, "msg": msg, "evals": self.evals, "best": self.best_score,
                "best_params": dict(self.best_params), "elapsed": time.time() - self.t0}
        info.update(extra)
        self.progress(info)

    def _batch(self, pool: ProcessPoolExecutor, plist: List[Dict[str, Any]]) -> List[Tuple[float, float, str]]:
        todo, seen = [], set()
        for p in plist:
            k = _key(p)
            if k not in self.cache and k not in seen:
                seen.add(k)
                todo.append(p)
        if todo:
            chunk = max(1, len(todo) // (self._workers * 4))
            for p, res in zip(todo, pool.map(_eval_worker, todo, chunksize=chunk)):
                self.cache[_key(p)] = res
                self.evals += 1
                if res[0] > self.best_score:
                    self.best_score, self.best_params = res[0], dict(p)
        return [self.cache[_key(p)] for p in plist]

    def _full(self, partial: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(self.base)
        out.update(partial)
        return out

    # -- steps
    def _effect_check(self, pool) -> List[str]:
        self.phase = "effect"
        searchable = [p for p in self.space.params if p.key not in self.space.fixed]
        rng = random.Random(7)
        bases = [dict(self.base)]
        for _ in range(self.depth["bases"] - 1):
            bases.append({**self.base, **{p.key: rng.choice(p.values()) for p in searchable}})
        effective = []
        for n, p in enumerate(searchable):
            vals = list(dict.fromkeys(p.coarse(8) + [rng.choice(p.values()) for _ in range(3)]))
            plist = [{**b, p.key: v} for b in bases for v in vals]
            # signal hashes come from the full data so a rare effect is not missed
            res = self._batch(pool, plist + bases)
            hashes = {}
            for prm, r in zip(plist + bases, res):
                bkey = _key({k: v for k, v in prm.items() if k != p.key})
                hashes.setdefault(bkey, set()).add(r[2])
            if any(len(h) > 1 for h in hashes.values()):
                effective.append(p.key)
            self._log(f"effect check {n + 1}/{len(searchable)}: {p.key} -> "
                      f"{'effective' if p.key in effective else 'no effect'}",
                      done=n + 1, total=len(searchable))
            if self.stop.is_set():
                break
        return effective

    def _grid(self, pool, keys: List[str]) -> None:
        self.phase = "grid"
        params = [self.space.param(k) for k in keys]
        total = math.prod(len(p.values()) for p in params)
        done = 0
        it = itertools.product(*[p.values() for p in params])
        batch_size = max(200, self._workers * 50)
        while not self.stop.is_set():
            chunk = list(itertools.islice(it, batch_size))
            if not chunk:
                break
            self._batch(pool, [self._full(dict(zip(keys, vals))) for vals in chunk])
            done += len(chunk)
            self._log(f"grid {done:,}/{total:,}", done=done, total=total)

    def _optuna(self, pool, keys: List[str]) -> None:
        import optuna
        from optuna.distributions import CategoricalDistribution, FloatDistribution, IntDistribution

        import warnings

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        warnings.filterwarnings("ignore", category=optuna.exceptions.ExperimentalWarning)
        self.phase = "optuna"
        dists = {}
        for k in keys:
            p = self.space.param(k)
            if p.kind == "int":
                dists[k] = IntDistribution(int(p.lo), int(p.hi), step=int(p.step))
            elif p.kind == "float":
                dists[k] = FloatDistribution(p.lo, p.hi, step=p.step)
            else:
                dists[k] = CategoricalDistribution(list(p.values()))
        coarse = [self.space.param(k).coarse(3) for k in keys]
        combos = list(itertools.product(*coarse))
        random.Random(3).shuffle(combos)
        first_seeds = [{k: self.base[k] for k in keys}] + [dict(zip(keys, c)) for c in combos[:300]]

        # TPE re-reads the whole history on every ask (quadratic cost), so the trials run as a chain of
        # studies of STUDY_TRIALS each; every new study starts from the best results found so far.
        STUDY_TRIALS = 1500
        total = self.depth["trials"] + len(first_seeds)
        done = 0
        batch = max(16, self._workers * 4)
        study_no = 0
        while done < total and not self.stop.is_set():
            sampler = optuna.samplers.TPESampler(seed=11 + study_no, n_startup_trials=max(100, len(keys) * 20),
                                                 multivariate=True, constant_liar=True)
            study = optuna.create_study(direction="maximize", sampler=sampler)
            seeds = first_seeds if study_no == 0 else self._top_distinct(keys, 40)
            for s in seeds:
                study.enqueue_trial({k: s[k] for k in keys}, skip_if_exists=True)
            in_study = 0
            limit = STUDY_TRIALS + len(seeds)
            while in_study < limit and done < total and not self.stop.is_set():
                trials = [study.ask(dists) for _ in range(min(batch, total - done, limit - in_study))]
                plist = [self._full({k: _clean(self.space.param(k), t.params[k]) for k in keys}) for t in trials]
                for t, r in zip(trials, self._batch(pool, plist)):
                    study.tell(t, r[0])
                done += len(trials)
                in_study += len(trials)
                self._log(f"optuna {done:,}/{total:,} (study {study_no + 1})", done=done, total=total)
            study_no += 1

    def _top_distinct(self, keys: List[str], n: int) -> List[Dict[str, Any]]:
        """Best cached settings with the no-effect inputs at their defaults, one per distinct value set."""
        frozen = {k: v for k, v in self.base.items() if k not in keys}
        out, seen = [], set()
        for k, _ in sorted(self.cache.items(), key=lambda kv: -kv[1][0]):
            p = dict(k)
            sig = tuple(p.get(x) for x in keys)
            if any(p.get(fk) != fv for fk, fv in frozen.items()) or sig in seen:
                continue
            seen.add(sig)
            out.append(p)
            if len(out) >= n:
                break
        return out

    def _descend(self, pool, start: Dict[str, Any], keys: List[str]) -> Tuple[float, Dict[str, Any]]:
        """Coordinate descent: sweep every input over its full range until no sweep improves."""
        cur = dict(start)
        cur_score = self._batch(pool, [cur])[0][0]
        for _ in range(30):
            improved = False
            for k in keys:
                if self.stop.is_set():
                    return cur_score, cur
                plist = [{**cur, k: v} for v in self.space.param(k).values()]
                res = self._batch(pool, plist)
                i = int(np.argmax([r[0] for r in res]))
                if res[i][0] > cur_score + 1e-12:
                    cur, cur_score, improved = plist[i], res[i][0], True
            if not improved:
                break
        return cur_score, cur

    def _refine(self, pool, keys: List[str]) -> None:
        """Local search from the best results found so far and from random points."""
        self.phase = "refine"
        starts = [dict(self.best_params)] + self._top_distinct(keys, self.depth["top_starts"])
        rng = random.Random(19)
        for _ in range(self.depth["random_starts"]):
            starts.append(self._full({k: rng.choice(self.space.param(k).values()) for k in keys}))
        for n, s in enumerate(starts):
            if self.stop.is_set():
                return
            score, _ = self._descend(pool, s, keys)
            self._log(f"local search {n + 1}/{len(starts)}: reached {score:.4f}", done=n + 1, total=len(starts))

    def _neighbour_mean(self, pool, params: Dict[str, Any], keys: List[str]) -> float:
        plist = [{**params, k: v} for k in keys for v in self.space.param(k).neighbours(params[k])]
        if not plist:
            return self.cache[_key(params)][0]
        return float(np.mean([r[0] for r in self._batch(pool, plist)]))

    def _robust_pick(self, pool, keys: List[str], default_score: float) -> Dict[str, Any]:
        self.phase = "robust"
        cands = [(self.cache[_key(p)][0], p) for p in self._top_distinct(keys, 15)]
        cands = [(s, p) for s, p in cands if s >= default_score - 1e-12]
        best, best_val = self.best_params, -1.0
        for n, (score, p) in enumerate(cands):
            val = 0.5 * score + 0.5 * self._neighbour_mean(pool, p, keys)
            if val > best_val:
                best, best_val = p, val
            self._log(f"robustness check {n + 1}/{len(cands)}", done=n + 1, total=len(cands))
        return best

    def _sensitivity(self, pool, final: Dict[str, Any], keys: List[str]) -> Dict[str, Dict[str, Any]]:
        self.phase = "sensitivity"
        out = {}
        base_score = self._batch(pool, [final])[0][0]
        for k in keys:
            p = self.space.param(k)
            vals = p.values()
            res = self._batch(pool, [{**final, k: v} for v in vals])
            scores = [r[0] for r in res]
            nb = {str(v): r[0] for v, r in zip(vals, res) if v in p.neighbours(final[k])}
            out[k] = {"min": float(min(scores)), "max": float(max(scores)), "at_final": base_score,
                      "impact": float(base_score - min(scores)), "neighbours": nb}
        return out

    # -- main
    def run(self) -> Dict[str, Any]:
        prob = self.problem
        self.base = self.space.defaults()
        self._workers = self.cfg.workers or max(1, (os.cpu_count() or 2) - 1)
        self._log(f"bars={len(prob.df)} train={prob.train.hi} test={prob.test.hi - prob.test.lo} "
                  f"target pivots={len(prob.scorer.pivot_bar)} workers={self._workers}")
        if len(prob.scorers) > 1:
            self._log(f"top/bottom definitions: {len(prob.scorers)} ({self.cfg.scenario_agg}) | target pivots: "
                      + ", ".join(str(len(s.pivot_bar)) for s in prob.scorers))
        with ProcessPoolExecutor(max_workers=self._workers, initializer=_init_worker,
                                 initargs=(asdict(self.cfg),)) as pool:
            default_res = self._batch(pool, [self.base])[0]
            effective = self._effect_check(pool)
            searchable = [p.key for p in self.space.params if p.key not in self.space.fixed]
            no_effect = [k for k in searchable if k not in effective]
            size = self.space.size(effective)
            self._log(f"effective inputs: {effective} | search space: {size:,}")
            # Restart the search from the defaults: effect-check bases also moved the no-effect inputs.
            self.best_params, self.best_score = dict(self.base), default_res[0]
            if effective:
                if size <= self.depth["grid_limit"]:
                    self._grid(pool, effective)
                else:
                    self._optuna(pool, effective)
                self._refine(pool, effective)
                final = self._robust_pick(pool, effective, default_res[0])
            else:
                final = dict(self.base)
            sens = self._sensitivity(pool, final, effective) if effective else {}
        return self._result(final, effective, no_effect, sens)

    def _result(self, final, effective, no_effect, sens) -> Dict[str, Any]:
        prob = self.problem
        sc = prob.scorer
        sig_def = prob.signal(self.base)
        sig_opt = prob.signal(final)
        metrics = {
            "default": {"train": sc.evaluate(sig_def, prob.train), "test": sc.evaluate(sig_def, prob.test)},
            "optimized": {"train": sc.evaluate(sig_opt, prob.train), "test": sc.evaluate(sig_opt, prob.test)},
        }
        inputs = []
        for p in self.space.params:
            if p.key in self.space.fixed:
                status = "fixed"
            elif p.key in effective:
                status = "effective"
            else:
                status = "no_effect"
            inputs.append({"key": p.key, "label": p.label, "default": self.base[p.key],
                           "optimized": final[p.key], "status": status, "rule_only": p.rule_only,
                           "sensitivity": sens.get(p.key)})
        scenarios = []
        if len(prob.scorers) > 1:
            for s, swing in zip(prob.scorers, [self.cfg.swing] + list(self.cfg.swing_scenarios)):
                scenarios.append({
                    "swing": dict(swing[self.cfg.level]),
                    "primary": s is sc,
                    "pivots_train": int(len(s.segment_pivots(prob.train))),
                    "pivots_test": int(len(s.segment_pivots(prob.test))),
                    "default": {"train": s.score(sig_def, prob.train), "test": s.score(sig_def, prob.test)},
                    "optimized": {"train": s.score(sig_opt, prob.train), "test": s.score(sig_opt, prob.test)},
                })
            metrics["aggregate"] = {
                which: {part: prob.score(sig, seg) for part, seg in (("train", prob.train), ("test", prob.test))}
                for which, sig in (("default", sig_def), ("optimized", sig_opt))
            }
        return {
            "scenarios": scenarios,
            "config": asdict(self.cfg),
            "indicator_label": self.space.label,
            "rule": self.space.note,
            "bars": len(prob.df),
            "first_time": str(prob.df["time"].iloc[0]),
            "split_time": str(prob.df["time"].iloc[prob.test.lo]) if prob.test.lo < len(prob.df) else "",
            "last_time": str(prob.df["time"].iloc[-1]),
            "target_pivots": int(len(sc.pivot_bar)),
            "inputs": inputs,
            "display_inputs": self.space.display_inputs,
            "style_labels": style_labels(self.cfg.ind),
            "default_params": self.base,
            "optimized_params": final,
            "metrics": metrics,
            **_trade_list(prob, sig_opt),
            "evaluations": self.evals,
            "seconds": round(time.time() - self.t0, 1),
            "stopped": self.stop.is_set(),
        }


def _trade_list(prob: Problem, sig: np.ndarray) -> Dict[str, List[Dict[str, Any]]]:
    """Every signal of the optimized setting (filled at the close of its candle) and the missed pivots."""
    sc, df = prob.scorer, prob.df
    buy = prob.cfg.side == "buy"
    times = df["time"]
    close = df["close"].to_numpy(dtype=float)
    touch = df["low" if buy else "high"].to_numpy(dtype=float)
    rows, missed = sc.details(sig)
    trades = []
    for r in rows:
        b, z, q = r["bar"], r["pivot"], r["quality"]
        t = {"bar": b, "time": str(times.iloc[b]), "price": float(close[b]), "touch": float(touch[b]),
             "part": "train" if b < prob.test.lo else "test", "quality": q, "catch": r["catch"],
             "pivot_time": "", "pivot_price": None, "lag_bars": None, "dist_pct": None}
        if q is None:
            t["result"] = "unconfirmed"
        elif z < 0 or q <= 0:
            t["result"] = "bad"
        else:
            t["result"] = "good" if q >= HIT_Q else "weak"
        if z >= 0:
            pb, px = int(sc.pivot_bar[z]), float(sc.pivot_price[z])
            t.update(pivot_time=str(times.iloc[pb]), pivot_price=px, lag_bars=b - pb,
                     dist_pct=(close[b] / px - 1) * 100 if buy else (px / close[b] - 1) * 100)
        trades.append(t)
    miss = [{"time": str(times.iloc[int(sc.pivot_bar[p])]), "price": float(sc.pivot_price[p]),
             "part": "train" if sc.pivot_bar[p] < prob.test.lo else "test"} for p in missed]
    return {"trades": trades, "missed_pivots": miss}


def _clean(p: Param, v: Any) -> Any:
    if p.kind == "int":
        return int(v)
    if p.kind == "float":
        return round(float(v), 6)
    return v


# ---------------------------------------------------------------- report

SIDE_FA = {"buy": "خرید (کف‌ها)", "sell": "فروش (سقف‌ها)"}
LEVEL_FA = {"major": "major (اساسی)", "minor": "minor (جزئی)"}
SWING_MODE_FA = {"manual": "دستی (همان مقدارهای واردشده)",
                 "auto": "خودکار (پیش‌فرض تایم‌فریم + چند تعریف اطراف آن)"}
PIVOT_PRICE_FA = {"buy": "Low", "sell": "High"}


def price_basis_lines(buy: bool) -> List[str]:
    pivot_fa, ext = ("کف", "Low") if buy else ("سقف", "High")
    return [
        "مبنای قیمت: سقف‌ها روی High و کف‌ها روی Low کندل (سایه) پیدا شده‌اند.",
        f"   کیفیت هر سیگنال با {ext} کندل سیگنال نسبت به {pivot_fa} ({ext}) سنجیده می‌شود.",
        f"   «قیمت» سیگنال و «فاصله %» = قیمت Close کندل سیگنال نسبت به {pivot_fa} ({ext}).",
    ]


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "On (تیک)" if v else "Off (بدون تیک)"
    if isinstance(v, float):
        return f"{v:.10g}"
    return str(v)


def fmt_price(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"{v:,.4f}".rstrip("0").rstrip(".")


def jalali_time(ts: str) -> str:
    t = pd.Timestamp(ts)
    y, mo, d = gregorian_to_jalali(t.year, t.month, t.day)
    return f"{y}/{mo:02d}/{d:02d} {t:%H:%M}"


RESULT_FA = {"good": "خوب", "weak": "ضعیف", "bad": "بد (دور از هدف)", "unconfirmed": "نامعلوم (هدف آخر هنوز تأیید نشده)"}
PART_FA = {"train": "آموزش", "test": "آزمون"}
# Tags of the summary lines (the GUI colours them): param = optimized inputs (red)
Line = Tuple[str, str]


def summary_lines(res: Dict[str, Any]) -> List[Line]:
    cfg = res["config"]
    m = res["metrics"]
    buy = cfg["side"] == "buy"
    pivot_fa = "کف" if buy else "سقف"
    lines: List[Line] = [
        (f"نماد: {cfg['ticker']}   تایم‌فریم: {cfg['tf']}   ({cfg['adj']})", ""),
        (f"اندیکاتور: {res['indicator_label']}   سمت: {SIDE_FA[cfg['side']]}   سطح: {LEVEL_FA[cfg['level']]}", ""),
        (f"قانون سیگنال: {res['rule']}", ""),
        (f"کندل‌ها: {res['bars']:,}  (آموزش تا {res['split_time']}، بقیه آزمون)   تعداد {pivot_fa} هدف: {res['target_pivots']}", ""),
    ]
    lv = (cfg.get("swing") or {}).get(cfg["level"]) or {}
    mode = cfg.get("swing_mode", "manual")
    lines.append((f"تعریف سقف/کف: {SWING_MODE_FA.get(mode, mode)}  |  {cfg['level']}: حداقل حرکت "
                  f"{_fmt(lv.get('pct'))}%   حداقل فاصله {lv.get('min_bars')} کندل   ضریب ATR {_fmt(lv.get('atr_mult'))}",
                  ""))
    lines.extend((t, "") for t in price_basis_lines(buy))
    lines += [
        ("", ""),
        ("پارامترهای بهینه‌شده (دقیقاً همین مقدارها را در تنظیمات اندیکاتور وارد کنید):", "head"),
    ]
    eff = [i for i in res["inputs"] if i["status"] == "effective"]
    for i in eff:
        mark = "   (همان پیش‌فرض)" if i["optimized"] == i["default"] else f"   (پیش‌فرض {_fmt(i['default'])})"
        sens = i.get("sensitivity") or {}
        if sens and sens["max"] - sens["min"] < 1e-12:
            mark += "   [با بقیه‌ی تنظیمات انتخاب‌شده بی‌اثر است]"
        lines.append((f"   {i['label']}  [{i['key']}]  =  {_fmt(i['optimized'])}{mark}", "param"))
    if not eff:
        lines.append(("   هیچ ورودی‌ای روی این سیگنال اثر ندارد.", "param"))
    fixed = [i for i in res["inputs"] if i["status"] == "fixed"]
    for i in fixed:
        lines.append((f"   {i['label']}  [{i['key']}]  =  {_fmt(i['optimized'])}   (ثابت طبق قانون کارفرما)", "param"))
    ne = [i for i in res["inputs"] if i["status"] == "no_effect"]
    for i in ne:
        lines.append((f"   {i['label']}  [{i['key']}]  =  {_fmt(i['optimized'])}   (روی این سیگنال بی‌اثر؛ پیش‌فرض ماند)",
                      "param"))
    def add(text: str = "", tag: str = "") -> None:
        lines.append((text, tag))

    disp = list(res["display_inputs"])
    if disp:
        add("ورودی‌های نمایشی در تب Inputs: " + "، ".join(disp))
    if res["style_labels"]:
        add("همه‌ی تنظیمات تب Style نمایشی هستند: " + "، ".join(res["style_labels"]))
    add()

    def row(name: str, d: Dict[str, Any]) -> str:
        return (f"   {name}: امتیاز {d['score']:.3f} (تصادفی {d['random_baseline']:.3f}) | سیگنال {d['signals']} | "
                f"شکار {d['caught']}/{d['pivots']} | سیگنال خوب {d['hit_rate'] * 100:.0f}% | "
                f"تأخیر {_nan(d['avg_lag_bars'], '{:+.1f}')} کندل | فاصله Close تا {pivot_fa} "
                f"{_nan(d['avg_dist_pct'], '{:.1f}')}%")

    add("نتیجه روی داده‌ی آموزش:", "head")
    add(row("پیش‌فرض", m["default"]["train"]))
    add(row("بهینه  ", m["optimized"]["train"]))
    add("نتیجه روی داده‌ی آزمون (دیده نشده):", "head")
    add(row("پیش‌فرض", m["default"]["test"]))
    add(row("بهینه  ", m["optimized"]["test"]))
    scen = res.get("scenarios") or []
    if scen:
        agg = m["aggregate"]
        how = "بدترین" if cfg.get("scenario_agg") == "min" else "میانگین"
        add()
        add(f"تعریف خودکار سقف/کف: {len(scen)} تعریف ({cfg['level']}) امتحان شد، امتیاز = {how} همه:", "head")
        add(f"   {how} امتیاز: آموزش {agg['default']['train']:.3f} -> {agg['optimized']['train']:.3f} | "
            f"آزمون {agg['default']['test']:.3f} -> {agg['optimized']['test']:.3f}   (پیش‌فرض -> بهینه)")
        for s in scen:
            sw = s["swing"]
            tag = "  [تعریف اصلی]" if s["primary"] else ""
            add(f"   حرکت {_fmt(sw['pct'])}% | فاصله {sw['min_bars']} کندل | ATR {_fmt(sw['atr_mult'])}: "
                f"هدف {s['pivots_train']}+{s['pivots_test']} | "
                f"آموزش {s['default']['train']:.3f} -> {s['optimized']['train']:.3f} | "
                f"آزمون {s['default']['test']:.3f} -> {s['optimized']['test']:.3f}{tag}")
        add("   (اعداد جدول بالا مربوط به تعریف اصلی است.)")
    tr, te = m["optimized"]["train"]["score"], m["optimized"]["test"]["score"]
    if m["optimized"]["test"]["pivots"] == 0:
        add("هشدار: در بخش آزمون هیچ سقف/کف هدفی نیست؛ درصد آموزش را کمتر کنید.", "warn")
    elif te < 0.6 * tr:
        add("هشدار: امتیاز آزمون خیلی کمتر از آموزش است (احتمال overfit).", "warn")
    elif te <= m["default"]["test"]["score"]:
        add("توجه: روی داده‌ی آزمون، تنظیمات بهینه از پیش‌فرض بهتر نشد.", "warn")
    if any(i["key"] == "use_chart_resolution" and i["status"] == "effective" for i in res["inputs"]):
        add("تایم‌فریم بالاتر (alt_tf) بدون نگاه به آینده حساب شده: کندل جاری آن تایم‌فریم مثل "
            "چارت زنده هنوز در حال شکل‌گیری است.")
    add(f"ارزیابی‌ها: {res['evaluations']:,}   زمان: {res['seconds']:.0f} ثانیه"
        + ("   (متوقف شده توسط کاربر)" if res["stopped"] else ""))
    lines.extend(trade_lines(res))
    return lines


def trade_lines(res: Dict[str, Any]) -> List[Line]:
    """One line per signal of the optimized setting: when, at what price, how close to the real top/bottom."""
    buy = res["config"]["side"] == "buy"
    act, pivot_fa = ("خرید", "کف") if buy else ("فروش", "سقف")
    ext = PIVOT_PRICE_FA["buy" if buy else "sell"]
    trades = res.get("trades") or []
    out: List[Line] = [("", ""), (f"فهرست {act}ها با تنظیمات بهینه ({len(trades)} سیگنال، "
                                   f"Close = قیمت پایانی کندل سیگنال، {pivot_fa} روی {ext}):", "head")]
    for n, t in enumerate(trades, 1):
        when = f"{jalali_time(t['time'])}  ({t['time'][:16]})"
        touch = f"  {ext} {fmt_price(t['touch'])}" if t.get("touch") is not None else ""
        text = (f"   {n}. {act} {when}  Close {fmt_price(t['price'])}{touch}  [{PART_FA[t['part']]}]  "
                f"نتیجه: {RESULT_FA[t['result']]}")
        if t["pivot_time"]:
            text += (f"  <- {pivot_fa} {jalali_time(t['pivot_time'])} {ext} {fmt_price(t['pivot_price'])}"
                     f"  فاصله Close {t['dist_pct']:+.2f}%  تأخیر {t['lag_bars']:+d} کندل")
            if t["catch"]:
                text += f"  (شکار این {pivot_fa})"
        out.append((text, t["result"]))
    missed = res.get("missed_pivots") or []
    if missed:
        out.append((f"{pivot_fa}های هدفی که هیچ {act} خوبی نزدیکشان نبود ({len(missed)}):", "head"))
        for p in missed:
            out.append((f"   {pivot_fa} {jalali_time(p['time'])}  ({p['time'][:16]})  {ext} {fmt_price(p['price'])}"
                        f"  [{PART_FA[p['part']]}]", "bad"))
    return out


def persian_summary(res: Dict[str, Any]) -> str:
    return "\n".join(text for text, _ in summary_lines(res))


def _nan(v: float, fmt: str) -> str:
    return "-" if v is None or (isinstance(v, float) and math.isnan(v)) else fmt.format(v)


def save_result(res: Dict[str, Any]) -> Path:
    cfg = res["config"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"{cfg['ticker']}_{cfg['tf']}_{cfg['ind']}_{cfg['side']}_{cfg['level']}_{stamp}.json"
    path.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    path.with_suffix(".txt").write_text(persian_summary(res), encoding="utf-8-sig")
    return path


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if math.isnan(o) else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)


def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("tf")
    ap.add_argument("ind")
    ap.add_argument("side", choices=["buy", "sell"])
    ap.add_argument("level", choices=["major", "minor"])
    ap.add_argument("--depth", default="fast", choices=list(DEPTHS))
    ap.add_argument("--adj", default="adjusted")
    ap.add_argument("--train", type=float, default=0.7)
    ap.add_argument("--vtx-levels", action="store_true")
    ap.add_argument("--max-bars", type=int, default=0)
    ap.add_argument("--pct-mults", default="1", help="e.g. 0.7,1,1.4 (robust over several top/bottom definitions)")
    ap.add_argument("--bars-mults", default="1")
    ap.add_argument("--atr-mults", default="1")
    ap.add_argument("--agg", default="mean", choices=["mean", "min"])
    args = ap.parse_args()
    from chart.swings import load_config
    swing = load_config(args.tf).to_dict()
    scen = make_scenarios(swing, args.level, parse_mults(args.pct_mults), parse_mults(args.bars_mults),
                          parse_mults(args.atr_mults))
    cfg = RunConfig(args.ticker, args.tf, args.adj, args.ind, args.side, args.level, args.depth, args.train,
                    args.vtx_levels, args.max_bars, swing, swing_scenarios=scen, scenario_agg=args.agg,
                    swing_mode="auto" if scen else "manual")
    last = [0.0]

    def progress(info):
        if time.time() - last[0] > 2 or info.get("done") == info.get("total"):
            last[0] = time.time()
            print(f"[{info['elapsed']:6.1f}s] {info['phase']:11s} best={info['best']:.4f} {info['msg']}", flush=True)

    res = Optimizer(cfg, progress).run()
    path = save_result(res)
    sys.stdout.reconfigure(encoding="utf-8")
    print(persian_summary(res))
    print("saved:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
