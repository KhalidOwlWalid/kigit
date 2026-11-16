"""A project's reviews, notes and discussions as a small docs site, like
a GitHub Pages / MkDocs site: tabs across the top (Home, Reviews,
Discussions, one per folder of your own notes in reviews/, Tags), the
section's pages on the left, one page per review, note or discussion with
"On this page" on the right, and a search box over everything.

The GUI's Reviews button opens it in a new tab (`/reviews-doc/{key}/`). It's
built from the files in `reviews/` on each request (unwritten drafts aren't
in it). The Reviews tab's front page is the timeline: every review, newest
commit first, by month.

- Notes: any other Markdown file you put in `reviews/` (or a folder in it),
  e.g. design decisions written in Obsidian. Frontmatter is shown as
  properties; `tags:` and #tags go to the Tags tab.
- Links: web addresses (bare ones too) open in a new tab. `[[note]]`,
  `[[note|text]]`, `[[review ID]]`, `[[commit subject]]` and
  `[text](decisions/x.md)` go to that page; links to other files in
  `reviews/` (`[[datasheet.pdf]]`, `[x](docs/x.pdf)`) open them.
  `![[picture.png]]` embeds a picture.
"""

from __future__ import annotations

import base64
import html
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from nicegui import app

from . import review
from .review import Review

