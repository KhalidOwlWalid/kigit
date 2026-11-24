"""Calls the kigit command line. Everything the GUI knows comes from here."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
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


def _command(args: tuple[str, ...]) -> list[str]:
    return [kigit_binary(), *args, *logs.kigit_flags()]


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash on Windows


async def _run(*args: str, input: bytes | None = None) -> tuple[bytes, str]:
    """Runs kigit. Returns (stdout, stderr without log lines). In a logged GUI
    session, kigit appends to the session log and its lines are echoed to the
    console. `input` goes to its stdin."""
    started = time.monotonic()
    # subprocess in a worker thread: works the same on Windows, Linux and
    # macOS (asyncio's own subprocess support depends on the event loop type).
    cmd = _command(args)
    proc = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, creationflags=_NO_WINDOW,
                                   input=input if input is not None else b"")
    return _finish(args, proc.returncode, proc.stdout, proc.stderr, started)


def command_line(args: tuple[str, ...] | list[str]) -> str:
    """A command as you'd type it (quoted only where needed), for the log."""
    if sys.platform == "win32":
        return subprocess.list2cmdline(list(args))
    return shlex.join(args)


def _finish(args: tuple[str, ...], code: int, out: bytes, err: bytes, started: float) -> tuple[bytes, str]:
    """Logs a finished run; raises KigitError if it failed."""
    lines = err.decode(errors="replace").splitlines()
    logs.echo_kigit_lines([l for l in lines if _LOG_LINE.match(l)])
    text = "\n".join(l for l in lines if not _LOG_LINE.match(l)).strip()
    cmd = command_line(("kigit", *args))
    logs.log.debug("$ %s  [exit %d%s, %.2f s]", cmd, code, "" if code == 0 else " FAILED", time.monotonic() - started)
    if code != 0:
        message = text.removeprefix("kigit: ") or f"kigit exited with {code}"
        logs.log.warning("$ %s failed: %s", cmd, message)  # a user-facing problem, not a GUI error
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
    parent: str = ""  # first parent's hash ("" for the first commit)


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
    head: str = ""        # HEAD's full hash
    user: str = ""        # git user.name in this repository ("" if unset)


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
        head=data.get("head", ""),
        user=(data.get("user") or {}).get("name", ""),
    )


@dataclass
class Moved:
    """A live commit a rewritten one may have become."""
    hash: str
    short: str
    parent: str
    date: str
    author: str
    subject: str
    body: str


@dataclass
class Rewritten:
    hash: str
    live: bool    # still on a branch, tag or HEAD
    exists: bool  # git still has it
    matches: list[Moved]  # same author and author date (rebase / amend keep those)


async def rewritten(project_dir: str, hashes: list[str]) -> list[Rewritten]:
    """For each commit: still live, and if not, where it may have gone."""
    found: list[Rewritten] = []
    for i in range(0, len(hashes), 200):  # keeps the command line short (Windows)
        out, _ = await _run("-C", project_dir, "--rewritten", *hashes[i:i + 200])
        for c in json.loads(out)["commits"]:
            found.append(Rewritten(c["hash"], c["live"], c["exists"], [Moved(**m) for m in c["matches"]]))
    return found


async def example(dest: Path) -> Path:
    """Makes the example project (a git repository) in dest; returns its
    project folder."""
    out, _ = await _run("example", str(dest))
    return Path(out.decode().strip().splitlines()[-1])


async def render(board: str, out_file: Path) -> Path:
    """Writes a picture of the board on disk (top view, KiCad's 3D render)
    and returns where: out_file, or the same with .svg (KiCad 8 has no 3D
    render, so kigit makes a 2D picture). An older picture in the other
    format is removed."""
    out, _ = await _run("-C", board, "-q", "--render", "-o", str(out_file))
    made = Path(out.strip().splitlines()[-1]) if out.strip() else out_file
    for other in (out_file.with_suffix(".png"), out_file.with_suffix(".svg")):
        if other != made:
            other.unlink(missing_ok=True)
    return made


@dataclass
class Made3d:
    """What kigit --3d said besides making the model."""
    warnings: list[str]
    missing: list[tuple[str, str]]  # parts without a 3D model: (reference, the file KiCad couldn't find)


MISSING_MODEL = "missing 3D model: "


DISK = "disk:"  # a "revision" that's a board file on disk (Compare folders: no git)


async def board3d(project: str, rev: str, out_file: Path) -> Made3d:
    """Writes the board at rev (a hash, or LOCAL; or "disk:<board file>" for
    a board on disk, no git) as a 3D model (.glb) to out_file; KiCad's
    kicad-cli makes it."""
    if rev.startswith(DISK):
        _, err = await _run("-q", "--3d", "--disk", rev[len(DISK):], "-o", str(out_file))
    else:
        _, err = await _run("-C", project, "-q", "--3d", rev, "-o", str(out_file))
    lines = err.splitlines()
    missing = [tuple(line.removeprefix(MISSING_MODEL).split("\t", 1) + [""])[:2]
               for line in lines if line.startswith(MISSING_MODEL)]
    return Made3d([line.removeprefix("warning: ") for line in lines if line.startswith("warning:")], missing)


def _view_options(silkscreen: bool, source: bool) -> list[str]:
    return (["--silkscreen"] if silkscreen else []) + (["--source"] if source else [])


async def diff_html(project: str, old: str, new: str, out_file: Path, silkscreen: bool = False,
                    source: bool = False) -> list[str]:
    """Writes the diff viewer page for old..new to out_file. Returns kigit's warnings.
    silkscreen / source: kigit --silkscreen / --source."""
    extra = _view_options(silkscreen, source)
    _, err = await _run("-C", project, "-n", "-q", *extra, "-o", str(out_file), f"{old}..{new}")
    return [line.removeprefix("warning: ") for line in err.splitlines() if line.startswith("warning:")]


