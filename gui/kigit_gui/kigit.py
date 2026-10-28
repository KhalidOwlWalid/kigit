"""Calls the kigit command line. Everything the GUI knows comes from here."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import logs


class KigitError(RuntimeError):
    """kigit exited with an error; the message is its stderr."""


def kigit_binary() -> str:
    """The kigit executable: the one that launched us (KIGIT_BIN), else PATH."""
    env = os.environ.get("KIGIT_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("kigit")
    if found:
        return found
    raise KigitError("kigit not found: start the GUI with `kigit gui`, or put kigit on PATH")


# kigit's own log lines start with a timestamp: "[2026-10-28 14:03:12.345] ..."
_LOG_LINE = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d")


async def _run(*args: str) -> tuple[bytes, str]:
    """Runs kigit. Returns (stdout, stderr without log lines). In a logged GUI
    session, kigit appends to the session log and its lines are echoed to the
    console."""
    session_log = os.environ.get(logs.SESSION_FILE_ENV)
    extra = ["--log-file", session_log, "--log-stderr"] if session_log else ["--no-log"]
    started = time.monotonic()
    # subprocess in a worker thread: works the same on Windows, Linux and
    # macOS (asyncio's own subprocess support depends on the event loop type).
    cmd = [kigit_binary(), *args, *extra]
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash on Windows
    proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, creationflags=no_window)
    out, err = proc.stdout, proc.stderr
    lines = err.decode(errors="replace").splitlines()
    logs.echo_kigit_lines([l for l in lines if _LOG_LINE.match(l)])
    text = "\n".join(l for l in lines if not _LOG_LINE.match(l)).strip()
    logs.log.debug("kigit %s -> exit %d in %.2f s", " ".join(args), proc.returncode, time.monotonic() - started)
    if proc.returncode != 0:
        message = text.removeprefix("kigit: ") or f"kigit exited with {proc.returncode}"
        logs.log.warning("kigit %s failed: %s", " ".join(args), message)  # a user-facing problem, not a GUI error
        raise KigitError(message)
    return out, text


@dataclass
class Commit:
    hash: str
    short: str
    date: str
    author: str
    subject: str
    body: str
    pcb: bool  # changed the board
    sch: bool  # changed the schematic


@dataclass
class Local:
    """Uncommitted changes in the project folder."""
    dirty: bool
    pcb: bool
    sch: bool
    files: list[str]


@dataclass
class History:
    repo: str
    board: str
    folders: list[str]    # every folder the project has lived in (renames followed)
    total: int            # commits matching the filters, before the limit
    commits: list[Commit]
    local: Local


@dataclass
class Project:
    name: str
    dir: str
    level: int   # 0 = the folder itself, 1-2 = below it
    pro: bool
    pcb: bool
    sch: bool
    board: str   # path to the .kicad_pcb, "" if none
    git: bool
    repo: str


async def projects(folder: str, depth: int = 2) -> list[Project]:
    """KiCad projects in folder and up to `depth` levels below it."""
    out, _ = await _run("-C", folder, "--projects", "--depth", str(depth))
    return [Project(**p) for p in json.loads(out)["projects"]]


async def history(project: str, max_count: int = 200, since: str = "", until: str = "",
                  kicad_only: bool = False) -> History:
    """The repository's commits, newest first, plus the uncommitted changes.

    max_count: at most this many (0 = all). since/until: date range ("" = open).
    kicad_only: only commits that changed the board or a schematic, searched
    through the whole history (following the project across folder renames).
    """
    args = ["-C", project, "--log", "--max", str(max_count)]
    if since:
        args += ["--since", since]
    if until:
        args += ["--until", until]
    if kicad_only:
        args.append("--kicad-only")
    out, _ = await _run(*args)
    data = json.loads(out)
    return History(
        repo=data["repo"],
        board=data["board"],
        folders=data["folders"],
        total=data["total"],
        commits=[Commit(**c) for c in data["commits"]],
        local=Local(**data["local"]),
    )


async def diff_html(project: str, old: str, new: str, out_file: Path) -> list[str]:
    """Writes the diff viewer page for old..new to out_file. Returns kigit's warnings."""
    _, err = await _run("-C", project, "-n", "-q", "-o", str(out_file), f"{old}..{new}")
    return [line.removeprefix("warning: ") for line in err.splitlines() if line.startswith("warning:")]