_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".webp": "image/webp", ".svg": "image/svg+xml"}
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(\s+\"[^\"]*\")?\s*\)")
_EMBED = re.compile(r"!\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
_MD_LINK = re.compile(r"(?<!!)\[([^\]\n]*)\]\(\s*<?([^)\s>]+)>?(\s+\"[^\"]*\")?\s*\)")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)?(?:#([^\]|]*))?(?:\|([^\]]*))?\]\]")
_INLINE_TAG = re.compile(r"(?<![\w&/#])#([A-Za-z][\w/-]*)")
_FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
_CODE_SPAN = re.compile(r"`[^`\n]+`")
# A #tag in the text (not in a link target, an entity or a heading's #s).
_TEXT_TAG = re.compile(r"(?<![\w&/#(\[\"'=])#([A-Za-z][\w/-]*)")
# Colours for the tags the GUI offers; others are plain.
_TAG_KINDS = {"reason", "todo", "question", "risk"}


def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _short(h: str) -> str:
    return h[:7] if h else ""


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "note"


@dataclass
class Doc:
    """A Markdown file of your own in reviews/."""
    path: Path
    title: str
    body: str
    props: dict[str, str | list[str]]
    tags: list[str]
    edited: str


@dataclass
class Site:
    """What links and pictures can point at, for one page."""
    root: Path                                         # the reviews/ folder
    names: dict[str, str] = field(default_factory=dict)  # lowercased name -> page address
    files: dict[str, Path] = field(default_factory=dict)  # lowercased file name -> file (for ![[...]])
    paths: dict[Path, str] = field(default_factory=dict)  # note/review file -> page address
    files_url: str = ""  # where files in reviews/ are served ("": links to them stay relative)

    def inside(self, path: Path) -> Path | None:
        """`path` resolved, if it's inside reviews/."""
        try:
            path = path.resolve()
            path.relative_to(self.root.resolve())
            return path
        except (OSError, ValueError):
            return None

    def file_url(self, path: Path) -> str:
        rel = path.relative_to(self.root.resolve()).as_posix()
        return self.files_url + urllib.parse.quote(rel) if self.files_url else urllib.parse.quote(rel)

    def image(self, path: Path) -> str | None:
        """A picture inside reviews/: its address when the GUI serves the
        files (files_url), else a data URL; None if it's not a picture there."""
        try:
            path = path.resolve()
            path.relative_to(self.root.resolve())  # nothing from outside reviews/
        except (OSError, ValueError):
            return None
        mime = _MIME.get(path.suffix.lower())
        if not mime or not path.is_file():
            return None
        if self.files_url:
            return self.file_url(path)
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"

    def md(self, text: str, base: Path | None = None, tags: bool = False) -> str:
        """Markdown to HTML: pictures embedded, Obsidian links resolved.
        base: the folder relative links start from (default: reviews/).
        tags: show #tags as tags (your own notes, as Obsidian does)."""
        base = base or self.root
        # Fenced code is left alone.
        blocks: list[str] = []

        def keep(m: re.Match) -> str:
            blocks.append(m.group(0))
            return f"\x00{len(blocks) - 1}\x00"

        text = _FENCE.sub(keep, text)
        if tags:
            text = _CODE_SPAN.sub(keep, text)
            text = _TEXT_TAG.sub(lambda m: f'<span class="itag">#{esc(m.group(1))}</span>', text)

        def embed(m: re.Match) -> str:
            name, size = m.group(1).strip(), (m.group(2) or "").strip()
            found = self.files.get(Path(name).name.lower())
            url = self.image(found) if found else None
            if url:
                width = f' width="{int(size)}"' if size.isdigit() else ""
                return f'<img src="{url}" alt="{esc(name)}"{width}>'
            return self._link(name, "", size or name)

        def image(m: re.Match) -> str:
            alt, src = m.group(1), m.group(2)
            if re.match(r"^[a-z][a-z0-9+.-]*:|^/|^#", src, re.IGNORECASE):
                return m.group(0)  # a web address or data URL: as it is
            url = self.image(base / src)
            return f"![{alt}]({url})" if url else m.group(0)

        def link(m: re.Match) -> str:
            label, href, title = m.group(1), m.group(2), m.group(3) or ""
            if re.match(r"^[a-z][a-z0-9+.-]*:|^/|^#", href, re.IGNORECASE):
                return m.group(0)  # a web address, mailto:, or a place on the page
            target = self.inside(base / urllib.parse.unquote(href.split("#", 1)[0]))
            thread = re.search(r"(?:^|/)threads/([0-9a-f]{8})\.md$", href.split("#", 1)[0])
            if thread:  # a discussion link: relative to reviews/, wherever it's written
                target = self.root / "threads" / f"{thread.group(1)}.md"
                if not target.is_file():
                    return (f'<span class="wl missing" title="This discussion is gone: deleted, or not pulled '
                            f'yet">{esc(label)}</span>')
                target = target.resolve()
            if target is None or not target.is_file():
                return m.group(0)
            to = self.paths.get(target) or self.file_url(target)
            return f"[{label}]({to}{title})"

        def wikilink(m: re.Match) -> str:
            return self._link((m.group(1) or "").strip(), (m.group(2) or "").strip(), (m.group(3) or "").strip())

        text = _EMBED.sub(embed, text)
        text = _MD_IMAGE.sub(image, text)
        text = _MD_LINK.sub(link, text)
        text = _WIKILINK.sub(wikilink, text)
        text = re.sub(r"\x00(\d+)\x00", lambda m: blocks[int(m.group(1))], text)
        return review.to_html(text)  # bare links, $math$, Markdown

    def inline(self, text: str) -> str:
        """One line of Markdown, without the paragraph around it."""
        out = self.md(text).strip()
        m = re.fullmatch(r"<p>(.*)</p>", out, re.DOTALL)
        return m.group(1) if m and "<p>" not in m.group(1) else out

    def _link(self, name: str, heading: str, label: str) -> str:
        shown = esc(label or name or heading)
        target = self.names.get(name.lower()) or self.names.get(Path(name).stem.lower())
        if target:
            return f'<a class="wl" href="{target}">{shown}</a>'
        found = self.files.get(Path(name).name.lower())
        if found:  # another kind of file in reviews/: a datasheet, a PDF, ...
            return f'<a class="wl" href="{esc(self.file_url(found.resolve()))}">{shown}</a>'
        return f'<span class="wl missing" title="Not in reviews/">{shown}</span>'


def _front(text: str) -> tuple[dict[str, str | list[str]], str]:
    """Simple YAML frontmatter (key: value, key: [a, b], and "- item" lists)
    and the text after it."""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() in ("---", "..."))
    except StopIteration:
        return {}, text
    props: dict[str, str | list[str]] = {}
    key = None
    for line in lines[1:end]:
        item = re.match(r"^\s*-\s+(.*)$", line)
        if item and key is not None:
            cur = props.get(key)
            props[key] = (cur if isinstance(cur, list) else []) + [item.group(1).strip().strip("'\"")]
            continue
        m = re.match(r"^([^:\s][^:]*):\s*(.*)$", line)
        if not m:
            continue
        key, value = m.group(1).strip(), m.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            props[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        else:
            props[key] = value.strip("'\"")
    return props, "\n".join(lines[end + 1:])


def load_doc(path: Path) -> Doc:
    text = path.read_text(encoding="utf-8")
    props, body = _front(text)
    title = props.get("title") if isinstance(props.get("title"), str) else ""
    heading = re.match(r"^\s*#\s+(.+?)\s*#*\s*$", body.lstrip("\n").split("\n", 1)[0])
    if not title and heading:
        title = heading.group(1)
        body = body.lstrip("\n").split("\n", 1)[1] if "\n" in body.lstrip("\n") else ""
    raw = props.get("tags", [])
    tags = raw if isinstance(raw, list) else re.split(r"[,\s]+", raw)
    tags = [t.lstrip("#") for t in tags if t.strip("#")]
    tags += [t for t in _INLINE_TAG.findall(_FENCE.sub("", body)) if t not in tags]
    edited = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    return Doc(path, title or path.stem, body, props, tags, edited)


def own_notes(folder: Path, reviews: set[Path]) -> list[Path]:
    """Markdown files in reviews/ that aren't kigit's: not reviews, not the
    index, not in assets/ or hidden folders."""
    out = []
    for p in folder.rglob("*.md"):
        rel = p.relative_to(folder)
        if p in reviews or rel == Path(review.INDEX) or rel.parts[0] in (review.ASSETS, "threads"):
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        out.append(p)
    return out


def _tag(t: str) -> str:
    kind = f" t-{t}" if t in _TAG_KINDS else ""
    return f'<span class="tag{kind}">{esc(t)}</span>'


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"



# ------------------------------------------------------------------ the book
# Every page of the site, built from reviews/ on each request. Page addresses
# (relative to the site's base):
#   ""                         home: counts, latest activity, the tabs
#   reviews                    the timeline: every review, newest first
#   reviews/<id>               one review with all its notes
#   discussions                the discussions, by status
#   discussions/<id>           one discussion
#   notes/<folder>/            a folder of your own notes (one tab per top folder)
#   notes/<folder>/<name>      one note (its path in reviews/, without .md)
#   tags, tags/<tag>           everything with a tag

@dataclass
class Page:
    url: str                 # unquoted, relative to the base
    title: str
    tab: str                 # the tab's key
    kind: str                # home, timeline, review, discussions, thread, folder, note, tags, tag
    date: str = ""
    text: str = ""           # for search
    tags: list[str] = field(default_factory=list)
    obj: object = None
    group: str = ""          # the sidebar group it's listed under


@dataclass
class Tab:
    key: str
    label: str
    url: str


@dataclass
class Book:
    name: str
    root: Path
    base: str
    site: Site
    reviews: list[tuple[Review, Path]]
    talks: list
    docs: list[Doc]
    pages: dict[str, Page] = field(default_factory=dict)
    tabs: list[Tab] = field(default_factory=list)

    def href(self, url: str, frag: str = "") -> str:
        return self.base + urllib.parse.quote(url, safe="/") + (f"#{frag}" if frag else "")


def _doc_url(d: Doc, root: Path) -> str:
    return "notes/" + d.path.relative_to(root).with_suffix("").as_posix()


def _tab_of(d: Doc, root: Path) -> str:
    """A note's tab: its top folder in reviews/, or "notes" for loose files."""
    rel = d.path.relative_to(root)
    return f"f:{rel.parts[0]}" if len(rel.parts) > 1 else "notes"


def _plain(md: str) -> str:
    """Markdown as plain text, for search."""
    t = re.sub(r"<!--.*?-->", " ", md, flags=re.DOTALL)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", t)
    t = re.sub(r"[*_`~]+", "", t)  # emphasis and code marks: gone
    t = re.sub(r"(^|\s)[#>|-]+(?=\s)", " ", t)  # heading, quote, table and list marks
    return re.sub(r"\s+", " ", t).strip()


def build(project_dir: str | Path, name: str = "", files_url: str = "", base: str = "/") -> Book:
    """Reads reviews/ and lays out the site."""
    from . import threads

    project = Path(project_dir)
    pro = sorted(project.glob("*.kicad_pro"))
    name = name or (pro[0].stem if pro else project.name)
    root = review.folder(project)
    site = Site(root, files_url=files_url)

    reviews: list[tuple[Review, Path]] = []
    for p in review.all_reviews(project).values():
        try:
            r = review.load(p)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        r.id = r.id or p.stem
        reviews.append((r, p))
    reviews.sort(key=lambda x: (x[0].date, x[0].id), reverse=True)
    docs: list[Doc] = []
    if root.is_dir():
        for p in own_notes(root, {p for _, p in reviews}):
            try:
                docs.append(load_doc(p))
            except (OSError, UnicodeDecodeError):
                continue
    docs.sort(key=lambda d: d.path.relative_to(root).as_posix().lower())
    talks = threads.all_threads(project)  # needing attention first
    book = Book(name, root, base, site, reviews, talks, docs)

    # Tabs: Home, Reviews, Discussions, one per top folder of notes, loose notes, Tags.
    book.tabs.append(Tab("home", "Home", ""))
    book.tabs.append(Tab("reviews", "Reviews", "reviews"))
    if talks:
        book.tabs.append(Tab("discussions", "Discussions", "discussions"))
    folders = sorted({_tab_of(d, root) for d in docs} - {"notes"}, key=str.lower)
    book.tabs += [Tab(f, f[2:], f"notes/{f[2:]}/") for f in folders]
    if any(_tab_of(d, root) == "notes" for d in docs):
        book.tabs.append(Tab("notes", "Notes", "notes/"))

    # Pages.
    def add(p: Page) -> None:
        book.pages[p.url] = p
    add(Page("", name, "home", "home"))
    add(Page("reviews", "Timeline", "reviews", "timeline"))
    for r, _ in reviews:
        text = " ".join([r.subject, _plain(r.summary)]
                        + [f"{n.title} {' '.join(a.label for a in n.anchors)} {_plain(n.body)}" for n in r.notes]
                        + [r.author, r.id, r.commit])  # findable, but last: snippets show the text
        add(Page(f"reviews/{r.id}", r.subject or "(no message)", "reviews", "review", r.date, text,
                 sorted({t for n in r.notes for t in n.tags}), r, r.date[:7]))
    if talks:
        add(Page("discussions", "Discussions", "discussions", "discussions"))
        for t in talks:
            text = " ".join([t.title, t.by, " ".join(a.label for a in t.anchors)]
                            + [f"{m.author} {_plain(m.text)}" for m in t.messages])
            add(Page(f"discussions/{t.id}", t.title, "discussions", "thread", t.opened, text, [t.status], t,
                     _THREAD_LOOK[t.status][0]))
    for f in folders:
        add(Page(f"notes/{f[2:]}/", f[2:], f, "folder"))
    if any(_tab_of(d, root) == "notes" for d in docs):
        add(Page("notes/", "Notes", "notes", "folder"))
    for d in docs:
        rel = d.path.relative_to(root)
        group = rel.parent.as_posix() if len(rel.parts) > 2 else ""
        add(Page(_doc_url(d, root), d.title, _tab_of(d, root), "note", d.edited, _plain(d.body), d.tags, d,
                 group))
    tags = sorted({t for p in book.pages.values() if p.kind in ("review", "note") for t in p.tags})
    if tags:
        book.tabs.append(Tab("tags", "Tags", "tags"))
        add(Page("tags", "Tags", "tags", "tags"))
        for t in tags:
            add(Page(f"tags/{t}", f"#{t}", "tags", "tag", tags=[t]))

    # What [[links]], relative links and ![[embeds]] reach: page addresses.
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                site.files.setdefault(p.name.lower(), p)
    for d in docs:
        to = book.href(_doc_url(d, root))
        for key in (d.title, d.path.stem, d.path.relative_to(root).with_suffix("").as_posix()):
            site.names.setdefault(key.lower(), to)
        site.paths[d.path.resolve()] = to
    for r, p in reviews:
        to = book.href(f"reviews/{r.id}")
        for key in (r.id, p.stem):
            site.names.setdefault(key.lower(), to)
        site.paths[p.resolve()] = to
    for t in talks:
        site.paths[(root / "threads" / f"{t.id}.md").resolve()] = book.href(f"discussions/{t.id}")
    for r, _ in reviews:  # [[commit subject]] too, after IDs and notes
        if r.subject:
            site.names.setdefault(review.one_line(r.subject).lower(), book.href(f"reviews/{r.id}"))
    return book


def search_index(book: Book) -> list[dict]:
    """Every page, and every note in a review, for the search box."""
    out = []
    for p in book.pages.values():
        if p.kind in ("review", "thread", "note"):
            out.append({"u": book.href(p.url), "t": p.title, "k": _KIND_LABEL[p.kind], "d": p.date[:10],
                        "g": p.tags, "x": p.text[:6000]})
    for r, _ in book.reviews:
        for n in r.notes:
            out.append({"u": book.href(f"reviews/{r.id}", f"n-{n.id}"), "t": n.title or "Note",
                        "k": f"Note · {review.one_line(r.subject)[:60]}", "d": r.date[:10], "g": n.tags,
                        "x": f"{' '.join(a.label for a in n.anchors)} {_plain(n.body)}"[:3000]})
    return out


_KIND_LABEL = {"review": "Review", "thread": "Discussion", "note": "Note"}


# ------------------------------------------------------------------ pieces
def _one_anchor(a) -> str:
    cls = "anchor removed" if a.removed else "anchor"
    label = a.label + (" · removed" if a.removed else "")
    return (f'<span class="{cls}" title="{esc(a.where)}"><b class="tab tab-{esc(a.tab)}">{esc(a.tab.upper())}</b>'
            f'{esc(label)}</span>')


def _anchor_html(n) -> str:
    """What a note (or discussion) is about: a badge each."""
    anchors = n.anchors
    if not anchors:
        return '<span class="anchor general">General note</span>'
    return "".join(_one_anchor(a) for a in anchors)


_THREAD_LOOK = {"open": ("Needs attention", "t-risk"), "done": ("Done, to be accepted", "t-todo"),
                "accepted": ("Accepted", "t-ok")}


def _with_ids(html_text: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Gives h2/h3 headings ids, for the "On this page" list."""
    found: list[tuple[int, str, str]] = []
    taken: set[str] = set()

    def give(m: re.Match) -> str:
        level, inner = int(m.group(1)), m.group(2)
        text = html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
        base = slug = "h-" + _slug(text)
        n = 2
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        taken.add(slug)
        found.append((level, slug, text))
        return f'<h{level} id="{slug}">{inner}</h{level}>'
    return re.sub(r"<h([23])>(.*?)</h\1>", give, html_text, flags=re.DOTALL), found


def _chips(r: Review) -> str:
    chips = []
    if r.parent:
        chips.append(f'<span class="chip commit" title="Compared with its parent">'
                     f'<code title="{esc(r.parent)}">{esc(_short(r.parent))}</code><span class="arrow">→</span>'
                     f'<code title="{esc(r.commit)}">{esc(_short(r.commit))}</code></span>')
    else:
        chips.append(f'<span class="chip commit"><code title="{esc(r.commit)}">{esc(_short(r.commit))}</code></span>')
    if r.author:
        chips.append(f'<span class="chip"><span class="av">{esc(r.author.strip()[:1].upper())}</span>'
                     f'{esc(r.author)}</span>')
    chips.append(f'<span class="chip id" title="Review ID: its file name in reviews/">{esc(r.id)}</span>')
    if r.notes:
        chips.append(f'<span class="chip">{_plural(len(r.notes), "note")}</span>')
    return f'<div class="meta">{"".join(chips)}</div>'


def _when(date: str) -> str:
    day, _, clock = (date or "").partition(" ")
    return f'<div class="when"><time>{esc(day)}</time><span>{esc(clock)}</span></div>'


def _note_html(n, site: Site) -> str:
    times = ""
    if n.created:
        times = f"Written {esc(n.created)}" + (f" · edited {esc(n.edited)}" if n.edited else "")
    kind = next((f" t-{t}" for t in n.tags if t in _TAG_KINDS), "")
    return (f'<article class="note{kind}" id="n-{esc(n.id)}">'
            f'<div class="nhead"><h3><a class="hash" href="#n-{esc(n.id)}" title="Link to this note">#</a>'
            f'{esc(n.title) or "Note"}</h3>'
            f'<div class="noterow">{_anchor_html(n)}{"".join(_tag(t) for t in n.tags)}</div></div>'
            + (f'<div class="md">{site.md(n.body)}</div>' if n.body.strip() else "")
            + (f'<div class="times">{times}</div>' if times else "")
            + "</article>")


def _review_page(book: Book, r: Review) -> tuple[str, list]:
    written = f"Review written {esc(r.created)}" + (f" · updated {esc(r.updated)}" if r.updated != r.created else "")
    out = [f'<section class="review single" id="r-{esc(r.id)}">', _when(r.date), '<div class="rbody">',
           f'<h1 class="title">{esc(r.subject) or "(no message)"}</h1>', _chips(r),
           f'<div class="written">{written}</div>']
    toc = []
    if r.summary.strip():
        out.append(f'<div class="md summary" id="summary">{book.site.md(r.summary)}</div>')
        toc.append((2, "summary", "Summary"))
    if not r.summary.strip() and not r.notes:
        out.append('<p class="empty">Nothing written in this review.</p>')
    for n in r.notes:
        out.append(_note_html(n, book.site))
        toc.append((2, f"n-{n.id}", n.title or "Note"))
    out.append("</div></section>")
    return "\n".join(out), toc


def _timeline(book: Book) -> tuple[str, list]:
    """Every review, newest first, by month: the subject, summary and its
    notes' headlines; each links to the review's page."""
    if not book.reviews:
        return ('<div class="empty-state"><div class="big">No reviews yet</div><p>In kigit, pick a commit, press '
                '<b>Review</b>, write why it changed, then <b>Write</b>.</p></div>', [])
    out, toc, month = ['<div class="timeline">'], [], None
    for r, _ in book.reviews:
        m = r.date[:7]
        if m != month:
            month = m
            label = _month(m)
            out.append(f'<h2 class="month" id="m-{esc(m)}">{esc(label)}</h2>')
            toc.append((2, f"m-{m}", label))
        to = book.href(f"reviews/{r.id}")
        notes = "".join(
            f'<li><a href="{to}#n-{esc(n.id)}">{esc(n.title) or "Note"}</a>{_anchor_html(n)}'
            f'{"".join(_tag(t) for t in n.tags)}</li>' for n in r.notes)
        out.append(f'<section class="review" id="r-{esc(r.id)}">{_when(r.date)}<div class="rbody">'
                   f'<h3 class="rtitle"><a href="{to}">{esc(r.subject) or "(no message)"}</a></h3>{_chips(r)}'
                   + (f'<div class="md summary">{book.site.md(r.summary)}</div>' if r.summary.strip() else "")
                   + (f'<ul class="nlist">{notes}</ul>' if notes else "")
                   + ('<p class="empty">Nothing written in this review.</p>'
                      if not r.summary.strip() and not r.notes else "")
                   + "</div></section>")
    out.append("</div>")
    return "\n".join(out), toc


def _month(m: str) -> str:
    try:
        return datetime.strptime(m, "%Y-%m").strftime("%B %Y")
    except ValueError:
        return m or "Undated"


def _thread_page(book: Book, t) -> str:
    from . import threads

    label, cls = _THREAD_LOOK[t.status]
    about = ""
    if t.anchors:
        about = "".join(_one_anchor(a) for a in t.anchors)
    msgs = []
    for m in t.messages:
        verb = threads.VERB.get(m.kind, "")
        head = f' <span class="dot">·</span> at <code>{esc(m.head[:7])}</code>' if m.head else ""
        if m.edited:
            head += f' <span class="dot">·</span><i title="Edited {esc(m.edited)}">edited</i>'
        msgs.append(f'<div class="msg{" ev" if verb else ""}"><div class="mh"><b>{esc(m.author)}</b>'
                    f'{" " + esc(verb) if verb else ""}<span class="dot">·</span>{esc(m.time)}{head}</div>'
                    + (f'<div class="md">{book.site.md(m.text)}</div>' if m.text.strip() else "") + "</div>")
    return (f'<section class="doc thread" id="t-{esc(t.id)}">'
            f'<div class="crumb"><span class="tstatus {cls}">{label}</span><span class="dot">·</span>opened by '
            f'{esc(t.by)} on <code>{esc(t.commit[:7])}</code><span class="dot">·</span>{esc(t.opened)}</div>'
            f'<h1 class="title">{esc(t.title)}</h1>'
            + (f'<div class="noterow">{about}</div>' if about else "")
            + f'<div class="msgs">{"".join(msgs)}</div></section>')


def _doc_page(book: Book, d: Doc) -> tuple[str, list]:
    rel = d.path.relative_to(book.root).as_posix()
    props = [(k, v) for k, v in d.props.items() if k not in ("title", "tags")]
    rows = "".join(f"<tr><th>{esc(k)}</th><td>{book.site.inline(', '.join(v) if isinstance(v, list) else v)}</td></tr>"
                   for k, v in props)
    tags = "".join(f'<a class="tag{" t-" + t if t in _TAG_KINDS else ""}" href="{book.href("tags/" + t)}">{esc(t)}</a>'
                   for t in d.tags)
    body, toc = _with_ids(book.site.md(d.body, d.path.parent, tags=True))
    return (f'<section class="doc page">'
            f'<div class="crumb"><span class="ico">{_ICON_FILE}</span><code>{esc(rel)}</code>'
            f'<span class="dot">·</span>edited {esc(d.edited)}</div>'
            f'<h1 class="title">{esc(d.title)}</h1>'
            + (f'<div class="noterow">{tags}</div>' if tags else "")
            + (f'<table class="props">{rows}</table>' if rows else "")
            + f'<div class="md">{body}</div></section>'), toc


def _card_list(book: Book, pages: list[Page], empty: str = "Nothing here.") -> str:
    if not pages:
        return f'<p class="empty">{esc(empty)}</p>'
    rows = []
    for p in pages:
        tags = "".join(_tag(t) for t in p.tags if p.kind != "thread")
        extra = ""
        if p.kind == "thread":
            label, cls = _THREAD_LOOK[p.obj.status]
            extra = f'<span class="tstatus {cls}">{label}</span>'
        elif p.kind == "review":
            extra = f'<code>{esc(_short(p.obj.commit))}</code>'
        rows.append(f'<a class="card" href="{book.href(p.url)}"><span class="ct">{esc(p.title)}</span>'
                    f'<span class="cm">{extra}<span>{esc(p.date[:16])}</span>{tags}</span></a>')
    return f'<div class="cards">{"".join(rows)}</div>'


def _home(book: Book) -> str:
    note_count = sum(len(r.notes) for r, _ in book.reviews)
    open_talks = [t for t in book.talks if t.status != "accepted"]
    stats = [(len(book.reviews), "review" if len(book.reviews) == 1 else "reviews"),
             (note_count, "note in reviews" if note_count == 1 else "notes in reviews"),
             (len(book.docs), "own note" if len(book.docs) == 1 else "own notes"),
             (len(open_talks), "open discussion" if len(open_talks) == 1 else "open discussions")]
    stat_html = "".join(f'<div class="stat"><b>{n}</b><span>{w}</span></div>' for n, w in stats)
    if book.reviews:
        stat_html += f'<div class="stat"><b>{esc(book.reviews[0][0].date[:10])}</b><span>latest commit</span></div>'
    pages = book.pages.values()
    latest = [p for p in pages if p.kind == "review"][:5]
    talks = [p for p in pages if p.kind == "thread" and p.obj.status != "accepted"][:5]
    edited = sorted((p for p in pages if p.kind == "note"), key=lambda p: p.date, reverse=True)[:5]
    out = [f'<header class="hero"><div class="eyebrow">Design reviews</div><h1>{esc(book.name)}</h1>'
           '<p class="lede">Why the board changed, commit by commit, and the notes behind it.</p>'
           f'<div class="stats">{stat_html}</div></header>']
    if not book.reviews and not book.docs and not book.talks:
        out.append('<div class="empty-state"><div class="big">No reviews yet</div><p>In kigit, pick a commit, press '
                   '<b>Review</b>, write why it changed, then <b>Write</b>. Markdown notes you put in the '
                   '<code>reviews/</code> folder show up here too.</p><p class="empty">Nothing here yet.</p></div>')
    if talks:
        out.append(f'<h2 class="section" id="attention">Open discussions</h2>{_card_list(book, talks)}')
    if latest:
        out.append(f'<h2 class="section" id="latest">Latest reviews <a class="more" href="{book.href("reviews")}">'
                   f'Timeline →</a></h2>{_card_list(book, latest)}')
    if edited:
        out.append(f'<h2 class="section" id="edited">Recently edited notes</h2>{_card_list(book, edited)}')
    return "\n".join(out)


def _folder(book: Book, tab: str) -> str:
    pages = [p for p in book.pages.values() if p.kind == "note" and p.tab == tab]
    groups: dict[str, list[Page]] = {}
    for p in pages:
        groups.setdefault(p.group, []).append(p)
    out = []
    for g in sorted(groups, key=lambda g: (g != "", g.lower())):
        if g:
            out.append(f'<h2 class="section" id="g-{_slug(g)}">{esc(g)}/</h2>')
        out.append(_card_list(book, groups[g]))
    return "\n".join(out) or '<p class="empty">No notes here.</p>'


def _tags_page(book: Book, tag: str | None) -> str:
    pages = [p for p in book.pages.values() if p.kind in ("review", "note")]
    if tag is None:
        counts: dict[str, int] = {}
        for p in pages:
            for t in p.tags:
                counts[t] = counts.get(t, 0) + 1
        return '<div class="tagcloud">' + "".join(
            f'<a class="tag big{" t-" + t if t in _TAG_KINDS else ""}" href="{book.href("tags/" + t)}">{esc(t)}'
            f'<span>{c}</span></a>' for t, c in sorted(counts.items())) + "</div>"
    out = []
    notes = [(r, n) for r, _ in book.reviews for n in r.notes if tag in n.tags]
    if notes:
        out.append('<h2 class="section" id="in-reviews">Notes in reviews</h2><div class="cards">' + "".join(
            f'<a class="card" href="{book.href(f"reviews/{r.id}", f"n-{n.id}")}"><span class="ct">'
            f'{esc(n.title) or "Note"}</span><span class="cm"><code>{esc(_short(r.commit))}</code>'
            f'<span>{esc(review.one_line(r.subject)[:70])}</span></span></a>' for r, n in notes) + "</div>")
    docs = [p for p in pages if p.kind == "note" and tag in p.tags]
    if docs:
        out.append(f'<h2 class="section" id="notes">Notes</h2>{_card_list(book, docs)}')
    return "\n".join(out) or '<p class="empty">Nothing has this tag.</p>'


# ------------------------------------------------------------------ layout
def _sidebar(book: Book, cur: Page) -> str:
    """The current tab's pages."""
    def link(p: Page, label: str = "", meta: str = "") -> str:
        on = " cur" if p.url == cur.url else ""
        return (f'<a class="nl{on}" href="{book.href(p.url)}"><span class="s">{esc(label or p.title)}</span>'
                + (f'<span class="m">{meta}</span>' if meta else "") + "</a>")
    pages = [p for p in book.pages.values() if p.tab == cur.tab]
    out = []
    if cur.tab == "home":
        for t in book.tabs[1:]:
            n = sum(1 for p in book.pages.values() if p.tab == t.key and p.kind in ("review", "thread", "note", "tag"))
            p = book.pages.get(t.url)
            if p:
                on = " cur" if p.url == cur.url else ""
                out.append(f'<a class="nl row{on}" href="{book.href(p.url)}"><span class="s">{esc(t.label)}</span>'
                           + (f'<span class="n">{n}</span>' if n else "") + "</a>")
    elif cur.tab == "reviews":
        out.append(link(book.pages["reviews"], "Timeline"))
        group = None
        for p in pages:
            if p.kind != "review":
                continue
            if p.group != group:
                group = p.group
                out.append(f'<div class="group">{esc(_month(group))}</div>')
            out.append(link(p, meta=f'<code>{esc(_short(p.obj.commit))}</code>{esc(p.date[:10])}'))
    elif cur.tab == "discussions":
        out.append(link(book.pages["discussions"], "All discussions"))
        group = None
        for p in pages:
            if p.kind != "thread":
                continue
            if p.group != group:
                group = p.group
                out.append(f'<div class="group">{esc(group)}</div>')
            out.append(link(p))
    elif cur.tab == "tags":
        out.append(link(book.pages["tags"], "All tags"))
        out += [link(p) for p in pages if p.kind == "tag"]
    else:
        index = next((p for p in pages if p.kind == "folder"), None)
        if index:
            out.append(link(index, "Overview"))
        groups: dict[str, list[Page]] = {}
        for p in pages:
            if p.kind == "note":
                groups.setdefault(p.group, []).append(p)
        for g in sorted(groups, key=lambda g: (g != "", g.lower())):
            if g:
                out.append(f'<div class="group">{esc(g.split("/", 1)[-1] if "/" in g else g)}/</div>')
            out += [link(p) for p in groups[g]]
    return "\n".join(out)


def _toc_html(toc: list) -> str:
    if not toc:
        return ""
    items = "".join(f'<a class="l{lvl}" href="#{esc(i)}">{esc(t)}</a>' for lvl, i, t in toc)
    return f'<div class="toc-title">On this page</div><nav class="toc-list">{items}</nav>'


def _crumbs(book: Book, p: Page) -> str:
    tab = next((t for t in book.tabs if t.key == p.tab), None)
    parts = [f'<a href="{book.href("")}">Home</a>']
    if tab and tab.key != "home":
        parts.append(f'<a href="{book.href(tab.url)}">{esc(tab.label)}</a>')
    if p.kind in ("review", "thread", "note", "tag") and p.group and p.kind == "note":
        parts.append(f'<span>{esc(p.group)}</span>')
    return '<nav class="crumbs">' + '<span class="sep">/</span>'.join(parts) + "</nav>"


def _prev_next(book: Book, p: Page) -> str:
    """Newer / older review, or the neighbours in the sidebar."""
    same = [q for q in book.pages.values() if q.tab == p.tab and q.kind == p.kind]
    if p.kind not in ("review", "thread", "note") or len(same) < 2:
        return ""
    i = same.index(p)
    before, after = ("Newer", "Older") if p.kind == "review" else ("Previous", "Next")
    out = []
    if i > 0:
        q = same[i - 1]
        out.append(f'<a class="pn prev" href="{book.href(q.url)}"><small>← {before}</small>{esc(q.title)}</a>')
    else:
        out.append("<span></span>")
    if i + 1 < len(same):
        q = same[i + 1]
        out.append(f'<a class="pn next" href="{book.href(q.url)}"><small>{after} →</small>{esc(q.title)}</a>')
    return f'<nav class="prevnext">{"".join(out)}</nav>'


def render(project_dir: str | Path, page: str = "", name: str = "", files_url: str = "", base: str = "/") -> str | None:
    """One page of the site (its address relative to base), or None if
    there's no such page. files_url: where files in reviews/ are served."""
    book = build(project_dir, name, files_url, base)
    p = book.pages.get(page) or book.pages.get(page.rstrip("/") + "/") or book.pages.get(page.rstrip("/"))
    if p is None:
        return None
    toc: list = []
    if p.kind == "home":
        body = _home(book)
        toc = [(2, i, t) for i, t in (("attention", "Open discussions"), ("latest", "Latest reviews"),
                                      ("edited", "Recently edited notes")) if f'id="{i}"' in body]
    elif p.kind == "timeline":
        body, toc = _timeline(book)
        body = '<h1 class="title">Timeline</h1><p class="lede">Every review, newest commit first.</p>' + body
    elif p.kind == "review":
        body, toc = _review_page(book, p.obj)
    elif p.kind == "discussions":
        groups = []
        for status in ("open", "done", "accepted"):
            items = [q for q in book.pages.values() if q.kind == "thread" and q.obj.status == status]
            if items:
                groups.append(f'<h2 class="section" id="s-{status}">{_THREAD_LOOK[status][0]}</h2>'
                              f'{_card_list(book, items)}')
                toc.append((2, f"s-{status}", _THREAD_LOOK[status][0]))
        body = '<h1 class="title">Discussions</h1>' + "".join(groups)
    elif p.kind == "thread":
        body = _thread_page(book, p.obj)
    elif p.kind == "folder":
        body = f'<h1 class="title">{esc(p.title)}</h1>' + _folder(book, p.tab)
    elif p.kind == "note":
        body, toc = _doc_page(book, p.obj)
    elif p.kind == "tags":
        body = '<h1 class="title">Tags</h1>' + _tags_page(book, None)
    else:
        body = f'<h1 class="title">#{esc(p.tags[0])}</h1>' + _tags_page(book, p.tags[0])
    tabs = "".join(f'<a class="tabl{" cur" if t.key == p.tab else ""}" href="{book.href(t.url)}">{esc(t.label)}</a>'
                   for t in book.tabs)
    counts = f"{_plural(len(book.docs), 'note')} · {_plural(len(book.reviews), 'review')}"
    title = book.name if p.kind == "home" else f"{p.title} · {book.name}"
    made = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = _PAGE
    for key, value in (("TITLE", esc(title)), ("NAME", esc(book.name)), ("COUNT", counts), ("MADE", made),
                       ("HOME", book.href("")), ("TABS", tabs), ("SIDE", _sidebar(book, p)),
                       ("CRUMBS", _crumbs(book, p) if p.kind != "home" else ""), ("BODY", body),
                       ("PREVNEXT", _prev_next(book, p)), ("TOC", _toc_html(toc)), ("LOGO", _LOGO),
                       ("SEARCH", book.href("search.json")), ("BASE", book.base), ("KIND", p.kind)):
        out = out.replace(f"%%{key}%%", value)
    return out


# ------------------------------------------------------------------ routes
def _project(key: str) -> Path | None:
    from .review_panel import _projects  # project folders the GUI has handed out keys for
    return _projects.get(key)


@app.get("/reviews-doc/{key}/files/{path:path}")
async def _file(key: str, path: str) -> Response:
    """A file in the project's reviews/ folder, for links on the pages."""
    project = _project(key)
    if project is None:
        return Response(status_code=404)
    found = Site(review.folder(project)).inside(review.folder(project) / path)
    if not found or not found.is_file():
        return Response(status_code=404)
    shown = review.SHOWN_TYPES.get(found.suffix.lower().lstrip(".")) or _MIME.get(found.suffix.lower())
    if shown and shown != "image/svg+xml":
        return FileResponse(found, media_type=shown)
    return FileResponse(found, media_type="application/octet-stream", filename=found.name)  # never run as a page


@app.get("/reviews-doc/{key}/search.json")
async def _search(key: str) -> Response:
    project = _project(key)
    if project is None:
        return Response(status_code=404)
    return JSONResponse(search_index(build(project, files_url=f"/reviews-doc/{key}/files/",
                                           base=f"/reviews-doc/{key}/")))


@app.get("/reviews-doc/{key}")
async def _doc(key: str) -> Response:
    return await _doc_page_route(key, "")


@app.get("/reviews-doc/{key}/{page:path}")
async def _doc_page_route(key: str, page: str) -> Response:
    project = _project(key)
    if project is None:
        return Response("Unknown project: open it in kigit first.", status_code=404)
    out = render(project, page, files_url=f"/reviews-doc/{key}/files/", base=f"/reviews-doc/{key}/")
    if out is None:
        return HTMLResponse(f'<p>No page {esc(page)}. <a href="/reviews-doc/{esc(key)}/">Home</a></p>',
                            status_code=404)
    return HTMLResponse(out)



_ICON_FILE = ('<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path fill="currentColor" '
              'd="M4 1h5l4 4v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1zm4.5 1.5V6H12zM5 8h6v1H5zm0 2.5h6v1H5z"/>'
              '</svg>')
_LOGO = ('<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><rect x="2" y="2" width="20" height="20" '
         'rx="5" fill="var(--accent)"/><path d="M7 7v10M7 12l5-5M7 12l5 5M15 7v10" stroke="var(--on-accent)" '
         'stroke-width="2" stroke-linecap="round" fill="none"/></svg>')

# Placeholders are %%NAME%%; the rest is plain CSS and JavaScript.
_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="kigit">
<title>%%TITLE%%</title>
<script>
  // The theme chosen with the button, before the page draws (no flash).
  try { const t = localStorage.getItem("kigit.docTheme"); if (t) document.documentElement.dataset.theme = t; } catch {}
</script>
<style>
:root {
  --bg: #0e1014; --side: #12151a; --card: #171b21; --card2: #1c2129; --line: #262c35; --line2: #323a45;
  --text: #e7eaef; --muted: #a0a9b6; --faint: #6c7684; --accent: #e8b84d; --accent-soft: rgba(232,184,77,.12);
  --on-accent: #1a1405; --link: #86b9ff; --removed: #f07178; --code-bg: #0a0c0f; --shadow: 0 1px 2px rgba(0,0,0,.3);
  --pcb: #5fc48a; --sch: #79a8ff; --head: #12151a;
  --t-reason: #79a8ff; --t-todo: #e8b84d; --t-question: #c39bff; --t-risk: #f07178;
  color-scheme: dark;
}
:root[data-theme="light"] {
  --bg: #fbfaf8; --side: #f4f3f0; --card: #ffffff; --card2: #f7f6f3; --line: #e6e3de; --line2: #d6d2cb;
  --text: #1c2026; --muted: #59616c; --faint: #8b929b; --accent: #b07a0c; --accent-soft: rgba(176,122,12,.10);
  --on-accent: #ffffff; --link: #1d5fc2; --removed: #c4314b; --code-bg: #f3f1ed; --shadow: 0 1px 2px rgba(0,0,0,.06);
  --pcb: #1f8a4c; --sch: #2f63c9; --head: #ffffff;
  --t-reason: #2f63c9; --t-todo: #a06e05; --t-question: #7a4bd1; --t-risk: #c4314b;
  color-scheme: light;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #fbfaf8; --side: #f4f3f0; --card: #ffffff; --card2: #f7f6f3; --line: #e6e3de; --line2: #d6d2cb;
    --text: #1c2026; --muted: #59616c; --faint: #8b929b; --accent: #b07a0c; --accent-soft: rgba(176,122,12,.10);
    --on-accent: #ffffff; --link: #1d5fc2; --removed: #c4314b; --code-bg: #f3f1ed; --shadow: 0 1px 2px rgba(0,0,0,.06);
    --pcb: #1f8a4c; --sch: #2f63c9; --head: #ffffff;
    --t-reason: #2f63c9; --t-todo: #a06e05; --t-question: #7a4bd1; --t-risk: #c4314b;
    color-scheme: light;
  }
}
* { box-sizing: border-box; }
html { scroll-padding-top: 120px; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15.5px/1.65 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  -webkit-font-smoothing: antialiased; }
code, kbd, pre, .id { font-family: ui-monospace, "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace; }
a { color: var(--link); text-underline-offset: 2px; text-decoration-thickness: 1px; }

/* ----------------------------------------------------------------- header */
.top { position: sticky; top: 0; z-index: 20; background: var(--head); border-bottom: 1px solid var(--line); }
.bar { display: flex; align-items: center; gap: 16px; padding: 10px 24px; max-width: 1500px; margin: 0 auto; }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 700; text-decoration: none; color: var(--text);
  white-space: nowrap; min-width: 0; }
.brand small { color: var(--faint); font-weight: 500; }
.brand .proj { font-weight: 650; overflow: hidden; text-overflow: ellipsis; }
.search { position: relative; margin-left: auto; width: min(460px, 46vw); }
.search svg { position: absolute; left: 11px; top: 50%; transform: translateY(-50%); color: var(--faint); }
.search input { width: 100%; padding: 8px 40px 8px 34px; border-radius: 9px; border: 1px solid var(--line2);
  background: var(--card); color: var(--text); font: inherit; font-size: 14px; outline: none; }
.search input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.search kbd { position: absolute; right: 9px; top: 50%; transform: translateY(-50%); font-size: 11px; color: var(--faint);
  border: 1px solid var(--line2); border-radius: 4px; padding: 0 5px; background: var(--side); }
#results { position: absolute; top: calc(100% + 6px); left: 0; right: 0; max-height: min(70vh, 560px); overflow: auto;
  background: var(--card); border: 1px solid var(--line2); border-radius: 10px; box-shadow: 0 12px 32px rgba(0,0,0,.35);
  display: none; padding: 6px; }
