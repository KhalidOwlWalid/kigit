"""Session logging for the GUI.

One file per GUI session, named after when it started
(kigit-gui_2026-10-28_14-03-12_<pid>.log), in the same folder and format as
the kigit command line's logs; every kigit call the GUI makes appends to the
same file (--log-file). Lines also go to the console the GUI was started
from. Old logs are kept.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

log = logging.getLogger("kigit-gui")

# The file kigit calls should append to ("" = no session log).
SESSION_FILE_ENV = "KIGIT_GUI_LOG_FILE"


class _Formatter(logging.Formatter):
    """[2026-10-28 14:03:12.345] [kigit-gui] [info] message (like spdlog's)."""

    def __init__(self) -> None:
        super().__init__("[%(asctime)s.%(msecs)03d] [%(name)s] [%(levellower)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        record.levellower = {"WARNING": "warning", "CRITICAL": "critical"}.get(record.levelname, record.levelname.lower())
        return super().format(record)


def default_dir() -> Path:
    """$KIGIT_LOG_DIR, else $XDG_STATE_HOME/kigit/log, else ~/.local/state/kigit/log (same as kigit)."""
    if os.environ.get("KIGIT_LOG_DIR"):
        return Path(os.environ["KIGIT_LOG_DIR"]).expanduser()
    state = os.environ.get("XDG_STATE_HOME")
    return (Path(state) if state else Path.home() / ".local" / "state") / "kigit" / "log"


def start(log_dir: str | None, enabled: bool = True, debug: bool = False) -> Path | None:
    """Starts logging to the console and (if enabled) a new session file. Returns the file."""
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    log.propagate = False
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(_Formatter())
    log.addHandler(console)
    if not enabled:
        return None
    folder = Path(log_dir).expanduser() if log_dir else default_dir()
    path = folder / f"kigit-gui_{time.strftime('%Y-%m-%d_%H-%M-%S')}_{os.getpid()}.log"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError as e:
        log.warning("can't write a log file in %s (%s); logging to the console only", folder, e)
        return None
    handler.setFormatter(_Formatter())
    log.addHandler(handler)
    os.environ[SESSION_FILE_ENV] = str(path)
    return path


def echo_kigit_lines(lines: list[str]) -> None:
    """Shows kigit's own log lines on the console (they're already in the file)."""
    if not log.handlers:
        return
    for line in lines:
        print(line, file=sys.stderr)
