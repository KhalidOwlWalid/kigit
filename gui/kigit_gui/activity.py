"""Your activity in kigit, for the header's heatmap (like GitHub's
contribution graph): how many comparisons, reviews, discussions, replies,
3D views and notes you did each day, in this project.

Kept in the project, so it goes with it through git: one file per person and
computer, `reviews/activity/<person>/<computer>.json` (counts per day and
kind). Each computer only ever writes its own file, so two laptops never
conflict; the heatmap adds up all of a person's files (or everyone's).
"""

from __future__ import annotations

import html
import json
import os
import re
import socket
import threading
from datetime import date, timedelta
from pathlib import Path

from . import logs, review

# The kinds, in the order the breakdown lists them: (singular, plural).
KINDS = {
    "compare": ("comparison", "comparisons"),
    "review": ("review written", "reviews written"),
    "discussion": ("discussion opened", "discussions opened"),
    "reply": ("discussion reply", "discussion replies"),
    "3d": ("3D view", "3D views"),
    "note": ("note or log line", "notes and log lines"),
}
FOLDER = "activity"
_lock = threading.Lock()
_project: Path | None = None
_person = ""


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.") or "someone"


def use(project_dir: str | Path | None, person: str) -> None:
    """The project activity is counted in, and whose (git user.name)."""
    global _project, _person
    _project, _person = (Path(project_dir) if project_dir else None), person


def folder(project_dir: str | Path) -> Path:
    return review.folder(project_dir) / FOLDER


def machine() -> str:
    return _slug(socket.gethostname())


def path() -> Path | None:
    """This person's file on this computer, in the open project."""
    if _project is None:
        return None
    return folder(_project) / _slug(_person) / f"{machine()}.json"


def _read(p: Path) -> dict[str, dict[str, int]]:
    try:
        data = json.loads(p.read_text(encoding="utf-8")).get("days", {})
    except (OSError, ValueError, AttributeError):
        return {}
    return {d: {k: int(n) for k, n in v.items() if isinstance(n, int)} for d, v in data.items() if isinstance(v, dict)}


def people(project_dir: str | Path) -> list[str]:
    """Everyone with activity in the project (their folder names)."""
    d = folder(project_dir)
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def load(project_dir: str | Path | None = None, person: str | None = None) -> dict[str, dict[str, int]]:
    """{"YYYY-MM-DD": {kind: count}}: a person's days (you, by default) added
    up over their computers; person="*" for everyone."""
    project_dir = project_dir if project_dir is not None else _project
    if project_dir is None:
        return {}
    who = _slug(_person if person is None else person)
    files = folder(project_dir).glob("*/*.json") if person == "*" else (folder(project_dir) / who).glob("*.json")
    out: dict[str, dict[str, int]] = {}
    for f in sorted(files):
        for d, counts in _read(f).items():
            day = out.setdefault(d, {})
            for k, n in counts.items():
                day[k] = day.get(k, 0) + n
    return out


def record(kind: str, when: date | None = None) -> None:
    """Counts one `kind` for today, in this computer's file. Never fails the
    thing being counted (and does nothing with no project open)."""
    p = path()
    if kind not in KINDS or p is None:
        return
    day = (when or date.today()).isoformat()
    with _lock:
        days = _read(p)
        days.setdefault(day, {})
        days[day][kind] = days[day].get(kind, 0) + 1
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"days": days}, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, p)
        except OSError as e:
            logs.log.warning("couldn't keep your activity: %s", e)