#results.open { display: block; }
#results a { display: block; padding: 8px 10px; border-radius: 8px; text-decoration: none; color: var(--text); }
#results a.sel, #results a:hover { background: var(--accent-soft); }
#results .rt { font-weight: 600; font-size: 14px; }
#results .rk { color: var(--faint); font-size: 12px; margin-left: 6px; font-weight: 400; }
#results .rx { color: var(--muted); font-size: 12.5px; line-height: 1.45; margin-top: 2px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
#results mark { background: var(--accent-soft); color: var(--accent); border-radius: 3px; padding: 0 1px; }
#results .none { color: var(--muted); padding: 10px; font-size: 13.5px; }
.iconbtn { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line2); background: var(--card);
  color: var(--muted); border-radius: 8px; padding: 5px 10px; font: inherit; font-size: 12.5px; cursor: pointer;
  white-space: nowrap; }
.iconbtn:hover { color: var(--text); }
.tabs { display: flex; gap: 2px; padding: 0 16px; max-width: 1500px; margin: 0 auto; overflow-x: auto; }
.tabl { padding: 8px 12px 9px; color: var(--muted); text-decoration: none; font-size: 14px; white-space: nowrap;
  border-bottom: 2px solid transparent; }
.tabl:hover { color: var(--text); }
.tabl.cur { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }

