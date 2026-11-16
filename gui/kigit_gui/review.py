"""Commit reviews: why a commit changed what it changed.

Everything lives in `<project>/reviews/`:

    reviews/
      index.md        every review: ID, commit, date, author, subject (written by kigit)
      3f9a1c0e.md     one review per commit; its ID is its file name
      assets/         pasted images, named by content hash

A review reads fine on its own (GitHub, an editor, Obsidian):

    ---
    id: 3f9a1c0e
    commit: <full hash>
    parent: <full hash>
    subject: v2: add C1
    date: 2025-03-01 12:00
    author: Author A
    created: 2026-11-13 14:02
    updated: 2026-11-13 14:30
    ---

    Summary of the commit, free Markdown.

    ## Moved U3 closer to the regulator
    <!-- kigit-note {"id": "1a2b3c4d", "anchor": {"tab": "pcb", "kind": "footprint", "name": "U3"}, "tags": ["reason"], "created": "2026-11-13 14:05", "edited": "2026-11-14 09:12"} -->

    Note text, free Markdown: links, ![images](assets/3f2a91c0d4e5b6a7.png).

A note starts at a `## ` heading followed by its `kigit-note` comment, so a
`## ` heading inside a note's text stays text. The anchor is what the note is
about in the viewer: a net, footprint, part or bus, by name, plus where it was
pinned (`seen`: the two commits compared, and the side it's on). Commits
don't change, so that comparison always shows it, even after it's deleted;
side "old" means that comparison removed it.

A note's `created` is when it was first written (Write), `edited` the last
Write that changed it (title, text, tags or anchor); neither is there if
unknown or never.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FOLDER = "reviews"
INDEX = "index.md"
ASSETS = "assets"
TAGS = ["reason", "todo", "question", "risk"]
IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
# Names the GUI gives added files: content hash plus extension.
ASSET_NAME = re.compile(r"^[0-9a-f]{16}\.[a-z0-9]{1,8}$")
# Served as themselves (shown in the browser); any other file is a download.
SHOWN_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
               "pdf": "application/pdf", "txt": "text/plain"}

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
    created: str = ""  # when first written
    edited: str = ""   # when last written with a change ("" if never)

    def content(self) -> tuple:
        """What counts as an edit: as it's written to the file."""
        return (one_line(self.title), self.body.strip(), self.anchor, list(self.tags))


@dataclass
class Review:
    commit: str
    parent: str = ""
    subject: str = ""
    date: str = ""     # the commit's date
    author: str = ""   # the commit's author
    id: str = ""       # the review's ID and file name; given on first save
    created: str = ""
    updated: str = ""
    summary: str = ""
    notes: list[Note] = field(default_factory=list)
    # Review files merged into this one (see absorb), deleted when it's written.
    absorbed: list[Path] = field(default_factory=list, compare=False, repr=False)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def one_line(s: str) -> str:
    return " ".join(s.split())


def dumps(r: Review) -> str:
    out = ["---", f"id: {r.id}", f"commit: {r.commit}", f"parent: {r.parent}", f"subject: {one_line(r.subject)}",
           f"date: {r.date}", f"author: {one_line(r.author)}", f"created: {r.created}", f"updated: {r.updated}",
           "---", ""]
    if r.summary.strip():
        out += [r.summary.strip(), ""]
    for n in r.notes:
        meta = {"id": n.id, "anchor": n.anchor.to_dict() if n.anchor else None, "tags": n.tags}
        if n.created:
            meta["created"] = n.created
        if n.edited:
            meta["edited"] = n.edited
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
               date=head.get("date", ""), author=head.get("author", ""), id=head.get("id", ""),
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
                        id=str(meta.get("id") or secrets.token_hex(4)),
                        created=meta["created"] if isinstance(meta.get("created"), str) else "",
                        edited=meta["edited"] if isinstance(meta.get("edited"), str) else "")
            i += 2
            continue
        chunk.append(lines[i])
        i += 1
    flush()
    return r


def clean_tag(t: str) -> str:
    """A tag as stored: no #, lower case, no spaces (one word, as Obsidian
    wants), so "Needs Review" becomes "needs-review". "" if nothing is left."""
    t = re.sub(r"\s+", "-", t.strip().lstrip("#").lower())
    return re.sub(r"[^\w/-]", "", t).strip("-/")


