"""The notebook: your own notes, as plain Markdown files in the project's
reviews/ folder (an Obsidian vault works as it is: same files, folders in
folders, [[links]], pictures). kigit adds a little on top, all optional:

- Pins: a note can point at parts, nets or footprints, like a review note,
  but it isn't tied to a commit. Kept as one HTML comment at the end of the
  file, which Obsidian and GitHub don't show:
      <!-- kigit-pins [{"tab": "pcb", "kind": "footprint", "name": "U1", "seen": {...}}] -->
- Notes about a part: the notes that pin it, or mention it by name.
- Today's log: a line added under today's heading in a Logs.md
  ("## 16th November 2026", the style of a hand-kept log), with the time,
  what's pinned and the commit you're on.

What isn't a note: kigit's review files, index.md, assets/, threads/, and
hidden folders (.obsidian). Folders that hold files but no Markdown (an
images folder) aren't shown either.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import review
from .review import Anchor

PINS = re.compile(r"\n*<!-- kigit-pins (\[.*?\]) -->\s*\Z", re.DOTALL)
SKIP = {review.ASSETS, "threads"}
LOG = "Logs.md"


@dataclass
class Note:
    path: Path
    title: str
    text: str                 # the Markdown, without kigit's pins comment
    pins: list[Anchor] = field(default_factory=list)


@dataclass
class Folder:
    path: Path
    folders: list["Folder"] = field(default_factory=list)
    notes: list[Path] = field(default_factory=list)


def root(project_dir: str | Path) -> Path:
    return review.folder(project_dir)


def _kigit_files(project_dir: str | Path) -> set[Path]:
    r = root(project_dir)
    return {p.resolve() for p in review.all_reviews(project_dir).values()} | {(r / review.INDEX).resolve()}


def _hidden(p: Path, base: Path) -> bool:
    rel = p.relative_to(base).parts
    return any(part.startswith(".") for part in rel) or (bool(rel) and rel[0] in SKIP)


def tree(project_dir: str | Path) -> Folder:
    """The notes and folders, folders first, by name."""
    base = root(project_dir)
    skip = _kigit_files(project_dir)

    def walk(d: Path) -> Folder:
        f = Folder(d)
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return f
        for p in entries:
            if _hidden(p, base):
                continue
            if p.is_dir():
                sub = walk(p)
                has_files = any(x.is_file() for x in p.rglob("*") if not _hidden(x, base))
                if sub.notes or sub.folders or not has_files:  # an images folder isn't a notes folder
                    f.folders.append(sub)
            elif p.suffix.lower() == ".md" and p.resolve() not in skip:
                f.notes.append(p)
        return f

    return walk(base) if base.is_dir() else Folder(base)


def all_notes(project_dir: str | Path) -> list[Path]:
    out: list[Path] = []

    def collect(f: Folder) -> None:
        out.extend(f.notes)
        for sub in f.folders:
            collect(sub)

    collect(tree(project_dir))
    return out


def title_of(path: Path, text: str) -> str:
    """The first "# " heading, else the file name (as Obsidian shows it)."""
    body = text
    if body.startswith("---"):
        end = body.find("\n---", 3)
        body = body[end + 4:] if end != -1 else body
    m = re.match(r"\s*#\s+(.+?)\s*#*\s*$", body.lstrip("\n").split("\n", 1)[0])
    return m.group(1) if m else path.stem


def read(path: Path) -> Note:
    raw = path.read_text(encoding="utf-8")
    pins: list[Anchor] = []
    m = PINS.search(raw)
    if m:
        try:
            pins = [a for a in (Anchor.from_dict(x) for x in json.loads(m.group(1))) if a]
        except json.JSONDecodeError:
            pins = []
        raw = raw[:m.start()] + "\n"
    return Note(path, title_of(path, raw), raw, pins)


def write(note: Note) -> None:
    """The note's text as it is (yours), then the pins comment if any."""
    text = note.text.rstrip("\n") + "\n"
    if note.pins:
        pins = json.dumps([a.to_dict() for a in note.pins], ensure_ascii=False)
        pins = pins.replace("<", "\\u003c").replace(">", "\\u003e")  # can't end the comment early
        text += f"\n<!-- kigit-pins {pins} -->\n"
    note.path.parent.mkdir(parents=True, exist_ok=True)
    review._write(note.path, text)  # noqa: SLF001  (atomic)


def _file_name(title: str) -> str:
    name = re.sub(r'[\\/:*?"<>|#^\[\]\n]+', " ", title).strip().strip(".") or "Untitled"
    return name[:80]