/* ----------------------------------------------------------------- layout */
.layout { display: grid; grid-template-columns: 270px minmax(0, 1fr) 220px; gap: 0; max-width: 1500px; margin: 0 auto; }
.side, .toc { position: sticky; top: 98px; align-self: start; max-height: calc(100vh - 98px); overflow: auto;
  padding: 22px 12px 40px; }
.side .group { font-size: 11px; font-weight: 650; letter-spacing: .08em; text-transform: uppercase; color: var(--faint);
  margin: 16px 10px 6px; }
.nl { display: block; padding: 6px 10px; border-radius: 8px; text-decoration: none; color: var(--text);
  font-size: 13.5px; line-height: 1.4; border-left: 2px solid transparent; }
.nl:hover { background: var(--card2); }
.nl.cur { background: var(--accent-soft); border-left-color: var(--accent); font-weight: 600; }
.nl .s { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.nl .m { display: flex; gap: 8px; align-items: center; color: var(--faint); font-size: 12px; margin-top: 1px; font-weight: 400; }
.nl .m code { color: var(--muted); font-size: 11.5px; }
.nl.row { display: flex; align-items: center; gap: 8px; }
.nl .n { margin-left: auto; background: var(--card2); border-radius: 999px; padding: 0 7px; font-size: 11px; }
.toc-title { font-size: 11px; font-weight: 650; letter-spacing: .08em; text-transform: uppercase; color: var(--faint);
  margin: 0 8px 8px; }
.toc-list a { display: block; padding: 3px 8px; color: var(--muted); text-decoration: none; font-size: 13px;
  border-left: 2px solid var(--line); line-height: 1.4; }
.toc-list a.l3 { padding-left: 20px; }
.toc-list a:hover { color: var(--text); }
.toc-list a.cur { color: var(--accent); border-left-color: var(--accent); }
main { padding: 26px 40px 96px; min-width: 0; }
.crumbs { color: var(--faint); font-size: 13px; margin-bottom: 14px; }
.crumbs a { color: var(--muted); text-decoration: none; } .crumbs a:hover { color: var(--text); }
.crumbs .sep { margin: 0 7px; }
h1.title { font-size: 30px; line-height: 1.2; margin: 0 0 10px; letter-spacing: -.01em; }
.lede { color: var(--muted); margin: 0 0 22px; }
.hero { padding-bottom: 22px; margin-bottom: 26px; border-bottom: 1px solid var(--line); }
.eyebrow { color: var(--accent); font-size: 12px; font-weight: 650; letter-spacing: .1em; text-transform: uppercase; }
.hero h1 { font-size: 34px; line-height: 1.15; margin: 6px 0 6px; letter-spacing: -.01em; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.stat { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px;
  box-shadow: var(--shadow); }
.stat b { display: block; font-size: 20px; font-weight: 650; font-variant-numeric: tabular-nums; }
.stat span { color: var(--muted); font-size: 12.5px; }
h2.section { display: flex; align-items: baseline; gap: 12px; font-size: 13px; font-weight: 650; letter-spacing: .08em;
  text-transform: uppercase; color: var(--muted); margin: 28px 0 12px; }
h2.section .more { margin-left: auto; text-transform: none; letter-spacing: 0; font-weight: 500; font-size: 13px; }
.cards { display: grid; gap: 8px; }
.card { display: block; background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px;
  text-decoration: none; color: var(--text); box-shadow: var(--shadow); }
.card:hover { border-color: var(--line2); background: var(--card2); }
.card .ct { display: block; font-weight: 600; }
.card .cm { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; color: var(--faint); font-size: 12.5px; margin-top: 2px; }
.card .cm code { color: var(--muted); }
.hash { color: var(--faint); text-decoration: none; margin-left: -1.15em; width: 1.15em; display: inline-block;
  font-weight: 400; opacity: 0; transition: opacity .15s; }
h3:hover .hash, .hash:focus { opacity: 1; }
.prevnext { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 40px; }
.pn { display: block; border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; text-decoration: none;
  color: var(--text); font-weight: 600; font-size: 14px; }
.pn small { display: block; color: var(--faint); font-weight: 500; font-size: 12px; }
.pn.next { text-align: right; } .pn:hover { border-color: var(--accent); }
.foot { color: var(--faint); font-size: 12px; margin-top: 30px; padding-top: 16px; border-top: 1px solid var(--line); }

/* Notes of your own, discussions */
.doc .crumb { display: flex; align-items: center; gap: 6px; color: var(--faint); font-size: 12.5px; margin-bottom: 6px; }
.crumb code { color: var(--muted); font-size: 12px; }
.crumb .ico { display: inline-flex; }
.dot { margin: 0 2px; color: var(--faint); }
.props { border-collapse: collapse; font-size: 13.5px; margin: 10px 0 16px; width: auto; }
.props th { text-align: left; color: var(--muted); font-weight: 500; padding: 3px 18px 3px 0; vertical-align: top;
  white-space: nowrap; }
.props td { padding: 3px 0; } .props td p { margin: 0; }
.tstatus { border-radius: 999px; padding: 0 9px; font-size: 12px; border: 1px solid currentColor; }
.tstatus.t-risk { color: var(--t-risk); } .tstatus.t-todo { color: var(--t-todo); } .tstatus.t-ok { color: #5fc48a; }
.msgs { margin-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.msg { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; }
.msg.ev { border-left: 3px solid var(--accent); }
.msg .mh { font-size: 12.5px; color: var(--muted); } .msg .mh b { color: var(--text); }
.itag { color: var(--accent); background: var(--accent-soft); border-radius: 4px; padding: 0 4px; font-size: .92em; }

/* Reviews: the timeline, newest first */
.timeline { position: relative; }
h2.month { font-size: 13px; font-weight: 650; letter-spacing: .08em; text-transform: uppercase; color: var(--muted);
  margin: 6px 0 16px 126px; }
.review { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 0 30px; position: relative; padding-bottom: 34px; }
.timeline .review::before { content: ""; position: absolute; left: 115px; top: 8px; bottom: 0; width: 2px; background: var(--line); }
.timeline .review::after { content: ""; position: absolute; left: 110px; top: 6px; width: 8px; height: 8px; border-radius: 50%;
  background: var(--bg); border: 2px solid var(--accent); }
.review.single { grid-template-columns: 96px minmax(0, 1fr); }
.when { text-align: right; padding-top: 3px; color: var(--muted); font-size: 13px; line-height: 1.3; }
.when time { display: block; color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
.when span { color: var(--faint); font-size: 12px; }
.rbody { min-width: 0; padding-left: 12px; }
.rtitle { margin: 0 0 6px; font-size: 19px; line-height: 1.3; }
.rtitle a { color: var(--text); text-decoration: none; } .rtitle a:hover { color: var(--accent); }
.meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 6px; }
.chip { display: inline-flex; align-items: center; gap: 6px; background: var(--card); border: 1px solid var(--line);
  border-radius: 999px; padding: 1px 10px; font-size: 12.5px; color: var(--muted); }
.chip code { font-size: 12px; color: var(--text); }
.chip .arrow { color: var(--faint); }
.chip.id { color: var(--accent); font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }
.av { display: inline-grid; place-items: center; width: 17px; height: 17px; margin-left: -6px; border-radius: 50%;
  background: var(--accent-soft); color: var(--accent); font-size: 10.5px; font-weight: 700; }
.written { color: var(--faint); font-size: 12px; margin-bottom: 12px; }
.summary { font-size: 15.5px; }
.nlist { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 4px; }
.nlist li { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 13.5px; }
.nlist li > a { font-weight: 600; text-decoration: none; color: var(--text); }
.nlist li > a:hover { color: var(--accent); }
.nlist li::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--line2); }
.note { position: relative; background: var(--card); border: 1px solid var(--line); border-left: 3px solid var(--line2);
  border-radius: 10px; padding: 14px 18px 12px; margin: 14px 0; box-shadow: var(--shadow); }
.note:target { box-shadow: 0 0 0 2px var(--accent); }
.note.t-reason { border-left-color: var(--t-reason); } .note.t-todo { border-left-color: var(--t-todo); }
.note.t-question { border-left-color: var(--t-question); } .note.t-risk { border-left-color: var(--t-risk); }
.nhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 12px; margin-bottom: 4px; }
.note h3 { margin: 0; font-size: 16.5px; line-height: 1.35; }
.noterow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12px; margin-bottom: 6px; }
.anchor { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line2); border-radius: 6px;
  padding: 0 8px 0 0; color: var(--text); overflow: hidden; font-size: 12px; }
