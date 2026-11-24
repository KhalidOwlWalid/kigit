"""Session logging for the GUI.

One file per GUI session, named after when it started
(kigit-gui_2026-10-28_14-03-12_<pid>.log), in the same folder and format as
the kigit command line's logs. Every kigit call the GUI makes appends to the
same file (kigit --log-file), so one file tells the whole story of a session.
Lines also go to the console the GUI was started from. Old logs are kept.

Levels, for the file and the console each (like kigit's; see
include/utils/log.hpp for what goes at which level):
  --log-level LEVEL      the file's: debug by default ($KIGIT_LOG_LEVEL)
  --console-level LEVEL  the console's: info by default ($KIGIT_CONSOLE_LEVEL)
  -V                     = --console-level debug
LEVEL: debug, info, warning, error or off. kigit calls get the same levels.

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

LEVELS = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "warn": logging.WARNING,
          "error": logging.ERROR, "off": logging.CRITICAL + 10}

# This session's levels, by name (passed on to kigit calls).
file_level = "debug"
console_level = "info"

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


def level_name(name: str | None, default: str) -> str:
    """A level's name, checked (ValueError if it isn't one)."""
    name = (name or default).strip().lower()
    if name not in LEVELS:
        raise ValueError(f"unknown log level '{name}' (debug, info, warning, error or off)")
    return "warning" if name == "warn" else name


def start(log_dir: str | None, enabled: bool = True, file: str | None = None,
          console: str | None = None) -> Path | None:
    """Starts this session's logging: the console and (if enabled) a new
    session file, each at its own level (None: $KIGIT_LOG_LEVEL /
    $KIGIT_CONSOLE_LEVEL, else debug for the file and info for the console).
    Calling it again starts over. Returns the file, if any."""
    global session_file, file_level, console_level
    stop()
    file_level = level_name(file or os.environ.get("KIGIT_LOG_LEVEL"), "debug")
    console_level = level_name(console or os.environ.get("KIGIT_CONSOLE_LEVEL"), "info")
    log.setLevel(logging.DEBUG)  # each handler keeps its own level
    log.propagate = False
    formatter = _Formatter()
    if console_level != "off":
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(formatter)
        h.setLevel(LEVELS[console_level])
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
    h.setLevel(LEVELS[file_level])
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
        lib.setLevel(max(logging.WARNING, LEVELS[file_level]))
        for name in _LIBRARY_LOGGERS:
            logging.getLogger(name).addHandler(lib)
        _handlers.append(lib)


def kigit_flags() -> list[str]:
    """Logging flags for a kigit call: append to this session's file at its
    level, and print to stderr (echoed on the console) at the console's."""
    if not session_file:
        return ["--no-log", *(["--console-level", console_level] if console_level != "off" else [])]
    return ["--log-file", str(session_file), "--log-level", file_level,
            *(["--console-level", console_level] if console_level != "off" else [])]


def echo_kigit_lines(lines: list[str]) -> None:
    """Shows kigit's own log lines on the console (they're already in the
    file; kigit printed only those at the console's level)."""
    if console_level == "off":
        return
    for line in lines:
        print(line, file=sys.stderr)


def tail(n: int = 300) -> list[str]:
    """The last n lines of this session's log file (empty if there's none)."""
    if not session_file or not session_file.exists():
        return []
    with open(session_file, encoding="utf-8", errors="replace") as f:
        return [line.rstrip("\n") for line in deque(f, maxlen=n)]
