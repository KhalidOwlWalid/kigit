"""Session logging for the GUI.

One file per GUI session, named after when it started
(kigit-gui_2026-10-28_14-03-12_<pid>.log), in the same folder and format as
the kigit command line's logs. Every kigit call the GUI makes appends to the
same file (kigit --log-file), so one file tells the whole story of a session.
Lines also go to the console the GUI was started from. Old logs are kept.

Also captured: messages shown to the user (see app.notify), unhandled
exceptions in the GUI, and NiceGUI's own warnings and errors.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from pathlib import Path

log = logging.getLogger("kigit-gui")

# The file kigit calls should append to (set while a session log is open).
SESSION_FILE_ENV = "KIGIT_GUI_LOG_FILE"

# NiceGUI and the web server it runs on: their warnings and errors go to the session log too.
_LIBRARY_LOGGERS = ("nicegui", "uvicorn.error")

session_file: Path | None = None
_handlers: list[logging.Handler] = []


class _Formatter(logging.Formatter):
    """[2026-10-28 14:03:12.345] [kigit-gui] [info] message (like kigit's spdlog lines)."""

    def __init__(self) -> None:
        super().__init__("[%(asctime)s.%(msecs)03d] [%(name)s] [%(levellower)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        record.levellower = {"WARNING": "warning", "CRITICAL": "critical"}.get(record.levelname, record.levelname.lower())
        return super().format(record)


def default_dir() -> Path:
    """Same rule as kigit (src/utils/log.cpp + platform.cpp): $KIGIT_LOG_DIR, else the
    app data folder: %LOCALAPPDATA% (Windows), ~/Library/Application Support
    (macOS), $XDG_STATE_HOME or ~/.local/state (Linux); then kigit/log."""
    if os.environ.get("KIGIT_LOG_DIR"):
        return Path(os.environ["KIGIT_LOG_DIR"]).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "kigit" / "log"


def start(log_dir: str | None, enabled: bool = True, debug: bool = False, console: bool = True) -> Path | None:
    """Starts this session's logging: the console and (if enabled) a new
    session file. Calling it again starts over. Returns the file, if any."""
    global session_file
    stop()
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    log.propagate = False
    formatter = _Formatter()
    if console:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(formatter)
        _attach(h)
    if not enabled:
        return None
    folder = Path(log_dir).expanduser() if log_dir else default_dir()
    path = folder / f"kigit-gui_{time.strftime('%Y-%m-%d_%H-%M-%S')}_{os.getpid()}.log"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        h = logging.FileHandler(path, encoding="utf-8")
    except OSError as e:
        log.warning("can't write a log file in %s (%s); logging to the console only", folder, e)
        return None
    h.setFormatter(formatter)
    _attach(h, libraries=True)
    session_file = path
    os.environ[SESSION_FILE_ENV] = str(path)
    return path


def stop() -> None:
    """Closes the session log (handlers removed, file closed)."""
    global session_file
    for h in _handlers:
        log.removeHandler(h)
        for name in _LIBRARY_LOGGERS:
            logging.getLogger(name).removeHandler(h)
        h.close()
    _handlers.clear()
    session_file = None
    os.environ.pop(SESSION_FILE_ENV, None)


def _attach(handler: logging.Handler, libraries: bool = False) -> None:
    log.addHandler(handler)
    _handlers.append(handler)
    if libraries:
        # Library messages: warnings and up only (their info lines are chatty).
        lib = logging.FileHandler(handler.baseFilename, encoding="utf-8")  # type: ignore[attr-defined]
        lib.setFormatter(handler.formatter)
        lib.setLevel(logging.WARNING)
        for name in _LIBRARY_LOGGERS:
            logging.getLogger(name).addHandler(lib)
        _handlers.append(lib)


def echo_kigit_lines(lines: list[str]) -> None:
    """Shows kigit's own log lines on the console (they're already in the file)."""
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in _handlers):
        return
    for line in lines:
        print(line, file=sys.stderr)


def tail(n: int = 300) -> list[str]:
    """The last n lines of this session's log file (empty if there's none)."""
    if not session_file or not session_file.exists():
        return []
    with open(session_file, encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n") for line in deque(f, maxlen=n)]
