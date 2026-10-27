"""Calls the kigit command line. Everything the GUI knows comes from here."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


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


async def _run(*args: str) -> tuple[bytes, str]:
    proc = await asyncio.create_subprocess_exec(
        kigit_binary(), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    text = err.decode(errors="replace").strip()
    if proc.returncode != 0:
        raise KigitError(text.removeprefix("kigit: ") or f"kigit exited with {proc.returncode}")
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