.anchor .tab { padding: 0 6px; font-size: 10.5px; letter-spacing: .04em; color: #fff; align-self: stretch;
  display: inline-flex; align-items: center; }
.tab-pcb { background: var(--pcb); } .tab-sch { background: var(--sch); }
.anchor.removed { border-color: var(--removed); color: var(--removed); }
.anchor.removed .tab { background: var(--removed); }
.anchor.general { color: var(--muted); padding: 0 8px; border-style: dashed; }
.tag { border-radius: 999px; padding: 0 9px; background: var(--card2); color: var(--muted); border: 1px solid var(--line);
  font-size: 12px; text-decoration: none; }
.tag.t-reason { color: var(--t-reason); border-color: currentColor; }
.tag.t-todo { color: var(--t-todo); border-color: currentColor; }
.tag.t-question { color: var(--t-question); border-color: currentColor; }
.tag.t-risk { color: var(--t-risk); border-color: currentColor; }
.tagcloud { display: flex; flex-wrap: wrap; gap: 8px; }
.tag.big { font-size: 14px; padding: 3px 12px; display: inline-flex; gap: 8px; align-items: center; }
.tag.big span { color: var(--faint); font-size: 12px; }
.times { color: var(--faint); font-size: 11.5px; margin-top: 8px; }

