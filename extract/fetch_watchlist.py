# -*- coding: utf-8 -*-
"""
Download OHLCV CSV for watchlist symbols from Chartix API.
Adapted from chartix_fetch/extract/fetch_all_symbols_excel2.py
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import shutil
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from Crypto.Cipher import AES
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
WATCHLIST_FILE = PROJECT_ROOT / "symbols" / "watchlist.json"
API_ID_FILE = BASE_DIR / "api_id.txt"
OUT_DIR = PROJECT_ROOT / "data" / "csv_data"

API_URL = "https://loadfx.chartix.ir/api/v1/history"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Origin": "https://max.chartix.ir",
    "Referer": "https://max.chartix.ir/",
    "Accept": "*/*",
}

DECRYPT_PASSPHRASE = "e122cac15bb1f7c2dff422aa73674580"
# Chartix symbols use Asia/Tehran; intraday bars are written in Tehran wall time to match its chart.
# Daily/weekly/monthly bars stay on the API's UTC date stamps (TradingView convention).
MARKET_TZ = ZoneInfo("Asia/Tehran")
DWM_TIMEFRAMES = {"1D", "1W", "1M"}
PAGE_SIZE = 5000
# Max history pages per timeframe (API pagination until short/empty page)
MAX_PAGES_BY_TF = {
    "1m": 120,
    "5m": 80,
    "10m": 60,
    "15m": 50,
    "30m": 40,
    "45m": 40,
    "1H": 30,
    "2H": 25,
    "3H": 20,
    "1D": 5,
    "1W": 5,
    "1M": 5,
}
DEFAULT_WORKERS = 12
VERBOSE = False

ALL_TIMEFRAMES = [
    "1m", "5m", "10m", "15m", "30m", "45m",
    "1H", "2H", "3H", "1D", "1W", "1M",
]

TF_FILE_MAP = {
    "1m": "1min",
    "5m": "5min",
    "10m": "10min",
    "15m": "15min",
    "30m": "30min",
    "45m": "45min",
    "1H": "1h",
    "2H": "2h",
    "3H": "3h",
    "1D": "1d",
    "1W": "1w",
    "1M": "1mon",
}

FILE_TF_MAP = {v: k for k, v in TF_FILE_MAP.items()}
ADJ_BY_NAME = {"adjusted": 1, "unadjusted": 0, "performance": 2}

# Incremental update: read only the end of each CSV and fetch only recent pages.
UPDATE_TAIL_BYTES = 256 * 1024
UPDATE_PAGE_SIZE = 1000
UPDATE_MAX_PAGES = 15
LOCK_FILE = PROJECT_ROOT / "data" / ".auto_update.lock"

_thread_local = threading.local()
_print_lock = threading.Lock()


def safe_print(*args, **kwargs) -> None:
    text = " ".join(str(a) for a in args)
    try:
        print(text, flush=True, **kwargs)
    except TypeError:
        try:
            print(text, **kwargs)
            sys.stdout.flush()
        except UnicodeEncodeError:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            sys.stdout.buffer.write((text + "\n").encode(enc, errors="replace"))
            sys.stdout.flush()
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        sys.stdout.buffer.write((text + "\n").encode(enc, errors="replace"))
        sys.stdout.flush()


def tf_to_safe_name(tf: str) -> str:
    return TF_FILE_MAP.get(tf.strip(), tf.strip().lower())


def adj_to_name(adj: int) -> str:
    return "adjusted" if adj == 1 else ("unadjusted" if adj == 0 else "performance")


def evp_bytes_to_key_md5(passphrase: bytes, salt: bytes, key_len: int, iv_len: int) -> Tuple[bytes, bytes]:
    d = b""
    prev = b""
    while len(d) < (key_len + iv_len):
        prev = hashlib.md5(prev + passphrase + salt).digest()
        d += prev
    return d[:key_len], d[key_len : key_len + iv_len]


def aes_cbc_pkcs7_decrypt(ciphertext: bytes, key: bytes, iv: bytes) -> Optional[bytes]:
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plain = cipher.decrypt(ciphertext)
    pad = plain[-1]
    if pad < 1 or pad > 16:
        return None
    if plain[-pad:] != bytes([pad]) * pad:
        return None
    return plain[:-pad]


def decrypt_cryptojs_openssl_base64(b64_text: str, passphrase: str) -> Optional[str]:
    try:
        raw = base64.b64decode(b64_text)
    except Exception:
        return None
    if not raw.startswith(b"Salted__"):
        return None
    salt = raw[8:16]
    ciphertext = raw[16:]
    key, iv = evp_bytes_to_key_md5(passphrase.encode("utf-8"), salt, 32, 16)
    plain = aes_cbc_pkcs7_decrypt(ciphertext, key, iv)
    if plain is None:
        return None
    try:
        return plain.decode("utf-8")
    except Exception:
        return None


def parse_json_maybe_encrypted(text: str) -> Optional[Dict]:
    t = (text or "").strip()
    if not t:
        return None
    if t.startswith("U2FsdGVkX1"):
        dec = decrypt_cryptojs_openssl_base64(t, DECRYPT_PASSPHRASE)
        if not dec:
            return None
        try:
            return json.loads(dec)
        except Exception:
            return None
    try:
        return json.loads(t)
    except Exception:
        return None


def format_bar_time(ts: int, tf: str) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if tf.strip() not in DWM_TIMEFRAMES:
        dt = dt.astimezone(MARKET_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def to_rows(data: Dict, tf: str) -> Optional[List[Tuple[str, float, float, float, float, float]]]:
    if not data:
        return None
    if "s" in data and data.get("s") not in ("ok", None, ""):
        return None

    t = data.get("t", [])
    o = data.get("o", [])
    h = data.get("h", [])
    l = data.get("l", [])
    c = data.get("c", [])
    v = data.get("v", [])

    if not isinstance(t, list) or len(t) == 0:
        return None

    n = min(
        len(t),
        len(o),
        len(h),
        len(l),
        len(c),
        len(v) if isinstance(v, list) else len(t),
    )

    rows: List[Tuple[str, float, float, float, float, float]] = []
    for i in range(n):
        try:
            ts = int(t[i])
            open_ = float(o[i])
            high = float(h[i])
            low = float(l[i])
            close = float(c[i])
            vol = float(v[i]) if isinstance(v, list) else 0.0
        except (TypeError, ValueError):
            continue
        rows.append(
            (
                format_bar_time(ts, tf),
                open_,
                high,
                low,
                close,
                vol,
            )
        )

    if not rows:
        return None
    rows.sort(key=lambda r: r[0])
    return rows


def resolution_candidates(tf: str) -> List[str]:
    tf = tf.strip()
    if tf.endswith("m"):
        return [tf[:-1], tf]
    if tf.endswith("H"):
        return [str(int(tf[:-1]) * 60), tf]
    if tf == "1D":
        return ["D", "1D"]
    if tf == "1W":
        return ["W", "1W"]
    if tf == "1M":
        return ["M", "1M"]
    return [tf]


def estimate_from_ts(to_ts: int, tf: str, n: int) -> int:
    tf = tf.strip()
    factor = 4
    if tf.endswith("m"):
        sec_per_bar = int(tf[:-1]) * 60
    elif tf.endswith("H"):
        sec_per_bar = int(tf[:-1]) * 3600
    elif tf == "1D":
        sec_per_bar = 86400
    elif tf == "1W":
        sec_per_bar = 7 * 86400
    elif tf == "1M":
        sec_per_bar = 30 * 86400
    else:
        sec_per_bar = 60

    lookback = n * sec_per_bar * factor
    if tf == "1W":
        lookback = max(lookback, 6 * 365 * 86400)
    if tf == "1M":
        lookback = max(lookback, 12 * 365 * 86400)
    return max(1, int(to_ts - lookback))


def get_session() -> requests.Session:
    sess = getattr(_thread_local, "session", None)
    if sess is not None:
        return sess
    sess = requests.Session()
    sess.headers.update(HEADERS)
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.2,
        status_forcelist=(502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(pool_connections=8, pool_maxsize=8, max_retries=retry)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    _thread_local.session = sess
    return sess


def fetch_candles_page(
    symbol: str,
    tf: str,
    adj: int,
    api_id: str,
    n: int,
    to_ts: int,
) -> Tuple[Optional[List[Tuple[str, float, float, float, float, float]]], Optional[int]]:
    """Return (rows, oldest bar unix ts)."""
    session = get_session()
    frm_ts = estimate_from_ts(to_ts, tf, n)

    for api_res in resolution_candidates(tf):
        params = {
            "symbol": symbol,
            "resolution": api_res,
            "from": frm_ts,
            "to": to_ts,
            "countback": n,
            "id": api_id,
            "adj": adj,
        }
        try:
            r = session.get(API_URL, params=params, timeout=30)
        except Exception as e:
            if VERBOSE:
                print(f"Request error {symbol} {tf} adj={adj} res={api_res} -> {e}")
            continue

        if r.status_code != 200:
            if VERBOSE:
                print(f"HTTP {r.status_code} {symbol} {tf} adj={adj} res={api_res}")
            continue

        data = parse_json_maybe_encrypted(r.text)
        if not data:
            continue

        rows = to_rows(data, tf)
        if rows:
            try:
                oldest_ts = min(int(x) for x in data["t"])
            except (TypeError, ValueError):
                oldest_ts = None
            return rows, oldest_ts
    return None, None


def fetch_all_candles(
    symbol: str,
    tf: str,
    adj: int,
    api_id: str,
    page_size: int = PAGE_SIZE,
) -> Optional[List[Tuple[str, float, float, float, float, float]]]:
    """Paginate backwards until API stops returning new bars."""
    max_pages = MAX_PAGES_BY_TF.get(tf, 20)
    to_ts = int(time.time())
    merged: Dict[str, Tuple[str, float, float, float, float, float]] = {}
    last_oldest: Optional[str] = None

    for _ in range(max_pages):
        rows, oldest_ts = fetch_candles_page(symbol, tf, adj, api_id, page_size, to_ts)
        if not rows or oldest_ts is None:
            break

        before = len(merged)
        for row in rows:
            merged[row[0]] = row
        after = len(merged)
        oldest = rows[0][0]
        newest = rows[-1][0]

        if VERBOSE:
            print(f"  page {symbol} {tf} adj={adj}: +{after - before} ({oldest} .. {newest})")

        if after == before:
            break
        if oldest == last_oldest:
            break
        last_oldest = oldest

        next_to = oldest_ts - 1
        if next_to >= to_ts:
            break
        to_ts = next_to

        # Likely end of history
        if len(rows) < max(50, page_size // 5):
            break

    if not merged:
        return None
    return [merged[k] for k in sorted(merged.keys())]


def fetch_last_n_candles(
    symbol: str,
    tf: str,
    adj: int,
    api_id: str,
    n: int,
) -> Optional[List[Tuple[str, float, float, float, float, float]]]:
    # Back-compat wrapper: full history via pagination
    return fetch_all_candles(symbol, tf, adj, api_id, page_size=max(n, PAGE_SIZE))


def read_watchlist() -> List[Dict[str, str]]:
    if not WATCHLIST_FILE.exists():
        return []
    data = json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
    symbols = data.get("symbols") or []
    out = []
    for s in symbols:
        name = str(s.get("name") or "").strip()
        ticker = str(s.get("ticker") or "").strip()
        if name and ticker:
            out.append({"name": name, "ticker": ticker, "note": str(s.get("note") or "")})
    return out


def read_api_id() -> Optional[str]:
    if API_ID_FILE.exists():
        try:
            x = API_ID_FILE.read_text(encoding="utf-8").strip()
            return x if x else None
        except Exception:
            return None
    return None


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_filename(name: str) -> str:
    bad = '<>:"/\\|?*'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip()[:200]


def replace_file(tmp: Path, path: Path) -> None:
    """Atomic swap; retried because Windows refuses while the chart is reading the file."""
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.25)


def write_csv_rows(path: Path, rows: List[Tuple[str, float, float, float, float, float]]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "volume"])
        w.writerows(rows)
    replace_file(tmp, path)


def create_info_df(symbol: str, display_name: str, sheets: Dict[str, List[Tuple]]) -> pd.DataFrame:
    rows = []
    earliest = None
    latest = None
    total_rows = 0
    for name, data_rows in sheets.items():
        if not data_rows:
            continue
        tmin = data_rows[0][0]
        tmax = data_rows[-1][0]
        earliest = tmin if earliest is None else min(earliest, tmin)
        latest = tmax if latest is None else max(latest, tmax)
        total_rows += len(data_rows)
        rows.append({"sheet": name, "rows": len(data_rows), "from": tmin, "to": tmax})

    header = [
        {"sheet": "Symbol", "rows": symbol, "from": "", "to": ""},
        {"sheet": "Name", "rows": display_name, "from": "", "to": ""},
        {
            "sheet": "Last Update",
            "rows": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "from": "",
            "to": "",
        },
        {"sheet": "Candles Target", "rows": "ALL (paginated)", "from": "", "to": ""},
        {"sheet": "Total Sheets", "rows": len(rows), "from": "", "to": ""},
        {"sheet": "Total Rows", "rows": total_rows, "from": "", "to": ""},
        {"sheet": "Range", "rows": "", "from": earliest, "to": latest},
        {"sheet": "---", "rows": "---", "from": "---", "to": "---"},
    ]
    return pd.DataFrame(header + rows)


def fetch_and_save_one(
    symbol: str,
    tf: str,
    adj: int,
    api_id: str,
    page_size: int,
) -> Tuple[str, str, Optional[List[Tuple]], int]:
    adj_name = adj_to_name(adj)
    rows = fetch_all_candles(symbol, tf, adj, api_id, page_size=page_size)
    if not rows:
        return symbol, f"{tf}_{adj_name}", None, 0

    sym_dir = OUT_DIR / safe_filename(symbol)
    ensure_dir(sym_dir)
    out_path = sym_dir / f"{tf_to_safe_name(tf)}_{adj_name}.csv"
    write_csv_rows(out_path, rows)
    return symbol, f"{tf}_{adj_name}", rows, len(rows)


TailRow = Tuple[int, str, Tuple[float, ...]]


def read_csv_tail(path: Path) -> List[TailRow]:
    """Last rows of a CSV as (byte offset of line, time, (o, h, l, c, v))."""
    size = path.stat().st_size
    start = max(0, size - UPDATE_TAIL_BYTES)
    with open(path, "rb") as f:
        f.seek(start)
        chunk = f.read()
    out: List[TailRow] = []
    offset = start
    for i, raw in enumerate(chunk.split(b"\n")):
        line_off = offset
        offset += len(raw) + 1
        if i == 0 and start > 0:
            continue
        text = raw.rstrip(b"\r").decode("utf-8-sig", errors="replace").strip()
        if not text or text.startswith("time"):
            continue
        cells = text.split(",")
        if len(cells) < 6:
            continue
        try:
            vals = tuple(float(x) for x in cells[1:6])
        except ValueError:
            continue
        out.append((line_off, cells[0], vals))
    return out


def _same_bar(a: Tuple[float, ...], b: Tuple[float, ...]) -> bool:
    return all(abs(x - y) <= 1e-9 * max(1.0, abs(x), abs(y)) for x, y in zip(a, b))


def update_one(symbol: str, tf: str, adj: int, api_id: str) -> Tuple[str, str, str, int]:
    """Bring one existing CSV up to date. Returns (symbol, key, status, new_rows).

    status: "same" | "updated" | "full" (history revised -> re-downloaded) | "fail"
    """
    key = f"{tf}_{adj_to_name(adj)}"
    path = OUT_DIR / safe_filename(symbol) / f"{tf_to_safe_name(tf)}_{adj_to_name(adj)}.csv"

    def full() -> Tuple[str, str, str, int]:
        _, _, rows, n = fetch_and_save_one(symbol, tf, adj, api_id, PAGE_SIZE)
        return symbol, key, ("full" if rows else "fail"), n

    tail = read_csv_tail(path) if path.exists() else []
    if not tail:
        return full()
    last_time = tail[-1][1]

    fetched: Dict[str, Tuple[str, float, float, float, float, float]] = {}
    to_ts = int(time.time())
    overlapped = False
    for _ in range(UPDATE_MAX_PAGES):
        rows, oldest_ts = fetch_candles_page(symbol, tf, adj, api_id, UPDATE_PAGE_SIZE, to_ts)
        if not rows or oldest_ts is None:
            break
        for row in rows:
            fetched[row[0]] = row
        if rows[0][0] <= last_time:
            overlapped = True
            break
        to_ts = oldest_ts - 1
    if not fetched:
        return symbol, key, "fail", 0
    if not overlapped:
        return full()

    existing = {t: (off, vals) for off, t, vals in tail}
    tail_start = tail[0][1]
    overlap = [t for t in sorted(fetched) if t in existing]
    if len(overlap) >= 2 and not _same_bar(existing[overlap[0]][1], fetched[overlap[0]][1:]):
        # The oldest overlapping bar changed: history was rewritten (e.g. capital adjustment).
        return full()

    changed_from: Optional[str] = None
    for t in sorted(fetched):
        if t < tail_start:
            continue
        old = existing.get(t)
        if old is None or not _same_bar(old[1], fetched[t][1:]):
            changed_from = t
            break
    if changed_from is None:
        return symbol, key, "same", 0

    cut = path.stat().st_size
    for off, t, _ in tail:
        if t >= changed_from:
            cut = off
            break
    new_rows = [fetched[t] for t in sorted(fetched) if t >= changed_from]
    buf = io.StringIO()
    csv.writer(buf).writerows(new_rows)

    tmp = path.with_name(path.name + ".tmp")
    shutil.copyfile(path, tmp)
    with open(tmp, "r+b") as f:
        f.truncate(cut)
        if cut > 0:
            f.seek(cut - 1)
            if f.read(1) != b"\n":
                f.write(b"\r\n")
        f.seek(0, os.SEEK_END)
        f.write(buf.getvalue().encode("utf-8"))
    replace_file(tmp, path)
    return symbol, key, "updated", sum(1 for t in new_rows if t[0] > last_time)


def existing_jobs(symbol: str) -> List[Tuple[str, int]]:
    folder = OUT_DIR / safe_filename(symbol)
    jobs: List[Tuple[str, int]] = []
    if not folder.exists():
        return jobs
    for p in folder.glob("*.csv"):
        if "_" not in p.stem:
            continue
        tf_name, adj_name = p.stem.rsplit("_", 1)
        if tf_name in FILE_TF_MAP and adj_name in ADJ_BY_NAME:
            jobs.append((FILE_TF_MAP[tf_name], ADJ_BY_NAME[adj_name]))
    return jobs


def run_update_cycle(watchlist: List[Dict[str, str]], api_id: str, workers: int) -> None:
    tasks: List[Tuple[str, str, int]] = []
    for w in watchlist:
        sym = w["ticker"]
        jobs = existing_jobs(sym)
        if not jobs:
            # New symbol in the watchlist: download its full history once.
            jobs = [(tf, adj) for adj in (1, 0, 2) for tf in ALL_TIMEFRAMES]
        tasks.extend((sym, tf, adj) for tf, adj in jobs)

    t0 = time.time()
    counts: Dict[str, int] = defaultdict(int)
    changed: List[str] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(update_one, sym, tf, adj, api_id) for sym, tf, adj in tasks]
        for fu in as_completed(futures):
            try:
                symbol, key, status, n_new = fu.result()
            except Exception as e:
                counts["fail"] += 1
                safe_print(f"  error: {e}")
                continue
            counts[status] += 1
            if status == "full" or n_new > 0:
                changed.append(f"{symbol} {key}" + (f" +{n_new}" if status == "updated" else " (full)"))

    stamp = datetime.now().strftime("%H:%M:%S")
    safe_print(
        f"[{stamp}] update done in {time.time() - t0:.1f}s | changed {counts['updated'] + counts['full']} | "
        f"same {counts['same']} | full {counts['full']} | fail {counts['fail']}"
    )
    for line in sorted(changed):
        safe_print(f"    {line}")


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def try_lock():
    """Hold an OS lock for the process lifetime so only one updater writes at a time."""
    ensure_dir(LOCK_FILE.parent)
    fh = open(LOCK_FILE, "a+")
    try:
        if os.name == "nt":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def run_update(args, watchlist: List[Dict[str, str]], api_id: str, workers: int) -> None:
    parent = int(args.parent_pid or 0)
    interval = max(0.0, float(args.loop)) * 60.0

    def parent_gone() -> bool:
        return parent > 0 and not pid_alive(parent)

    lock = try_lock()
    if lock is None:
        safe_print("Another updater is already running; waiting for it to finish...")
    while lock is None:
        if parent_gone() or interval <= 0:
            return
        time.sleep(5)
        lock = try_lock()

    while True:
        safe_print(f"Updating {len(watchlist)} symbols (latest candles only)...")
        try:
            run_update_cycle(watchlist, api_id, workers)
        except Exception as e:
            safe_print(f"update cycle failed: {e}")
        if interval <= 0:
            return
        deadline = time.time() + interval
        while time.time() < deadline:
            if parent_gone():
                return
            time.sleep(2)
        if parent_gone():
            return


def parse_args():
    p = argparse.ArgumentParser(description="Chartix watchlist CSV downloader (max history)")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--page_size", type=int, default=PAGE_SIZE, help="Candles per API page")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--update", action="store_true", help="Only fetch new candles into existing CSVs")
    p.add_argument("--loop", type=float, default=0.0, help="With --update: repeat every N minutes")
    p.add_argument("--parent-pid", type=int, default=0, help="Stop when this process exits")
    return p.parse_args()


def main():
    global VERBOSE

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    args = parse_args()
    VERBOSE = bool(args.verbose)
    page_size = max(500, int(args.page_size))
    workers = max(2, int(args.workers))

    print("=" * 70)
    print("Watchlist CSV Downloader (ALL available history, paginated)")
    print("=" * 70)

    watchlist = read_watchlist()
    if not watchlist:
        print(f"Watchlist empty or missing: {WATCHLIST_FILE}")
        return

    api_id = read_api_id()
    if not api_id and args.update:
        print(f"API ID missing: {API_ID_FILE}")
        return
    if not api_id:
        api_id = input("API ID: ").strip()
        if not api_id:
            print("API ID required")
            return

    if args.update:
        ensure_dir(OUT_DIR)
        run_update(args, watchlist, api_id, workers)
        return

    name_by_ticker = {w["ticker"]: w["name"] for w in watchlist}
    symbols = [w["ticker"] for w in watchlist]
    ensure_dir(OUT_DIR)

    tasks: List[Tuple[str, str, int]] = []
    expected_sheets: Dict[str, int] = {}
    for sym in symbols:
        expected_sheets[sym] = len(ALL_TIMEFRAMES) * 3
        for adj in (1, 0, 2):
            for tf in ALL_TIMEFRAMES:
                tasks.append((sym, tf, adj))

    print(f"\nSymbols: {len(symbols)}")
    for w in watchlist:
        safe_print(f"  - {w['name']} -> {w['ticker']}")
    print(f"Jobs: {len(tasks)} (each job paginates until history ends)")
    print(f"Page size: {page_size}")
    print(f"Workers: {workers}")
    print(f"Out: {OUT_DIR}")
    print("-" * 70)

    sheets_by_sym: Dict[str, Dict[str, List[Tuple]]] = defaultdict(dict)
    done_count: Dict[str, int] = defaultdict(int)
    candle_count: Dict[str, int] = defaultdict(int)
    finished_syms: set = set()
    ok = 0
    completed_reqs = 0
    t0 = time.time()
    total_symbols = len(symbols)
    total_reqs = len(tasks)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [
            ex.submit(fetch_and_save_one, sym, tf, adj, api_id, page_size)
            for sym, tf, adj in tasks
        ]
        for fu in as_completed(futures):
            symbol, sheet_key, rows, n_rows = fu.result()
            completed_reqs += 1
            done_count[symbol] += 1

            if rows is not None:
                sheets_by_sym[symbol][sheet_key] = rows
                candle_count[symbol] += n_rows
                ok += 1

            if completed_reqs % 5 == 0 or n_rows > 10000:
                with _print_lock:
                    safe_print(
                        f"JOB:{completed_reqs}/{total_reqs} {symbol} {sheet_key} "
                        f"{'OK '+str(n_rows) if rows is not None else 'FAIL'}"
                    )

            if done_count[symbol] >= expected_sheets[symbol] and symbol not in finished_syms:
                finished_syms.add(symbol)
                sheets = sheets_by_sym.pop(symbol, {})
                display = name_by_ticker.get(symbol, symbol)
                if sheets:
                    info_df = create_info_df(symbol, display, sheets)
                    info_path = OUT_DIR / safe_filename(symbol) / "Info.csv"
                    info_df.to_csv(info_path, index=False, encoding="utf-8-sig")
                with _print_lock:
                    safe_print(
                        f"PROGRESS:{len(finished_syms)}/{total_symbols} "
                        f"JOB:{completed_reqs}/{total_reqs} "
                        f"{'OK' if sheets else 'FAIL'} {display} ({symbol}) "
                        f"{candle_count.get(symbol, 0)} rows"
                    )
                candle_count.pop(symbol, None)

    dt = max(0.001, time.time() - t0)
    print("-" * 70)
    print(f"Done in {dt:.1f}s | ok sheets~{ok} | {total_reqs / dt:.2f} jobs/s")
    print(f"CSV: {OUT_DIR}")


if __name__ == "__main__":
    main()
