"""Mentions: where a discussion or review is linked from (GitHub's
"mentioned this in ..."). Worked out from the files each time, not written
into the discussion that's linked: an edited or deleted link takes its
mention with it, sending a message only changes its own file (fewer git
conflicts), and mentions arrive with a pull like everything else.

Links are the ones kigit copies: `[title](threads/<id>.md)` to a discussion
and `[subject](<id>.md)` to a review, in discussion messages and in reviews
(summary and notes).

Which mentions you've seen is yours, not the project's: it's kept in
`<app data>/kigit/mentions-seen.json`, per project, for the bell.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import logs, review, threads


@dataclass(frozen=True)
class Mention:
    target: str      # what's linked: "thread:<id>" or "review:<id>"
    kind: str        # where the link is: "discussion" or "review"
    source: str      # its ID
    title: str       # its title (a discussion's) or commit subject (a review's)
    author: str
    time: str        # "YYYY-MM-DD HH:MM"
    where: str = ""  # the message's index, a note's ID, or "summary"

    @property
    def key(self) -> str:
        return f"{self.target}|{self.kind}:{self.source}|{self.where}"


def _targets(text: str) -> list[str]:
    return ([f"thread:{i}" for i in threads.linked(text)]
            + [f"review:{i}" for i in dict.fromkeys(review.REVIEW_LINK.findall(text or ""))])


def all_mentions(project_dir: str | Path) -> dict[str, list[Mention]]:
    """Every mention in the project, by what's mentioned, oldest first."""
    out: dict[str, list[Mention]] = {}

    def add(m: Mention) -> None:
        out.setdefault(m.target, []).append(m)

    for t in threads.all_threads(project_dir):
        for i, msg in enumerate(t.messages):
            for target in _targets(msg.text):
                if target != f"thread:{t.id}":
                    add(Mention(target, "discussion", t.id, t.title, msg.author, msg.time, str(i)))
    for p in review.all_reviews(project_dir).values():
        try:
            r = review.load(p)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        rid = r.id or p.stem
        parts = [("summary", r.summary, r.updated or r.created)] + [(n.id, n.body, n.created or r.updated)
                                                                   for n in r.notes]
        for where, text, when in parts:
            for target in _targets(text):
                if target != f"review:{rid}":
                    add(Mention(target, "review", rid, review.one_line(r.subject), r.author, when, where))
    for items in out.values():
        items.sort(key=lambda m: m.time)
    return out


def involved(t: threads.Thread, me: str) -> bool:
    """You opened the discussion or wrote in it: its mentions are for you."""
    return t.by == me or any(m.author == me for m in t.messages)


# ------------------------------------------------------------ seen (the bell)
def _seen_path() -> Path:
    return logs.default_dir().parent / "mentions-seen.json"


def _load() -> dict[str, list[str]]:
    try:
        data = json.loads(_seen_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def new_for_me(project_dir: str | Path, me: str, found: dict[str, list[Mention]] | None = None) -> list[Mention]:
    """Mentions of your discussions you haven't been told about, by others.
    Marks them seen. The first time a project is seen, its mentions so far
    are taken as seen (no flood of old news)."""
    found = all_mentions(project_dir) if found is None else found
    mine = {f"thread:{t.id}" for t in threads.all_threads(project_dir) if involved(t, me)}
    current = [m for target, ms in found.items() if target in mine for m in ms if m.author != me]
    data = _load()
    key = str(Path(project_dir).resolve())
    first = key not in data
    seen = set(data.get(key, []))
    new = [] if first else [m for m in current if m.key not in seen]
    if first or new:
        data[key] = sorted(seen | {m.key for m in current})
        path = _seen_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as e:
            logs.log.warning("couldn't keep which mentions were seen: %s", e)
    return new
