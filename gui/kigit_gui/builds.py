"""Builds: a batch of boards you're making from the design, e.g.
"December run, 50 boards". Each is a folder next to the board, in git:

    kigit-builds/<id>/build.json   {"version": 1, "name", "boards", "created",
                                    "revision": {"hash", "subject"} | null,
                                    "head": the commit the working tree was at}

revision is the commit the build is for (null: the working tree, with
head saying where it started). A build's id is its folder's name, made
from its name (renaming it renames the folder).

What's bought for it is in the same file (Buy): "tracking" (your tick
columns: Sourced, Carted...) and "carts" (imported from Mouser and LCSC,
with "received" once they're in your inventory); bom.py reads and writes
those (load_extra / save_extra), this keeps them as they are.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

FOLDER = "kigit-builds"
EXTRA = ("tracking", "carts")  # what's bought for a build (bom.py)
FILE = "build.json"
MAX_BOARDS = 100000


class BuildError(ValueError):
    """Something a build can't be (the message says why)."""


@dataclass
class Build:
    id: str
    name: str
    boards: int
    created: str
    revision: dict | None  # {"hash", "subject"}, or None for the working tree
    head: str = ""
    extra: dict | None = None  # what bom.py keeps in it: tracking, carts

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "boards": self.boards, "created": self.created,
                "revision": self.revision, "head": self.head}


def folder(board: str | Path) -> Path:
    return Path(board).parent / FOLDER


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "build"


def _free_id(board: str | Path, name: str, keep: str = "") -> str:
    base, n = _slug(name), 2
    out = base
    while out != keep and (folder(board) / out).exists():
        out = f"{base}-{n}"
        n += 1
    return out


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name:
        raise BuildError("a build needs a name")
    return name[:80]


def _boards(n) -> int:
    try:
        n = int(n)
    except (TypeError, ValueError) as e:
        raise BuildError("the number of boards must be a whole number") from e
    if not 1 <= n <= MAX_BOARDS:
        raise BuildError(f"a build has 1 to {MAX_BOARDS} boards")
    return n