/* Markdown */
.md > :first-child { margin-top: 0; } .md > :last-child { margin-bottom: 0; }
.md p { margin: .55em 0; }
.md h1, .md h2, .md h3, .md h4 { line-height: 1.3; margin: 1.3em 0 .45em; }
.md h1 { font-size: 1.45em; } .md h2 { font-size: 1.25em; } .md h3 { font-size: 1.08em; } .md h4 { font-size: 1em; }
.md ul, .md ol { padding-left: 1.4em; margin: .5em 0; } .md li { margin: .15em 0; }
.md li:has(> input[type=checkbox]) { list-style: none; margin-left: -1.3em; }
.md input[type=checkbox] { accent-color: var(--accent); margin-right: 6px; }
.md img { max-width: 100%; height: auto; border-radius: 8px; border: 1px solid var(--line); display: block; margin: .7em 0; }
.md :not(pre) > code { background: var(--card2); border: 1px solid var(--line); border-radius: 5px; padding: .05em .35em;
  font-size: .86em; }
.md pre { background: var(--code-bg); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; overflow: auto;
  font-size: 13px; line-height: 1.5; }
.md blockquote { margin: .8em 0; padding: .3em 1em; border-left: 3px solid var(--accent); background: var(--accent-soft);
  border-radius: 0 8px 8px 0; color: var(--text); }
