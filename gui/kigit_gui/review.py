"""Commit reviews: why a commit changed what it changed.

One Markdown file per commit in `<project>/reviews/`, images in
`reviews/assets/`. The file reads fine on its own (GitHub, an editor,
Obsidian):

    ---
    commit: <full hash>
    parent: <full hash>
    subject: v2: add C1
    created: 2026-11-13 14:02
    updated: 2026-11-13 14:30
    ---

    Summary of the commit, free Markdown.

    ## Moved U3 closer to the regulator
    <!-- kigit-note {"id": "1a2b3c4d", "anchor": {"tab": "pcb", "kind": "footprint", "name": "U3"}, "tags": ["reason"]} -->

    Note text, free Markdown: links, ![images](assets/3f2a91c0d4e5b6a7.png).

A note starts at a `## ` heading followed by its `kigit-note` comment, so a
`## ` heading inside a note's text stays text. The anchor is what the note is
about in the viewer: a net, footprint, part or bus, by name, plus where it was
pinned (`seen`: the two commits compared, and the side it's on). Commits
don't change, so that comparison always shows it, even after it's deleted;
side "old" means that comparison removed it.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FOLDER = "reviews"
ASSETS = "assets"
TAGS = ["reason", "todo", "question", "risk"]
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
# Names the GUI gives pasted images: content hash plus extension.
ASSET_NAME = re.compile(r"^[0-9a-f]{16}\.(png|jpg|gif|webp)$")

_NOTE_META = re.compile(r"^<!-- kigit-note (\{.*\}) -->$")
_KINDS = {("pcb", "net"): "PCB net", ("pcb", "footprint"): "Footprint",
          ("sch", "net"): "Net", ("sch", "part"): "Part", ("sch", "bus"): "Bus"}


@dataclass
class Seen:
    """Where an anchor was pinned: the comparison old..new (full hashes, ""
    for the working tree), and the side the thing is on."""
    old: str
    new: str
    side: str  # "new", or "old" when old..new removed it

    def to_dict(self) -> dict:
        return {"old": self.old, "new": self.new, "side": self.side}

    @staticmethod
    def from_dict(d) -> Seen | None:
        if not isinstance(d, dict) or not all(isinstance(d.get(k), str) for k in ("old", "new", "side")):
            return None
        return Seen(d["old"], d["new"], d["side"] if d["side"] in ("old", "new") else "new")


@dataclass
class Anchor:
    tab: str   # "pcb" or "sch"
    kind: str  # pcb: net, footprint; sch: net, part, bus
    name: str  # net name, reference or bus name
    seen: Seen | None = None  # None in files from before it was recorded

    @property
    def removed(self) -> bool:
        return bool(self.seen and self.seen.side == "old")

    @property
    def label(self) -> str:
        return f"{_KINDS.get((self.tab, self.kind), self.kind)} {self.name or '(no net)'}"

    @property
    def where(self) -> str:
        """Where it was pinned, for a tooltip."""
        if not self.seen:
            return ""
        short = lambda h: h[:7] if h else "working tree"
        what = "removed there" if self.removed else "present there"
        return f"Pinned in {short(self.seen.old)} → {short(self.seen.new)} ({what})"

    def to_dict(self) -> dict:
        d = {"tab": self.tab, "kind": self.kind, "name": self.name}
        if self.seen:
            d["seen"] = self.seen.to_dict()
        return d

    @staticmethod
    def from_dict(d) -> Anchor | None:
        if not isinstance(d, dict) or not all(isinstance(d.get(k), str) for k in ("tab", "kind", "name")):
            return None
        return Anchor(d["tab"], d["kind"], d["name"], Seen.from_dict(d.get("seen")))


@dataclass
class Note:
    title: str = ""
    body: str = ""
    anchor: Anchor | None = None
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: secrets.token_hex(4))


@dataclass
class Review:
    commit: str
    parent: str = ""
    subject: str = ""
    created: str = ""
    updated: str = ""
    summary: str = ""
    notes: list[Note] = field(default_factory=list)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def one_line(s: str) -> str:
    return " ".join(s.split())


def dumps(r: Review) -> str:
    out = ["---", f"commit: {r.commit}", f"parent: {r.parent}", f"subject: {one_line(r.subject)}",
           f"created: {r.created}", f"updated: {r.updated}", "---", ""]
    if r.summary.strip():
        out += [r.summary.strip(), ""]
    for n in r.notes:
        meta = {"id": n.id, "anchor": n.anchor.to_dict() if n.anchor else None, "tags": n.tags}
        # "<" and ">" escaped so a name can't end the comment early.
        text = json.dumps(meta, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")
        out += [f"## {one_line(n.title) or 'Note'}", f"<!-- kigit-note {text} -->", ""]
        if n.body.strip():
            out += [n.body.strip(), ""]
    return "\n".join(out)


def loads(text: str) -> Review:
    """Reads a review file. Raises ValueError if it has no commit."""
    lines = text.replace("\r\n", "\n").split("\n")
    head: dict[str, str] = {}
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            key, _, value = lines[i].partition(":")
            head[key.strip()] = value.strip()
            i += 1
        i += 1
    if not head.get("commit"):
        raise ValueError("not a kigit review (no commit in the header)")
    r = Review(commit=head["commit"], parent=head.get("parent", ""), subject=head.get("subject", ""),
               created=head.get("created", ""), updated=head.get("updated", ""))

    def is_note(k: int) -> bool:
        return lines[k].startswith("## ") and k + 1 < len(lines) and bool(_NOTE_META.match(lines[k + 1].strip()))

    chunk: list[str] = []
    note: Note | None = None

    def flush() -> None:
        body = "\n".join(chunk).strip()
        if note is None:
            r.summary = body
        else:
            note.body = body
            r.notes.append(note)

    while i < len(lines):
        if is_note(i):
            flush()
            chunk = []
            try:
                meta = json.loads(_NOTE_META.match(lines[i + 1].strip()).group(1))
            except json.JSONDecodeError:
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            tags = meta.get("tags")
            note = Note(title=lines[i][3:].strip(), anchor=Anchor.from_dict(meta.get("anchor")),
                        tags=[t for t in tags if isinstance(t, str)] if isinstance(tags, list) else [],
                        id=str(meta.get("id") or secrets.token_hex(4)))
            i += 2
            continue
        chunk.append(lines[i])
        i += 1
    flush()
    return r


def folder(project_dir: str | Path) -> Path:
    return Path(project_dir) / FOLDER


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40].rstrip("-")


def file_name(r: Review) -> str:
    slug = _slug(r.subject)
    return f"{r.commit[:7]}{'-' + slug if slug else ''}.md"


def all_reviews(project_dir: str | Path) -> dict[str, Path]:
    """Every review in the project: commit hash -> file. Files that aren't
    reviews are skipped."""
    found: dict[str, Path] = {}
    d = folder(project_dir)
    if not d.is_dir():
        return found
    for p in sorted(d.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        m = re.search(r"^commit:\s*([0-9a-f]+)\s*$", text[:2000], re.MULTILINE)
        if text.startswith("---") and m:
            found.setdefault(m.group(1), p)
    return found


def load(path: Path) -> Review:
    return loads(path.read_text(encoding="utf-8"))


def save(project_dir: str | Path, r: Review, path: Path | None = None) -> Path:
    """Writes the review (to `path`, else a new file named after the commit).
    Returns the file."""
    d = folder(project_dir)
    d.mkdir(parents=True, exist_ok=True)
    r.created = r.created or now()
    r.updated = now()
    path = path or d / file_name(r)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(dumps(r), encoding="utf-8", newline="\n")
    tmp.replace(path)  # never leave a half-written review
    return path


def save_image(project_dir: str | Path, data: bytes, mime: str) -> str:
    """Stores a pasted image in reviews/assets/. Returns its path relative to
    the review files (what the Markdown links to)."""
    ext = IMAGE_TYPES.get(mime)
    if not ext:
        raise ValueError(f"unsupported image type {mime}")
    name = f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    d = folder(project_dir) / ASSETS
    d.mkdir(parents=True, exist_ok=True)
    if not (d / name).exists():
        (d / name).write_bytes(data)
    return f"{ASSETS}/{name}"
