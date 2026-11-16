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
    by: Author A
    commit: <full hash of the commit it was opened on>
    anchor: {"tab": "pcb", "kind": "footprint", "name": "R704", ...}
    ---

    **Author A** · 2026-11-15 18:02 · at 7cd6670
    <!-- kigit-msg {"author": "Author A", "time": "...", "head": "<hash>", "kind": "comment"} -->

    The courtyard overlaps the keep-out.

    **Author B** · 2026-11-16 09:30 · marked done at 4f2a1c0
    <!-- kigit-msg {... "kind": "done"} -->

    Moved it 1 mm left.

The bold line is for people (GitHub, Obsidian); kigit reads the comment.
Messages are added at the end. Their authors can change their text later
(`edit`): in place, with an "edited" time; nothing else about a message
changes. They can delete their own comments (`delete`), but not status
changes, which would change the status. Whoever opened a discussion can
change what it's about (`repoint`): the anchor in the header changes and a
"repointed" message says so. The status is the last status message's: open (needs attention),
done, accepted.
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
KINDS = ("comment", "done", "accepted", "reopened", "repointed", "renamed")
STATUS = {"done": "done", "accepted": "accepted", "reopened": "open"}  # what each kind sets the status to
LABELS = {"open": "Needs attention", "done": "Done, to be accepted", "accepted": "Accepted"}
VERB = {"comment": "", "done": "marked done", "accepted": "accepted", "reopened": "reopened",
        "repointed": "changed what it's about", "renamed": "renamed it"}

_MSG = re.compile(r"^<!-- kigit-msg (\{.*\}) -->$")


@dataclass
class Message:
    author: str
    time: str
    text: str = ""
    head: str = ""      # the repository's HEAD when it was written ("" unknown)
    kind: str = "comment"
    edited: str = ""    # when its author last changed the text ("" never)


@dataclass
class Thread:
    title: str
    commit: str                 # the commit it was opened on
    by: str = ""
    opened: str = ""
    anchor: Anchor | None = None  # what it's about (the first, if several)
    id: str = field(default_factory=lambda: secrets.token_hex(4))
    messages: list[Message] = field(default_factory=list)
    more: list[Anchor] = field(default_factory=list)  # anything else it's about

    @property
    def anchors(self) -> list[Anchor]:
        return ([self.anchor] if self.anchor else []) + list(self.more)

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
           f"by: {review.one_line(t.by)}", f"commit: {t.commit}", f"anchor: {anchor}"]
    if t.more:  # "anchor" stays the first: older kigit reads that
        out.append(f"more: {json.dumps([a.to_dict() for a in t.more], ensure_ascii=False)}")
    out += ["---", ""]
    for m in t.messages:
        at = f" at {m.head[:7]}" if m.head else ""
        verb = VERB.get(m.kind, "")
        edited = f" · edited {m.edited}" if m.edited else ""
        out.append(f"**{review.one_line(m.author) or 'someone'}** · {m.time} ·{' ' + verb if verb else ''}{at}{edited}")
        fields = {"author": m.author, "time": m.time, "head": m.head, "kind": m.kind}
        if m.edited:
            fields["edited"] = m.edited
        meta = json.dumps(fields, ensure_ascii=False)
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
    try:
        more = json.loads(head.get("more") or "[]")
    except json.JSONDecodeError:
        more = []
    t.more = [a for a in (Anchor.from_dict(x) for x in more if isinstance(more, list)) if a]
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
                                kind, str(meta.get("edited", ""))), []
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


def edit(project_dir: str | Path, thread_id: str, index: int, author: str, time: str, text: str) -> Thread:
    """Changes the text of message `index` (0 = the first), in the
    discussion as it is on disk now, if it's `author`'s and was written at
    `time` (so it's still the message that was shown). Raises ValueError
    otherwise: only your own messages can be changed."""
    p = folder(project_dir) / f"{thread_id}.md"
    t = loads(p.read_text(encoding="utf-8"))
    m = t.messages[index] if 0 <= index < len(t.messages) else None
    if m is None or m.author != author or m.time != time:
        raise ValueError("that message isn't yours, or it's gone")
    if not text.strip() and m.kind == "comment":
        raise ValueError("a message needs some text")
    if text.strip() != m.text.strip():
        m.text = text
        m.edited = review.now()
        save(project_dir, t)
    return t


