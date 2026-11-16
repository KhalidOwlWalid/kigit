"""Recent sessions, for the landing page: each project opened in the GUI and
the last two revisions compared there, so it can be opened or resumed.

Kept in <app data>/kigit/sessions.json, next to the logs (one file for every
`kigit gui`, whichever port). Newest first, at most MAX.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import logs

MAX = 30


def path() -> Path:
    return logs.default_dir().parent / "sessions.json"


@dataclass
class Compared:
    old: str          # revision as compared (a hash, LOCAL, or what was typed)
    new: str
    old_label: str = ""  # short hash or name
    new_label: str = ""
    subject: str = ""    # the newer commit's message


@dataclass
class Session:
    dir: str       # the project folder
    board: str     # its .kicad_pcb
    name: str
    opened: float  # time.time() of the last open
    last: Compared | None = None
    extra: dict = field(default_factory=dict)  # room for more without breaking old files

    @property
    def exists(self) -> bool:
        return Path(self.board).exists() or Path(self.dir).is_dir()


def load() -> list[Session]:
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict):
            continue
        try:
            last = d.get("last")
            out.append(Session(str(d["dir"]), str(d["board"]), str(d.get("name") or Path(d["dir"]).name),
                               float(d.get("opened", 0)), Compared(**last) if isinstance(last, dict) else None,
                               d.get("extra") if isinstance(d.get("extra"), dict) else {}))
        except (KeyError, TypeError, ValueError):
            continue  # a broken entry is skipped, not the whole list
    return sorted(out, key=lambda s: s.opened, reverse=True)


def _save(items: list[Session]) -> None:
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps([asdict(s) for s in items[:MAX]], indent=1), encoding="utf-8")
        tmp.replace(p)  # never half a file, even with two GUIs open
    except OSError as e:
        logs.log.warning("couldn't save recent sessions: %s", e)


def _key(board: str) -> str:
    return str(Path(board).expanduser().resolve())


def opened(project_dir: str, board: str, name: str) -> None:
    """A project was opened: to the top of the list."""
    items = load()
    old = next((s for s in items if _key(s.board) == _key(board)), None)
    items = [s for s in items if s is not old]
    items.insert(0, Session(str(project_dir), str(board), name, time.time(), old.last if old else None,
                            old.extra if old else {}))
    _save(items)


def compared(board: str, last: Compared) -> None:
    """Two revisions were compared in the project with this board."""
    items = load()
    for s in items:
        if _key(s.board) == _key(board):
            s.last = last
            s.opened = time.time()
            _save(items)
            return


def forget(board: str) -> None:
    _save([s for s in load() if _key(s.board) != _key(board)])


# --------------------------------------------------------------- snapshots
# A picture of each board (kigit --render), for its card: thumbnails/<key>.png
# (or .svg with KiCad 8)
# next to sessions.json, made again when the board file is newer.

def thumb_key(board: str) -> str:
    return hashlib.sha1(_key(board).encode()).hexdigest()[:16]


def thumb(board: str) -> Path:
    """The board's picture: <key>.png (KiCad 9's 3D render), or <key>.svg
    (a 2D picture: KiCad 8 has no render). The .png path if there's neither."""
    base = path().parent / "thumbnails" / thumb_key(board)
    found = [p for p in (base.with_suffix(".png"), base.with_suffix(".svg")) if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else base.with_suffix(".png")


def thumb_fresh(board: str) -> bool:
    """There's a picture, taken after the board was last saved."""
    try:
        return thumb(board).stat().st_mtime >= Path(board).stat().st_mtime
    except OSError:
        return False


def ago(t: float, now: float | None = None) -> str:
    """"just now", "5 min ago", "3 h ago", "yesterday", "4 days ago", or the date."""
    s = max(0.0, (now or time.time()) - t)
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    if s < 2 * 86400:
        return "yesterday"
    if s < 30 * 86400:
        return f"{int(s // 86400)} days ago"
    return time.strftime("%Y-%m-%d", time.localtime(t))
