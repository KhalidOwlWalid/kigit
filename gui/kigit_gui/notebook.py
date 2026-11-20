"""The notebook: your own notes, as plain Markdown files in the project's
reviews/ folder (an Obsidian vault works as it is: same files, folders in
folders, [[links]], pictures). kigit adds a little on top, all optional:

- Pins: a note can point at parts, nets or footprints, like a review note,
  but it isn't tied to a commit. Kept as one HTML comment at the end of the
  file, which Obsidian and GitHub don't show:
      <!-- kigit-pins [{"tab": "pcb", "kind": "footprint", "name": "U1", "seen": {...}}] -->
- Notes about a part: the notes that pin it, or mention it by name.
- Notes about a BOM line (the BOM page's + Notes): ordinary notes in
  reviews/BOM/, pinned to every part on the line, so they're found from
  the viewer too; why that part was chosen, and when.
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
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import review
from .review import Anchor

PINS = re.compile(r"\n*<!-- kigit-pins (\[.*?\]) -->\s*\Z", re.DOTALL)
SKIP = {review.ASSETS, "threads"}
LOG = "Logs.md"
BOM = "BOM"  # where notes about BOM lines go, in reviews/


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


def listing(project_dir: str | Path, folder: Path) -> Folder:
    """One folder's folders and notes (what the browser shows), the same
    rules as tree()."""
    def find(f: Folder) -> Folder | None:
        if f.path == folder:
            return f
        for sub in f.folders:
            if folder == sub.path or sub.path in folder.parents:
                return find(sub)
        return None
    return find(tree(project_dir)) or Folder(folder)


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


def _inside(project_dir: str | Path, p: Path) -> bool:
    """A path in your notes: inside reviews/, not reviews/ itself, not kigit's."""
    base = root(project_dir).resolve()
    try:
        rel = p.resolve().relative_to(base)
    except ValueError:
        return False
    return bool(rel.parts) and not _hidden(base / rel, base) and p.resolve() not in _kigit_files(project_dir)


def rename_folder(project_dir: str | Path, folder: Path, name: str) -> Path:
    name = _file_name(review.one_line(name).strip())
    if not _inside(project_dir, folder) or not folder.is_dir():
        raise ValueError("that isn't one of your note folders")
    if name == folder.name:
        return folder
    target = folder.with_name(name)
    if target.exists():
        raise ValueError(f"there's already a {name} there")
    folder.rename(target)
    return target


def contents(folder: Path) -> tuple[int, int]:
    """(notes, other files) in a folder, all the way down."""
    files = [p for p in folder.rglob("*") if p.is_file()]
    notes = sum(1 for p in files if p.suffix.lower() == ".md"
                and not any(part.startswith(".") for part in p.relative_to(folder).parts))
    return notes, len(files) - notes  # others: pictures, and hidden things like .obsidian/


def unsaved_in_git(project_dir: str | Path, p: Path) -> int:
    """How many files at p have changes git doesn't have (new or edited):
    deleting those loses them for good. -1 if git can't tell."""
    try:
        r = subprocess.run(["git", "-C", str(Path(project_dir)), "status", "--porcelain", "--", str(p)],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return -1
    return len([line for line in r.stdout.splitlines() if line.strip()]) if r.returncode == 0 else -1


def delete(project_dir: str | Path, p: Path) -> None:
    """Deletes a note, or a folder and everything in it. Only your notes and
    folders: never reviews/ itself or kigit's files and folders."""
    if not _inside(project_dir, p):
        raise ValueError("that isn't one of your notes or note folders")
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()


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


# ------------------------------------------------------- notes about BOM lines
def part_anchors(refs: list[str], head: str = "") -> list[Anchor]:
    """A BOM line's parts as pins (schematic parts, so the PCB's footprints
    match too). Seen in HEAD..working tree, where the BOM was read."""
    from .review import Seen
    seen = Seen(head, "", "new") if head else None
    return [Anchor("sch", "part", r, seen) for r in refs if r]


def notes_for_parts(project_dir: str | Path, refs: list[str]) -> list[Note]:
    """The notes that pin any of these parts (on either tab), newest first."""
    want = set(refs)
    out = []
    for p in all_notes(project_dir):
        try:
            n = read(p)
        except (OSError, UnicodeDecodeError):
            continue
        if any(a.kind in ("part", "footprint") and a.name in want for a in n.pins):
            out.append(n)
    return sorted(out, key=lambda n: n.path.stat().st_mtime if n.path.exists() else 0, reverse=True)


def counts_by_part(project_dir: str | Path) -> dict[str, int]:
    """How many notes pin each part (by reference), for the BOM's + Notes."""
    counts: dict[str, int] = {}
    for p in all_notes(project_dir):
        try:
            n = read(p)
        except (OSError, UnicodeDecodeError):
            continue
        for ref in {a.name for a in n.pins if a.kind in ("part", "footprint")}:
            counts[ref] = counts.get(ref, 0) + 1
    return counts


def bom_note(project_dir: str | Path, line: dict, head: str = "", subject: str = "") -> Note:
    """A new note about a BOM line, in reviews/BOM/: pinned to its parts,
    started with what the part is and the commit you're on."""
    refs = [r for r in line.get("refs", []) if isinstance(r, str)]
    value = review.one_line(str(line.get("value", ""))).strip()
    title = f"{value or 'Part'} ({_refs_short(refs)})"
    facts = [("Parts", ", ".join(refs)), ("Value", value), ("MPN", line.get("mpn", "")),
             ("Manufacturer", line.get("manufacturer", "")), ("Footprint", line.get("footprint", ""))]
    text = "\n".join(f"- **{k}:** {review.one_line(str(v)).strip()}" for k, v in facts if str(v or "").strip())
    if head:
        text += "\n- **Chosen at:** " + commit_ref(head, subject)
    text += "\n\n## Why this part\n\n"
    return new_note(root(project_dir) / BOM, title, part_anchors(refs, head), text)


def _refs_short(refs: list[str]) -> str:
    return ", ".join(refs[:4]) + (f" +{len(refs) - 4}" if len(refs) > 4 else "")


def commit_ref(full_hash: str, subject: str = "", date: str = "") -> str:
    """A commit in a note: its short hash (code), date and subject."""
    bits = [f"`{full_hash[:7]}`"] + ([date[:10]] if date else []) + ([review.one_line(subject).strip()] if subject else [])
    return " ".join(bits[:1]) + (" (" + " · ".join(bits[1:]) + ")" if len(bits) > 1 else "")