.md blockquote p { margin: .3em 0; }
.md table { border-collapse: collapse; margin: .8em 0; font-size: 14px; display: block; overflow-x: auto; max-width: 100%; }
.md th { text-align: left; background: var(--card2); font-weight: 600; }
.md td, .md th { border: 1px solid var(--line); padding: 5px 11px; }
.md hr { border: 0; border-top: 1px solid var(--line); margin: 1.4em 0; }
.md a { overflow-wrap: anywhere; }
math { font-size: 1.1em; }
math[display=block] { margin: .8em 0; overflow-x: auto; overflow-y: hidden; }
.math-error { color: var(--removed); border-bottom: 1px dotted var(--removed); cursor: help; }
.wl { text-decoration: none; border-bottom: 1px dashed var(--link); }
.wl:hover { border-bottom-style: solid; }
.wl.missing { color: var(--muted); border-bottom-color: var(--faint); cursor: help; }
.md a[href*="/discussions/"]::before { content: "💬"; margin-right: 3px; font-size: .9em; }
a[target=_blank]::after { content: "↗"; font-size: .75em; margin-left: 2px; color: var(--faint); }
.empty { color: var(--muted); font-style: italic; }
.empty-state { text-align: center; padding: 50px 20px; border: 1px dashed var(--line2); border-radius: 12px; color: var(--muted); }
.empty-state .big { font-size: 20px; font-weight: 650; color: var(--text); margin-bottom: 6px; }
#menu { display: none; }