def known_tags(project_dir: str | Path) -> list[str]:
    """The built-in tags, then every other tag the project's reviews use."""
    used: set[str] = set()
    for p in all_reviews(project_dir).values():
        try:
            used |= {t for n in load(p).notes for t in n.tags}
        except (OSError, ValueError, UnicodeDecodeError):
            continue
    return TAGS + sorted(used - set(TAGS))


def folder(project_dir: str | Path) -> Path:
    return Path(project_dir) / FOLDER


def new_id(project_dir: str | Path) -> str:
    """A review ID not used in the project yet. Random rather than counted, so
    reviews written on two branches can't get the same one."""
    taken = {p.stem for p in folder(project_dir).glob("*.md")}
    while (i := secrets.token_hex(4)) in taken:
        pass
    return i


def file_name(r: Review) -> str:
    return f"{r.id}.md"


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


# A link to a review, pasted into another review or a discussion: Markdown to
# its file, relative to reviews/ (like a discussion link).
REVIEW_LINK = re.compile(r"\]\(\s*<?(?:\.\./)*([0-9a-f]{8})\.md")


def review_link(subject: str, path: Path) -> str:
    title = re.sub(r"[\[\]\n]", "", one_line(subject)).strip() or path.stem
    return f"[{title}]({path.name})"


def is_empty(r: Review) -> bool:
    """Nothing written in it: no summary and no notes."""
    return not r.summary.strip() and not r.notes


def reviewed_commits(project_dir: str | Path) -> set[str]:
    """Commits with a review that has something in it (the commit list's
    mark); an emptied review doesn't count."""
    out = set()
    for commit, p in all_reviews(project_dir).items():
        try:
            if not is_empty(load(p)):
                out.add(commit)
        except (OSError, ValueError, UnicodeDecodeError):
            out.add(commit)  # there, even if unreadable
    return out


def remove(project_dir: str | Path, r: Review, path: Path | None) -> None:
    """Deletes a review's file (and any it took in), then rebuilds the index:
    for a review emptied of everything."""
    for p in [path, *r.absorbed]:
        if p is not None:
            p.unlink(missing_ok=True)
    r.absorbed = []
    if folder(project_dir).is_dir():
        write_index(project_dir)


def load(path: Path) -> Review:
    return loads(path.read_text(encoding="utf-8"))


def _write(path: Path, text: str) -> None:
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)  # never leave a half-written file


def save(project_dir: str | Path, r: Review, path: Path | None = None) -> Path:
    """Writes the review (to `path`, else `<id>.md`, giving it an ID if it has
    none), then the index. Returns the review's file."""
    d = folder(project_dir)
    d.mkdir(parents=True, exist_ok=True)
    r.id = r.id or new_id(project_dir)
    when = now()
    r.created = r.created or when
    r.updated = when
    path = path or d / file_name(r)
    before = None
    if path.exists():
        try:
            before = load(path)
        except (OSError, ValueError, UnicodeDecodeError):
            pass
    stamp(r, before, when)
    _write(path, dumps(r))
    for p in r.absorbed:
        if p != path:
            p.unlink(missing_ok=True)
    r.absorbed = []
    write_index(project_dir)
    return path


# ------------------------------------------------- rewritten commits
# Rebase, amend and squash make new commits, so a review's commit can end up
# on no branch. These move a review to the commit it became.

def retarget(r: Review, commit: str, parent: str, subject: str, date: str, author: str,
             moved: dict[str, str] | None = None) -> None:
    """Points the review at another commit. Anchors pinned in the commit's
    own comparison follow it; other pinned commits follow `moved` (old hash
    -> new) where they were rewritten too."""
    moved = moved or {}
    for n in r.notes:
        s = n.anchor.seen if n.anchor else None
        if not s:
            continue
        if (s.old, s.new) == (r.parent, r.commit):
            s.old, s.new = parent, commit
        else:
            s.old, s.new = moved.get(s.old, s.old), moved.get(s.new, s.new)
    r.commit, r.parent, r.subject, r.date, r.author = commit, parent, subject, date, author