async def bom(board: str, rev: str = "LOCAL") -> dict:
    """kigit bom --json: the bill of materials of the board's schematic at
    `rev` (LOCAL: the files on disk)."""
    out, _ = await _run("bom", "--json", *([] if rev == "LOCAL" else [rev]), board)
    return json.loads(out)


async def bom_write(board: str, edits: list[dict], edits_file: Path, force: bool = False) -> dict:
    """kigit bom --write: sets part information fields ({refs, field, value})
    in the schematic on disk. kigit refuses KiCad's own fields and anything
    that would change the design. Returns {written, fields, backup}."""
    edits_file.write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
    try:
        out, _ = await _run("bom", "--write", str(edits_file), *(["--force"] if force else []), board)
    finally:
        edits_file.unlink(missing_ok=True)
    return json.loads(out)


async def bom_restore(backup: str) -> dict:
    """kigit bom --restore: puts back the files a --write replaced."""
    out, _ = await _run("bom", "--restore", backup)
    return json.loads(out)


async def bom_lcsc_info(refresh: bool = False) -> dict:
    """kigit bom --lcsc-info (or --lcsc-refresh, which downloads first): where
    the LCSC data (jlcparts) is kept, when it was downloaded, its size."""
    out, _ = await _run("bom", "--lcsc-refresh" if refresh else "--lcsc-info")
    return json.loads(out)


async def bom_keys() -> dict:
    """kigit bom --keys: {site: {set, env}} (never the keys themselves)."""
    out, _ = await _run("bom", "--keys")
    return json.loads(out)


async def bom_set_key(site: str, *lines: str) -> None:
    """kigit bom --set-key: the key goes on stdin, never on a command line.
    Mouser: the key; Digi-Key: client ID, secret, "SITE CURRENCY". An empty
    first line removes the site's key."""
    text = "".join(line.strip() + "\n" for line in lines) or "\n"
    await _run("bom", "--set-key", site, input=text.encode())


# kigit bom --lookup's progress lines: "kigit: looking up 3/40 R1 R2"
_PROGRESS = re.compile(r"^kigit: looking up (\d+)/(\d+)[ \t]*(.*)")


async def bom_lookup(board: str, rev: str = "LOCAL", boards: int = 1, refresh: bool = False,
                     progress: Callable[..., None] | None = None,
                     started_proc: Callable[[subprocess.Popen], None] | None = None,
                     sites: list[str] | None = None) -> dict:
    """kigit bom --lookup --json: stock, prices and lifecycle for each line,
    at the given sites (None: kigit's default, every site with a key). Mouser
    is asked about 2 s apart, so this can take a minute; progress(done,
    total, what) follows kigit's progress lines (what: the line's
    references); started_proc gets the process, so it can be stopped."""
    args = ("bom", "--lookup", "--json", "--boards", str(max(1, boards)), *(["--refresh"] if refresh else []),
            *(["--site", ",".join(sites)] if sites else []),
            *([] if rev == "LOCAL" else [rev]), board)
    started = time.monotonic()

    def go() -> tuple[int, bytes, bytes]:
        proc = subprocess.Popen(_command(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
        if started_proc:
            started_proc(proc)
        out: list[bytes] = []
        reader = threading.Thread(target=lambda: out.append(proc.stdout.read()), daemon=True)
        reader.start()
        err = []
        for raw in proc.stderr:
            err.append(raw)
            m = _PROGRESS.match(raw.decode(errors="replace"))
            if m and progress:
                progress(int(m.group(1)) - 1, int(m.group(2)), m.group(3).strip())
        reader.join()
        return proc.wait(), b"".join(out), b"".join(err)

    code, out, err = await asyncio.to_thread(go)
    _finish(args, code, out, err, started)
    return json.loads(out)


async def board_json(board: str, rev: str, out_file: Path) -> None:
    """One revision's board as kigit's viewer data (outline, tracks, pads with
    their parts, zones): kigit --json REV..REV, or --files B B for a board on
    disk ("disk:<board>", no git). For the BOM page's 2D view."""
    if rev.startswith(DISK):
        await _run("-n", "-q", "--json", "-o", str(out_file), "--files", rev[len(DISK):], rev[len(DISK):])
    else:
        await _run("-n", "-q", "--json", "-o", str(out_file), f"{rev}..{rev}", board)


async def diff_json(project: str, old: str, new: str, out_file: Path) -> None:
    """The comparison as kigit's JSON (what changed, where) for old..new, or
    two boards on disk ("disk:<board>", Compare folders). For the 3D diff."""
    if old.startswith(DISK) and new.startswith(DISK):
        await _run("-n", "-q", "--json", "-o", str(out_file), "--files", old[len(DISK):], new[len(DISK):])
    else:
        await _run("-C", project, "-n", "-q", "--json", "-o", str(out_file), f"{old}..{new}")


async def diff_files_html(old_board: str, new_board: str, out_file: Path, silkscreen: bool = False,
                          source: bool = False) -> list[str]:
    """Writes the diff viewer page for two board files, no git involved (each
    board's schematic is read from its own folder). Returns kigit's warnings."""
    extra = _view_options(silkscreen, source)
    _, err = await _run("-n", "-q", *extra, "-o", str(out_file), "--files", old_board, new_board)
    return [line.removeprefix("warning: ") for line in err.splitlines() if line.startswith("warning:")]
