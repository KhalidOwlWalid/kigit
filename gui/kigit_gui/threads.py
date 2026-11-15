"""Discussions: PR-style "needs attention" threads on a project.

A discussion is opened from a commit's review, about something on the board
or schematic (an anchor, like a note's) or the commit in general. It belongs
to the project, not to that commit: it's shown on every later commit too,
until someone accepts it. People reply in it like a chat; "done" says the
point was dealt with, "accepted" closes it, "reopened" opens it again.

One file per discussion, so two people rarely touch the same file:

    reviews/threads/7c2e19ab.md

    ---
    id: 7c2e19ab
    title: R704 too close to the mounting hole
    opened: 2026-11-15 18:02
    by: Khalid
    commit: <full hash of the commit it was opened on>
    anchor: {"tab": "pcb", "kind": "footprint", "name": "R704", ...}
    ---

    **Khalid** · 2026-11-15 18:02 · at 7cd6670
    <!-- kigit-msg {"author": "Khalid", "time": "...", "head": "<hash>", "kind": "comment"} -->

    The courtyard overlaps the keep-out.

    **Ada** · 2026-11-16 09:30 · marked done at 4f2a1c0
    <!-- kigit-msg {... "kind": "done"} -->

    Moved it 1 mm left.

The bold line is for people (GitHub, Obsidian); kigit reads the comment.
Messages are only ever added, at the end. The status is the last status
message's: open (needs attention), done, accepted.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from . import review
from .review import Anchor

FOLDER = "threads"
KINDS = ("comment", "done", "accepted", "reopened")
STATUS = {"done": "done", "accepted": "accepted", "reopened": "open"}  # what each kind sets the status to
LABELS = {"open": "Needs attention", "done": "Done, to be accepted", "accepted": "Accepted"}
VERB = {"comment": "", "done": "marked done", "accepted": "accepted", "reopened": "reopened"}

_MSG = re.compile(r"^<!-- kigit-msg (\{.*\}) -->$")


@dataclass
class Message:
    author: str
    time: str
    text: str = ""
    head: str = ""      # the repository's HEAD when it was written ("" unknown)
    kind: str = "comment"


@dataclass
class Thread:
    title: str
    commit: str                 # the commit it was opened on
    by: str = ""
    opened: str = ""
    anchor: Anchor | None = None
    id: str = field(default_factory=lambda: secrets.token_hex(4))
    messages: list[Message] = field(default_factory=list)

    @property
    def status(self) -> str:
        s = "open"
        for m in self.messages:
            s = STATUS.get(m.kind, s)
        return s

    @property
    def updated(self) -> str:
        return self.messages[-1].time if self.messages else self.opened


def folder(project_dir: str | Path) -> Path:
    return review.folder(project_dir) / FOLDER


def dumps(t: Thread) -> str:
    anchor = json.dumps(t.anchor.to_dict(), ensure_ascii=False) if t.anchor else ""
    out = ["---", f"id: {t.id}", f"title: {review.one_line(t.title)}", f"opened: {t.opened}",
           f"by: {review.one_line(t.by)}", f"commit: {t.commit}", f"anchor: {anchor}", "---", ""]
    for m in t.messages:
        at = f" at {m.head[:7]}" if m.head else ""
        verb = VERB.get(m.kind, "")
        out.append(f"**{review.one_line(m.author) or 'someone'}** · {m.time} ·{' ' + verb if verb else ''}{at}")
        meta = json.dumps({"author": m.author, "time": m.time, "head": m.head, "kind": m.kind}, ensure_ascii=False)
        meta = meta.replace("<", "\\u003c").replace(">", "\\u003e")  # a name can't end the comment
        out += [f"<!-- kigit-msg {meta} -->", ""]
        if m.text.strip():
            out += [m.text.strip(), ""]
    return "\n".join(out)


def loads(text: str) -> Thread:
    """Reads a discussion file. Raises ValueError if it isn't one."""
    lines = text.replace("\r\n", "\n").split("\n")
    head: dict[str, str] = {}
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            k, _, v = lines[i].partition(":")
            head[k.strip()] = v.strip()
            i += 1
        i += 1
    if not head.get("id") or "title" not in head:
        raise ValueError("not a kigit discussion")
    anchor = None
    if head.get("anchor"):
        try:
            anchor = Anchor.from_dict(json.loads(head["anchor"]))
        except json.JSONDecodeError:
            pass
    t = Thread(head["title"], head.get("commit", ""), head.get("by", ""), head.get("opened", ""), anchor, head["id"])
    msg: Message | None = None
    body: list[str] = []

    def flush() -> None:
        if msg is not None:
            msg.text = "\n".join(body).strip()
            t.messages.append(msg)

    while i < len(lines):
        m = _MSG.match(lines[i].strip())
        if m:
            if body and body[-1].startswith("**"):
                body.pop()  # the bold line for people, made again on save
            flush()
            try:
                meta = json.loads(m.group(1))
            except json.JSONDecodeError:
                meta = {}
            kind = meta.get("kind") if meta.get("kind") in KINDS else "comment"
            msg, body = Message(str(meta.get("author", "")), str(meta.get("time", "")), "", str(meta.get("head", "")),
                                kind), []
        else:
            body.append(lines[i])
        i += 1
    flush()
    return t


def path_of(project_dir: str | Path, t: Thread) -> Path:
    return folder(project_dir) / f"{t.id}.md"


def save(project_dir: str | Path, t: Thread) -> Path:
    d = folder(project_dir)
    d.mkdir(parents=True, exist_ok=True)
    while not t.opened and path_of(project_dir, t).exists():  # a new one: a free ID
        t.id = secrets.token_hex(4)
    t.opened = t.opened or review.now()
    p = path_of(project_dir, t)
    review._write(p, dumps(t))  # noqa: SLF001  (atomic write)
    return p


def all_threads(project_dir: str | Path) -> list[Thread]:
    """Every discussion in the project: needing attention first, then done,
    then accepted; newest activity first within each."""
    out = []
    d = folder(project_dir)
    for p in sorted(d.glob("*.md")) if d.is_dir() else []:
        try:
            out.append(loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
    order = {"open": 0, "done": 1, "accepted": 2}
    out.sort(key=lambda t: t.updated, reverse=True)
    out.sort(key=lambda t: order[t.status])
    return out


def start(project_dir: str | Path, title: str, text: str, commit: str, author: str, head: str,
          anchor: Anchor | None = None) -> Thread:
    """Opens a discussion, with its first message."""
    now = review.now()
    t = Thread(title.strip() or "Needs attention", commit, author, now, anchor)
    t.messages.append(Message(author, now, text, head, "comment"))
    save(project_dir, t)
    return t


def add(project_dir: str | Path, thread_id: str, author: str, head: str, text: str = "", kind: str = "comment") -> Thread:
    """Adds a message (or a status change, with optional text) to the
    discussion as it is on disk now (someone may have pulled replies)."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind}")
    p = folder(project_dir) / f"{thread_id}.md"
    t = loads(p.read_text(encoding="utf-8"))
    t.messages.append(Message(author, review.now(), text, head, kind))
    save(project_dir, t)
    return t


def counts(threads: list[Thread]) -> dict[str, int]:
    out = {"open": 0, "done": 0, "accepted": 0}
    for t in threads:
        out[t.status] += 1
    return out