def absorb(target: Review, other: Review, path: Path | None = None) -> None:
    """Adds another review's summary and notes to `target` (several commits
    squashed into one). `path`, the other's file, is deleted when `target`
    is written."""
    if other.summary.strip():
        head = f"From {other.commit[:7]}" + (f" ({one_line(other.subject)})" if other.subject else "")
        target.summary = "\n\n".join(
            x for x in (target.summary.strip(), f"*{head}:*\n\n{other.summary.strip()}") if x)
    ids = {n.id for n in target.notes}
    for n in other.notes:
        while n.id in ids:
            n.id = secrets.token_hex(4)
        ids.add(n.id)
        target.notes.append(n)
    if path is not None:
        target.absorbed.append(path)


def move(project_dir: str | Path, path: Path, commit: str, parent: str, subject: str, date: str, author: str,
         moved: dict[str, str] | None = None) -> Path:
    """Moves the review in `path` to another commit and writes it. If that
    commit has a review already, the two are merged into it. Returns the file."""
    r = load(path)
    retarget(r, commit, parent, subject, date, author, moved)
    there = all_reviews(project_dir).get(commit)
    if there and there != path:
        target = load(there)
        absorb(target, r, path)
        return save(project_dir, target, there)
    return save(project_dir, r, path)


def stamp(r: Review, before: Review | None, when: str) -> None:
    """Sets each note's created / edited times for a write at `when`, from
    what the file held `before` (None: nothing written yet)."""
    old = {n.id: n for n in before.notes} if before else {}
    for n in r.notes:
        o = old.get(n.id)
        if o is None:
            n.created = n.created or when
            continue
        n.created = n.created or o.created
        if n.content() != o.content():
            n.edited = when
        else:
            n.edited = n.edited or o.edited


def _cell(s: str) -> str:
    return one_line(s).replace("|", "\\|")


def index_text(reviews: list[tuple[Review, Path]]) -> str:
    """index.md: one row per review, newest commit first."""
    rows = sorted(reviews, key=lambda x: (x[0].date, x[0].id), reverse=True)
    out = ["# Reviews", "",
           "Written by kigit each time a review is written; edit the reviews, not this file. "
           "A review's ID is its file name (`<ID>.md`).", "",
           "| ID | Commit | Date | Author | Subject | Notes | Written |",
           "| --- | --- | --- | --- | --- | --- | --- |"]
    for r, p in rows:
        out.append(f"| [{_cell(r.id or p.stem)}]({p.name}) | `{r.commit}` | {_cell(r.date)} | {_cell(r.author)} | "
                   f"{_cell(r.subject)} | {len(r.notes)} | {_cell(r.updated)} |")
    return "\n".join(out) + "\n"


def write_index(project_dir: str | Path) -> Path:
    """Rewrites reviews/index.md from the review files."""
    reviews = []
    for p in all_reviews(project_dir).values():
        try:
            reviews.append((load(p), p))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
    path = folder(project_dir) / INDEX
    _write(path, index_text(reviews))
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


def save_file(project_dir: str | Path, data: bytes, filename: str, mime: str = "") -> str:
    """Stores an added file (a datasheet, a picture, a log...) in
    reviews/assets/, named by its content. Returns its path relative to the
    review files. Images keep their type's extension even when pasted
    without a name."""
    ext = IMAGE_TYPES.get(mime) or re.sub(r"[^a-z0-9]", "", Path(filename).suffix.lower())[:8] or "bin"
    name = f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    d = folder(project_dir) / ASSETS
    d.mkdir(parents=True, exist_ok=True)
    if not (d / name).exists():
        (d / name).write_bytes(data)
    return f"{ASSETS}/{name}"


def attachment_markdown(filename: str, path: str, mime: str = "") -> str:
    """The Markdown for an added file: a picture for images, else a link
    named after the file."""
    label = re.sub(r"[\[\]\n]", "", filename or "").strip()
    if mime in IMAGE_TYPES or path.rsplit(".", 1)[-1] in ("png", "jpg", "gif", "webp"):
        return f"![{label}]({path})"
    return f"[{label or path.rsplit('/', 1)[-1]}]({path})"


