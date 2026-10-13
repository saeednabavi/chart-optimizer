# -*- coding: utf-8 -*-
"""Start the incremental CSV updater in the background for the chart / optimizer.

Interval comes from AUTO_UPDATE_MINUTES (set in the .bat files); 0 disables it.
The updater exits on its own when the launching process closes.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FETCH_SCRIPT = PROJECT_ROOT / "extract" / "fetch_watchlist.py"
LOG_DIR = PROJECT_ROOT / "output" / "logs"
DEFAULT_MINUTES = 2.0


def start_background_update(tag: str) -> Optional[subprocess.Popen]:
    try:
        minutes = float(os.environ.get("AUTO_UPDATE_MINUTES", DEFAULT_MINUTES))
    except ValueError:
        minutes = DEFAULT_MINUTES
    if minutes <= 0:
        print("Auto data update: off", flush=True)
        return None

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"auto_update_{tag}.txt"
    cmd = [
        sys.executable,
        "-u",
        str(FETCH_SCRIPT),
        "--update",
        "--loop",
        str(minutes),
        "--parent-pid",
        str(os.getpid()),
        "--workers",
        "6",
    ]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        log = open(log_path, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            creationflags=flags,
        )
    except Exception as ex:
        print(f"Auto data update failed to start: {ex}", flush=True)
        return None

    def _stop() -> None:
        if proc.poll() is None:
            proc.terminate()
        log.close()

    atexit.register(_stop)
    print(f"Auto data update every {minutes:g} min (log: {log_path})", flush=True)
    return proc