def _read(path: Path) -> Build | None:
    try:
        d = json.loads((path / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not isinstance(d.get("name"), str):
        return None
    rev = d.get("revision") if isinstance(d.get("revision"), dict) else None
    try:
        boards = _boards(d.get("boards", 1))
    except BuildError:
        boards = 1
    extra = {k: d[k] for k in EXTRA if k in d}
    return Build(path.name, d["name"], boards, str(d.get("created", "")), rev, str(d.get("head", "")), extra)


def _write(board: str | Path, b: Build) -> None:
    path = folder(board) / b.id
    path.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "name": b.name, "boards": b.boards, "created": b.created, "revision": b.revision,
            "head": b.head, **{k: v for k, v in (b.extra or {}).items() if k in EXTRA and v}}
    tmp = path / (FILE + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path / FILE)


def all_builds(board: str | Path) -> list[Build]:
    """The board's builds, newest first. Folders without a readable build.json are left out."""
    d = folder(board)
    if not d.is_dir():
        return []
    found = [b for p in d.iterdir() if p.is_dir() and (b := _read(p))]
    return sorted(found, key=lambda b: (b.created, b.id), reverse=True)


def get(board: str | Path, build_id: str) -> Build:
    if not re.fullmatch(r"[a-z0-9-]{1,80}", build_id or ""):
        raise BuildError("no such build")
    b = _read(folder(board) / build_id)
    if b is None:
        raise BuildError(f"no build {build_id}")
    return b


def _git(cwd: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=5,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def new(board: str | Path, name: str, boards: int, rev: str = "LOCAL") -> Build:
    """A new build of `boards` boards, for revision `rev` (a commit's hash, or
    LOCAL for the working tree)."""
    name, boards = _clean_name(name), _boards(boards)
    cwd = Path(board).parent
    revision = None
    if rev and rev != "LOCAL":
        revision = {"hash": rev, "subject": _git(cwd, "log", "-1", "--format=%s", rev)}
    b = Build(_free_id(board, name), name, boards, time.strftime("%Y-%m-%d %H:%M"), revision,
              _git(cwd, "rev-parse", "HEAD"))
    _write(board, b)
    return b


def update(board: str | Path, build_id: str, name: str | None = None, boards: int | None = None) -> Build:
    """A new name (the folder follows it) or number of boards."""
    b = get(board, build_id)
    if boards is not None:
        b.boards = _boards(boards)
    if name is not None and _clean_name(name) != b.name:
        b.name = _clean_name(name)
        new_id = _free_id(board, b.name, keep=b.id)
        if new_id != b.id:
            (folder(board) / b.id).rename(folder(board) / new_id)
            b.id = new_id
    _write(board, b)
    return b


def delete(board: str | Path, build_id: str) -> None:
    b = get(board, build_id)
    shutil.rmtree(folder(board) / b.id)


def load_extra(board: str | Path, build_id: str) -> dict:
    """A build's tracking and carts, as stored (bom.py cleans them)."""
    return dict(get(board, build_id).extra or {})


def save_extra(board: str | Path, build_id: str, extra: dict) -> None:
    """Replaces a build's tracking and carts (re-reading the rest first)."""
    b = get(board, build_id)
    b.extra = {k: extra[k] for k in EXTRA if k in extra}
    _write(board, b)


# ------------------------------------------------------------------ boards
# Boards #1, #2... of a build, each made only when you start it:
#   kigit-builds/<id>/boards/<n>.json  {"version": 1, "board": n, "started",
#       "finished" (when done), "status": "in progress" | "done", "notes",
#       "placed": [refs], "taken": {ref: part ids}}
# taken: what placing a part took out of your inventory (bom.py), so taking
# it off puts back exactly that.
BOARD_STATUS = ("in progress", "done")


def _board_path(board: str | Path, build_id: str, n: int) -> Path:
    get(board, build_id)  # the build must exist (and the id be safe)
    return folder(board) / build_id / "boards" / f"{int(n)}.json"


def _clean_board(d: dict, n: int) -> dict:
    placed = sorted({r for r in d.get("placed", []) if isinstance(r, str)}) if isinstance(d.get("placed"), list) else []
    taken = {r: ids for r, ids in (d.get("taken") or {}).items()
             if isinstance(r, str) and isinstance(ids, dict) and r in placed} if isinstance(d.get("taken"), dict) else {}
    status = d.get("status") if d.get("status") in BOARD_STATUS else "in progress"
    return {"board": n, "started": str(d.get("started", "")), "finished": str(d.get("finished", "")),
            "status": status, "notes": str(d.get("notes", ""))[:5000], "placed": placed, "taken": taken}


def boards(board: str | Path, build_id: str) -> list[dict]:
    """The build's started boards, by number."""
    d = folder(board) / build_id / "boards"
    get(board, build_id)
    out = []
    for p in d.glob("*.json") if d.is_dir() else []:
        if not p.stem.isdigit():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(_clean_board(data, int(p.stem)))
    return sorted(out, key=lambda b: b["board"])


def get_board(board: str | Path, build_id: str, n: int) -> dict:
    p = _board_path(board, build_id, n)
    try:
        return _clean_board(json.loads(p.read_text(encoding="utf-8")), int(n))
    except (OSError, ValueError) as e:
        raise BuildError(f"board #{n} isn't started") from e


def save_board(board: str | Path, build_id: str, b: dict) -> dict:
    p = _board_path(board, build_id, b["board"])
    p.parent.mkdir(parents=True, exist_ok=True)
    b = _clean_board(b, b["board"])
    data = {"version": 1, **{k: v for k, v in b.items() if v or k in ("board", "placed")}}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(p)
    return b


def start_board(board: str | Path, build_id: str, n: int | None = None) -> dict:
    """Board #n (the next one not started, if None): made, nothing placed."""
    b = get(board, build_id)
    have = {x["board"] for x in boards(board, build_id)}
    if n is None:
        n = next(i for i in range(1, b.boards + 2) if i not in have)
    n = int(n)
    if not 1 <= n <= b.boards:
        raise BuildError(f"this build has boards #1 to #{b.boards}")
    if n in have:
        return get_board(board, build_id, n)
    return save_board(board, build_id, {"board": n, "started": time.strftime("%Y-%m-%d %H:%M"), "placed": []})


def delete_board(board: str | Path, build_id: str, n: int) -> None:
    _board_path(board, build_id, n).unlink(missing_ok=True)