# ---------------------------------------------------------------- links
# Code, existing links/images, <autolinks> and HTML tags: left alone.
_KEEP = re.compile(r"^(```|~~~).*?^\1|`[^`\n]+`|!?\[[^\]\n]*\]\([^)\n]*\)|<[^>\n]+>", re.MULTILINE | re.DOTALL)
_BARE_URL = re.compile(r"(?<![\w/.@-])(?:https?://|www\.)[^\s<>()\[\]]*[^\s<>()\[\].,;:!?'\"*_~]")


def autolink(text: str) -> str:
    """Bare web addresses (https://..., www....) as Markdown links."""
    def link(m: re.Match) -> str:
        url = m.group(0)
        return f"<{url}>" if url.startswith("http") else f"[{url}](https://{url})"

    out, last = [], 0
    for m in _KEEP.finditer(text):
        out.append(_BARE_URL.sub(link, text[last:m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_BARE_URL.sub(link, text[last:]))
    return "".join(out)


def link_markdown(text: str, url: str) -> str:
    """A Markdown link to `url` showing `text` (the address if empty). A bare
    domain like example.com/x gets https://; spaces and brackets are escaped."""
    url = url.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*:|^[/#.]", url, re.IGNORECASE) and \
            re.match(r"^(www\.)?[\w-]+(\.[\w-]+)+(:\d+)?(/|\?|#|$)", url) and not url.lower().endswith(".md"):
        url = "https://" + url
    url = url.replace(" ", "%20").replace("(", "%28").replace(")", "%29").replace("<", "%3C").replace(">", "%3E")
    text = one_line(text) or url
    text = text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
    return f"[{text}]({url})"


# ---------------------------------------------------------------- math
# $inline$ and $$block$$ LaTeX, as MathML (browsers draw it; no JavaScript).
# Like Pandoc and Obsidian: no space just inside $...$, no digit right after
# the closing $ (so "$5 and $10" stays text), \$ is a dollar sign, and code
# is left alone.
_MATH_CODE = re.compile(r"^(```|~~~).*?^\1|`[^`\n]+`", re.MULTILINE | re.DOTALL)
_MATH_BLOCK = re.compile(r"(?<!\\)\$\$(.+?)(?<!\\)\$\$", re.DOTALL)
_MATH_INLINE = re.compile(r"(?<![\\$])\$(?=[^\s$])([^$\n]*?[^\s\\$])\$(?![\d$])"
                          r"|(?<![\\$])\$([^\s$\\])\$(?![\d$])")


def _mathml(tex: str, block: bool) -> str:
    import latex2mathml.converter

    try:
        return latex2mathml.converter.convert(tex.strip(), display="block" if block else "inline")
    except Exception as e:  # noqa: BLE001  (any bad formula: show it as written)
        shown = f"$${tex}$$" if block else f"${tex}$"
        why = str(e) or type(e).__name__
        return (f'<code class="math-error" title="Not valid LaTeX: {html.escape(why, quote=True)}">'
                f"{html.escape(shown)}</code>")


def to_html(text: str) -> str:
    """Markdown (with bare links and $math$) to HTML."""
    import markdown2

    math: list[str] = []

    def token(converted: str) -> str:
        math.append(converted)
        return f"KIGITMATH{len(math) - 1}X"  # Markdown leaves this alone; swapped back after

    def swap(part: str) -> str:
        part = _MATH_BLOCK.sub(lambda m: "\n\n" + token(_mathml(m.group(1), True)) + "\n\n", part)
        part = _MATH_INLINE.sub(lambda m: token(_mathml(m.group(1) or m.group(2), False)), part)
        return part.replace("\\$", "&#36;")  # \$: a plain dollar sign

    out, last = [], 0
    for m in _MATH_CODE.finditer(text):
        out += [swap(text[last:m.start()]), m.group(0)]
        last = m.end()
    out.append(swap(text[last:]))
    rendered = markdown2.markdown(autolink("".join(out)),
                                  extras=["fenced-code-blocks", "tables", "strike", "task_list"])
    rendered = re.sub(r"<p>\s*KIGITMATH(\d+)X\s*</p>", lambda m: math[int(m.group(1))], rendered)
    return re.sub(r"KIGITMATH(\d+)X", lambda m: math[int(m.group(1))], rendered)