@media (max-width: 1180px) {
  .layout { grid-template-columns: 250px minmax(0, 1fr); }
  .toc { display: none; }
}
@media (max-width: 820px) {
  .bar { padding: 8px 12px; gap: 10px; flex-wrap: wrap; }
  .search { order: 3; width: 100%; margin-left: 0; }
  #menu { display: inline-flex; }
  .layout { display: block; }
  .side { display: none; position: static; max-height: none; border-bottom: 1px solid var(--line); }
  body.menu .side { display: block; }
  main { padding: 20px 16px 72px; }
  .review, .review.single { grid-template-columns: 1fr; padding-left: 0; }
  .timeline .review { padding-left: 20px; }
  .timeline .review::before { left: 4px; } .timeline .review::after { left: -1px; }
  h2.month { margin-left: 20px; }
  .when { text-align: left; display: flex; gap: 8px; align-items: baseline; margin-bottom: 4px; }
  .when time { display: inline; }
  .rbody { padding-left: 0; }
  .hash { display: none; }
}
@media print {
  :root { --bg: #fff; --card: #fff; --card2: #f6f6f6; --text: #000; --muted: #444; --faint: #777; --line: #ddd;
    --line2: #ccc; --shadow: none; color-scheme: light; }
  .top, .side, .toc, .prevnext { display: none !important; }
  .layout { display: block; } main { padding: 0; }
  .note, .stat, .card { break-inside: avoid; }
  a[target=_blank]::after { content: ""; }
}
</style>
</head>
<body data-kind="%%KIND%%">
<header class="top">
  <div class="bar">
    <button class="iconbtn" id="menu" type="button" aria-label="Pages">☰</button>
    <a class="brand" href="%%HOME%%">%%LOGO%% <span>kigit <small>reviews</small></span><span class="dot">·</span><span class="proj">%%NAME%%</span></a>
    <div class="search">
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M7 2a5 5 0 0 1 3.9 8.1l3 3-.8.8-3-3A5 5 0 1 1 7 2zm0 1.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z"/></svg>
      <input id="q" type="search" placeholder="Search reviews, notes and discussions" aria-label="Search" autocomplete="off">
      <kbd>/</kbd>
      <div id="results" role="listbox"></div>
    </div>
    <button class="iconbtn" id="theme" type="button" title="Switch between light and dark">Theme</button>
  </div>
  <nav class="tabs" aria-label="Sections">%%TABS%%</nav>
</header>
<div class="layout">
  <aside class="side" aria-label="Pages in this section">%%SIDE%%</aside>
  <main>
    %%CRUMBS%%
    %%BODY%%
    %%PREVNEXT%%
    <p class="foot">%%COUNT%% · built by kigit from reviews/ on %%MADE%%.</p>
  </main>
  <aside class="toc">%%TOC%%</aside>
</div>
<script>
(() => {
  // ---------------------------------------------------------------- search
  // The index is every page and every note in a review (search.json),
  // fetched the first time the box is used. Words must all appear; title
  // hits rank first.
  const q = document.getElementById("q"), box = document.getElementById("results");
  let index = null, sel = 0, shown = [];
  const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const mark = (text, words) => {
    let out = esc(text);
    for (const w of words) out = out.replace(new RegExp("(" + w.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&") + ")", "ig"), "<mark>$1</mark>");
    return out;
  };
  async function load() {
    if (index) return index;
    try { index = await (await fetch("%%SEARCH%%")).json(); } catch { index = []; }
    return index;
  }
  function snippet(text, words) {
    const low = text.toLowerCase();
    const at = Math.max(0, Math.min(...words.map((w) => { const i = low.indexOf(w); return i < 0 ? 1e9 : i; })));
    const start = at > 60 && at < 1e9 ? at - 60 : 0;
    return (start ? "…" : "") + text.slice(start, start + 220);
  }
  async function run() {
    const words = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
    if (!words.length) { box.classList.remove("open"); return; }
    const all = await load();
    const scored = [];
    for (const e of all) {
      const title = e.t.toLowerCase(), body = (e.x + " " + e.g.join(" ") + " " + e.k).toLowerCase();
      if (!words.every((w) => title.includes(w) || body.includes(w))) continue;
      const score = words.reduce((s, w) => s + (title.includes(w) ? 10 : 0) + (title.startsWith(w) ? 5 : 0), 0);
      scored.push([score, e]);
    }
    scored.sort((a, b) => b[0] - a[0]);
    shown = scored.slice(0, 30).map((s) => s[1]);
    sel = 0;
    box.innerHTML = shown.length ? shown.map((e, i) =>
      `<a href="${esc(e.u)}" class="${i === 0 ? "sel" : ""}"><span class="rt">${mark(e.t, words)}</span>` +
      `<span class="rk">${esc(e.k)}${e.d ? " · " + esc(e.d) : ""}</span>` +
      `<div class="rx">${mark(snippet(e.x, words), words)}</div></a>`).join("")
      : `<div class="none">Nothing matches “${esc(q.value)}”.</div>`;
    box.classList.add("open");
  }
  q.addEventListener("input", run);
  q.addEventListener("focus", () => { load(); if (q.value) run(); });
  q.addEventListener("keydown", (e) => {
    const items = [...box.querySelectorAll("a")];
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!items.length) return;
      items[sel]?.classList.remove("sel");
      sel = (sel + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      items[sel].classList.add("sel");
      items[sel].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && items[sel]) { e.preventDefault(); location.href = items[sel].href; }
    else if (e.key === "Escape") { q.value = ""; box.classList.remove("open"); q.blur(); }
  });
  document.addEventListener("click", (e) => { if (!e.target.closest(".search")) box.classList.remove("open"); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== q && !e.ctrlKey && !e.metaKey
        && !/^(input|textarea)$/i.test(document.activeElement?.tagName || "")) { e.preventDefault(); q.focus(); }
  });

  // Links leaving the site (web, files) open in a new tab.
  document.querySelectorAll("main a[href]").forEach((a) => {
    const h = a.getAttribute("href");
    if (!h.startsWith("#") && !h.startsWith("%%BASE%%") || h.startsWith("%%BASE%%files/")) {
      a.target = "_blank"; a.rel = "noopener";
    }
  });
  // "On this page": mark the part in view.
  const tocLinks = new Map([...document.querySelectorAll(".toc-list a")].map((a) => [a.getAttribute("href").slice(1), a]));
  if (tocLinks.size) {
    const seen = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (!e.isIntersecting) return;
      tocLinks.forEach((a) => a.classList.remove("cur"));
      tocLinks.get(e.target.id)?.classList.add("cur");
    }), { rootMargin: "-100px 0px -65% 0px" });
    tocLinks.forEach((_, id) => { const el = document.getElementById(id); if (el) seen.observe(el); });
  }
  document.querySelector(".side .cur")?.scrollIntoView({ block: "center" });
  document.getElementById("menu").addEventListener("click", () => document.body.classList.toggle("menu"));
  // Light / dark: follows the system until the button picks one.
  const root = document.documentElement;
  const dark = () => (root.dataset.theme || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark")) === "dark";
  const themeBtn = document.getElementById("theme");
  const label = () => { themeBtn.textContent = dark() ? "☀ Light" : "☾ Dark"; };
  label();
  themeBtn.addEventListener("click", () => {
    root.dataset.theme = dark() ? "light" : "dark";
    try { localStorage.setItem("kigit.docTheme", root.dataset.theme); } catch {}
    label();
  });
})();
</script>
</body>
</html>
"""