def delete(project_dir: str | Path, thread_id: str, index: int, author: str, time: str) -> Thread:
    """Removes `author`'s comment `index` (written at `time`) from the
    discussion as it is on disk now. Only your own comments: a status change
    (done, accepted, reopened) stays, since removing it would change the
    status; its text can be edited away. Raises ValueError otherwise."""
    p = folder(project_dir) / f"{thread_id}.md"
    t = loads(p.read_text(encoding="utf-8"))
    m = t.messages[index] if 0 <= index < len(t.messages) else None
    if m is None or m.author != author or m.time != time:
        raise ValueError("that message isn't yours, or it's gone")
    if m.kind != "comment":
        raise ValueError("a status change can't be deleted (edit its text instead)")
    del t.messages[index]
    save(project_dir, t)
    return t


def repoint(project_dir: str | Path, thread_id: str, author: str, head: str, anchors: list[Anchor]) -> Thread:
    """Changes what the discussion is about (a mistake, or more to it):
    the parts, nets or footprints in `anchors`, or the commit in general
    (empty). Only whoever opened it can; a "repointed" message says what it's
    about now (it doesn't change the status). Raises ValueError otherwise."""
    p = folder(project_dir) / f"{thread_id}.md"
    t = loads(p.read_text(encoding="utf-8"))
    if t.by != author:
        raise ValueError(f"only {t.by or 'whoever opened it'} can change what it's about")
    unique: list[Anchor] = []
    for a in anchors:
        if not any(review.same_thing(a, u) for u in unique):
            unique.append(a)
    old = t.anchors
    if len(old) == len(unique) and all(review.same_thing(x, y) for x, y in zip(old, unique)):
        return t
    t.anchor, t.more = (unique[0], unique[1:]) if unique else (None, [])
    labels = lambda xs: ", ".join(a.label for a in xs)  # noqa: E731
    t.messages.append(Message(author, review.now(), f"Now about {labels(unique) or 'the commit in general'}"
                              + (f" (was {labels(old)})" if old else "") + ".", head, "repointed"))
    save(project_dir, t)
    return t


def rename(project_dir: str | Path, thread_id: str, author: str, head: str, title: str) -> Thread:
    """Changes the discussion's title. Only whoever opened it can; a
    "renamed" message keeps the old title. Raises ValueError otherwise."""
    title = review.one_line(title).strip()
    if not title:
        raise ValueError("a discussion needs a title")
    p = folder(project_dir) / f"{thread_id}.md"
    t = loads(p.read_text(encoding="utf-8"))
    if t.by != author:
        raise ValueError(f"only {t.by or 'whoever opened it'} can rename it")
    if title == t.title:
        return t
    old, t.title = t.title, title
    t.messages.append(Message(author, review.now(), f"Was: {old}", head, "renamed"))
    save(project_dir, t)
    return t


# A link to a discussion, pasted into a review or another discussion: plain
# Markdown to its file, relative to reviews/, so it also works on GitHub and
# in Obsidian from a review file.
LINK = re.compile(r"\]\(\s*<?(?:\.\./)?threads/([0-9a-f]{8})\.md")


def link_markdown(t: Thread) -> str:
    title = re.sub(r"[\[\]\n]", "", t.title).strip() or "discussion"
    return f"[{title}](threads/{t.id}.md)"


def linked(text: str) -> list[str]:
    """The discussions a text links to (their IDs, in order, once each)."""
    return list(dict.fromkeys(LINK.findall(text or "")))


def exists(project_dir: str | Path, thread_id: str) -> bool:
    return (folder(project_dir) / f"{thread_id}.md").is_file()


def missing(project_dir: str | Path, text: str) -> list[str]:
    """The discussions a text links to that aren't there (deleted, or not
    pulled yet)."""
    return [i for i in linked(text) if not exists(project_dir, i)]


def counts(threads: list[Thread]) -> dict[str, int]:
    out = {"open": 0, "done": 0, "accepted": 0}
    for t in threads:
        out[t.status] += 1
    return out