# ----------------------------------------------------------------- the graph
def stats(days: dict[str, dict[str, int]], today: date | None = None) -> dict:
    """The year up to today: total, by kind, current and longest streak (days
    in a row with anything), busiest day."""
    today = today or date.today()
    start = today - timedelta(days=364)
    total = {d: sum(v.values()) for d, v in days.items()}
    year = {d: n for d, n in total.items() if start.isoformat() <= d <= today.isoformat() and n}
    by_kind = {k: sum(days[d].get(k, 0) for d in year) for k in KINDS}
    longest = run = 0
    for i in range(365):
        run = run + 1 if year.get((start + timedelta(days=i)).isoformat()) else 0
        longest = max(longest, run)
    current, d = 0, today
    if not year.get(d.isoformat()):
        d -= timedelta(days=1)  # today not yet: the streak up to yesterday still counts
    while year.get(d.isoformat()):
        current, d = current + 1, d - timedelta(days=1)
    busiest = max(year.items(), key=lambda kv: (kv[1], kv[0])) if year else None
    return {"total": sum(year.values()), "by_kind": by_kind, "current": current, "longest": longest,
            "busiest": busiest, "active_days": len(year)}


def level(n: int, top: int) -> int:
    """0 (nothing) to 4 (busiest), scaled to the year's busiest day."""
    if n <= 0:
        return 0
    if top <= 4:
        return min(n, 4)
    return min(4, 1 + (n - 1) * 4 // top)


def _tip(day: date, counts: dict[str, int]) -> str:
    n = sum(counts.values())
    when = day.strftime("%a %d %b %Y")
    if not n:
        return f"Nothing on {when}"
    parts = ", ".join(f"{c} {KINDS[k][0] if c == 1 else KINDS[k][1]}" for k, c in counts.items() if c and k in KINDS)
    return f"{n} on {when}: {parts}"


def heatmap_svg(days: dict[str, dict[str, int]], today: date | None = None) -> str:
    """52 weeks and this one, a column per week (Sunday at the top), like
    GitHub's. Each day's square has its tally as a tooltip."""
    today = today or date.today()
    first = today - timedelta(days=364)
    first -= timedelta(days=(first.weekday() + 1) % 7)  # back to a Sunday
    cell, gap, left, top = 12, 3, 30, 18
    weeks = (today - first).days // 7 + 1
    top_n = max([sum(v.values()) for d, v in days.items() if d >= first.isoformat()] or [0])
    out = [f'<svg class="kigit-heat" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {left + weeks * (cell + gap)} '
           f'{top + 7 * (cell + gap)}" role="img" aria-label="Your kigit activity, the last year">']
    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        out.append(f'<text x="0" y="{top + row * (cell + gap) + cell - 2}" class="lbl">{name}</text>')
    month = None
    for w in range(weeks):
        sunday = first + timedelta(days=7 * w)
        if sunday.month != month and sunday.day <= 7:  # a month's first week: its name above
            month = sunday.month
            out.append(f'<text x="{left + w * (cell + gap)}" y="11" class="lbl">{sunday.strftime("%b")}</text>')
        for d in range(7):
            day = sunday + timedelta(days=d)
            if day > today:
                break
            counts = days.get(day.isoformat(), {})
            lv = level(sum(counts.values()), top_n)
            out.append(f'<rect x="{left + w * (cell + gap)}" y="{top + d * (cell + gap)}" width="{cell}" '
                       f'height="{cell}" rx="2" class="l{lv}" data-day="{day.isoformat()}">'
                       f'<title>{html.escape(_tip(day, counts))}</title></rect>')
    out.append("</svg>")
    return "".join(out)


CSS = """<style>
.kigit-heat { width: 100%; height: auto; }
.kigit-heat .lbl { fill: #7d8794; font-size: 9px; font-family: system-ui, sans-serif; }
.kigit-heat rect { stroke: rgba(255,255,255,.04); }
.kigit-heat .l0 { fill: #1c2128; } .kigit-heat .l1 { fill: #5a4519; } .kigit-heat .l2 { fill: #8a6720; }
.kigit-heat .l3 { fill: #c08f2c; } .kigit-heat .l4 { fill: #e8b84d; }
.kigit-heat rect:hover { stroke: #e6e9ee; stroke-width: 1; }
</style>"""