def _free(path: Path) -> Path:
    n = 2
    out = path
    while out.exists():
        out = path.with_name(f"{path.stem} {n}{path.suffix}")
        n += 1
    return out


def new_note(folder: Path, title: str, pins: list[Anchor] | None = None, text: str = "") -> Note:
    """A new note in `folder`, named after its title (made unique)."""
    title = review.one_line(title).strip() or "Untitled"
    path = _free(folder / f"{_file_name(title)}.md")
    note = Note(path, title, f"# {title}\n\n{text.strip()}\n" if text.strip() else f"# {title}\n\n", list(pins or []))
    write(note)
    return note


def new_folder(parent: Path, name: str) -> Path:
    p = _free(parent / (_file_name(name) or "New folder"))
    p.mkdir(parents=True)
    return p


def rename(note: Note, title: str) -> Note:
    """A new title: the file's name, and its "# " heading if it had one."""
    title = review.one_line(title).strip()
    if not title or title == note.title:
        return note
    # The first "# " heading, if it's the title (not just any heading).
    note.text = re.sub(rf"^#[ \t]+{re.escape(note.title)}[ \t]*$", lambda m: f"# {title}", note.text, count=1,
                       flags=re.MULTILINE)
    new_path = _free(note.path.with_name(f"{_file_name(title)}.md"))
    note.path.rename(new_path)
    note.path, note.title = new_path, title
    write(note)
    return note


# ------------------------------------------------------------- finding notes
def search(project_dir: str | Path, query: str) -> list[Note]:
    """Notes with every word of `query` in their title, text or pins."""
    words = [w.lower() for w in query.split() if w]
    out = []
    for p in all_notes(project_dir):
        try:
            n = read(p)
        except (OSError, UnicodeDecodeError):
            continue
        hay = " ".join([n.title, n.text] + [a.label for a in n.pins]).lower()
        if all(w in hay for w in words):
            out.append(n)
    return out


def same_component(a: Anchor, b: Anchor) -> bool:
    """The same thing on either tab: a schematic part and its PCB footprint
    (same reference), a net by name, a bus by name."""
    group = {"footprint": "part", "part": "part", "net": "net", "bus": "bus"}
    return (group.get(a.kind, a.kind), a.name) == (group.get(b.kind, b.kind), b.name)


def about(project_dir: str | Path, anchor: Anchor) -> list[tuple[Note, str]]:
    """Notes about a part, net or footprint: those that pin it, on either tab
    ("pinned"), then those that mention its name as a word ("mentions")."""
    name = re.escape(anchor.name)
    word = re.compile(rf"(?<![\w+-]){name}(?![\w])")
    pinned, mentioned = [], []
    for p in all_notes(project_dir):
        try:
            n = read(p)
        except (OSError, UnicodeDecodeError):
            continue
        if any(same_component(anchor, a) for a in n.pins):
            pinned.append((n, "pinned"))
        elif anchor.name and word.search(n.text):
            mentioned.append((n, "mentions"))
    return pinned + mentioned


# ----------------------------------------------------------------- the log
def _ordinal(day: int) -> str:
    return f"{day}{'th' if 11 <= day % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')}"


def log_heading(when: datetime) -> str:
    return f"## {_ordinal(when.day)} {when.strftime('%B %Y')}"


def log(folder: Path, line: str, when: datetime | None = None, pinned: Anchor | None = None,
        commit: str = "") -> Path:
    """Adds `- HH:MM line` under today's heading in folder/Logs.md (made if
    there's none), with what's pinned and the commit, if given."""
    when = when or datetime.now()
    path = folder / LOG
    note = read(path) if path.exists() else Note(path, "Logs", "", [])
    extra = " · ".join(x for x in (pinned.label if pinned else "", f"at {commit[:7]}" if commit else "") if x)
    entry = f"- {when.strftime('%H:%M')} {review.one_line(line).strip()}" + (f" ({extra})" if extra else "")
    heading = log_heading(when)
    lines = note.text.rstrip("\n").split("\n") if note.text.strip() else []
    if heading in lines:
        # After the last line of today's section (before the next "## ").
        i = lines.index(heading) + 1
        while i < len(lines) and not lines[i].startswith("## "):
            i += 1
        while i > 0 and not lines[i - 1].strip():
            i -= 1
        lines.insert(i, entry)
    else:
        lines += ([""] if lines else []) + [heading, entry]
    note.text = "\n".join(lines) + "\n"
    write(note)
    return path
