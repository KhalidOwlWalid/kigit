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


async def history(project: str, max_count: int = 2000) -> History:
    """All commits of the project's repository (newest first) plus the uncommitted changes."""
    out, _ = await _run("-C", project, "--log", "--max", str(max_count))
    data = json.loads(out)
    return History(
        repo=data["repo"],
        board=data["board"],
        commits=[Commit(**c) for c in data["commits"]],
        local=Local(**data["local"]),
    )


async def diff_html(project: str, old: str, new: str, out_file: Path) -> list[str]:
    """Writes the diff viewer page for old..new to out_file. Returns kigit's warnings."""
    _, err = await _run("-C", project, "-n", "-q", "-o", str(out_file), f"{old}..{new}")
    return [line.removeprefix("warning: ") for line in err.splitlines() if line.startswith("warning:")]
