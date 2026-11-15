"""All of a project's reviews and notes as one HTML page, like a docs site.

The GUI's Reviews button opens it in a new tab (`/reviews-doc/{key}`). It's
built from the files in `reviews/` each time it's opened (unwritten drafts
aren't in it):

- Notes: any other Markdown file you put in `reviews/` (or a folder in it),
  e.g. design decisions written in Obsidian. Newest first. Frontmatter is
  shown as properties; `tags:` and #tags work with the tag filter.
- Reviews: kigit's commit reviews, newest commit first.

Links: web addresses (bare ones too) open in a new tab. `[[note]]`,
`[[note|text]]`, `[[review ID]]` and `[text](decisions/x.md)` jump within the
page; links to other files in `reviews/` (`[[datasheet.pdf]]`,
`[x](docs/x.pdf)`) open them. `![[picture.png]]` embeds a picture.
Pictures are embedded, so saving the page from the browser gives one
self-contained file.
"""

from __future__ import annotations

import base64
import html
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse, Response
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
    anchor: str = ""  # its id in the page


@dataclass
class Site:
    """What links and pictures can point at, for one page."""
    root: Path                                         # the reviews/ folder
    names: dict[str, str] = field(default_factory=dict)  # lowercased name -> "#anchor"
    files: dict[str, Path] = field(default_factory=dict)  # lowercased file name -> file (for ![[...]])
    paths: dict[Path, str] = field(default_factory=dict)  # note/review file -> "#anchor"
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
        """A picture inside reviews/ as a data URL, or None."""
        try:
            path = path.resolve()
            path.relative_to(self.root.resolve())  # nothing from outside reviews/
        except (OSError, ValueError):
            return None
        mime = _MIME.get(path.suffix.lower())
        if not mime or not path.is_file():
            return None
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
        if p in reviews or rel == Path(review.INDEX) or rel.parts[0] == review.ASSETS:
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


def _doc_html(d: Doc, site: Site, root: Path) -> str:
    rel = d.path.relative_to(root).as_posix()
    props = [(k, v) for k, v in d.props.items() if k not in ("title", "tags")]
    rows = "".join(f"<tr><th>{esc(k)}</th><td>{site.inline(', '.join(v) if isinstance(v, list) else v)}</td></tr>"
                   for k, v in props)
    tags = "".join(_tag(t) for t in d.tags)
    return (f'<section class="doc" id="{d.anchor}" data-tags="{esc(" ".join(d.tags))}">'
            f'<div class="crumb"><span class="ico">{_ICON_FILE}</span><code>{esc(rel)}</code>'
            f'<span class="dot">·</span>edited {esc(d.edited)}</div>'
            f'<h2><a class="hash" href="#{d.anchor}" title="Link to this note">#</a>{esc(d.title)}</h2>'
            + (f'<div class="noterow">{tags}</div>' if tags else "")
            + (f'<table class="props">{rows}</table>' if rows else "")
            + f'<div class="md">{site.md(d.body, d.path.parent, tags=True)}</div></section>')


def _anchor_html(n: review.Note) -> str:
    if not n.anchor:
        return '<span class="anchor general">General note</span>'
    a = n.anchor
    cls = "anchor removed" if a.removed else "anchor"
    label = a.label + (" · removed" if a.removed else "")
    return (f'<span class="{cls}" title="{esc(a.where)}"><b class="tab tab-{esc(a.tab)}">{esc(a.tab.upper())}</b>'
            f'{esc(label)}</span>')


def _review_html(r: Review, site: Site) -> str:
    rid = esc(r.id)
    day, _, clock = (r.date or "").partition(" ")
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
    chips.append(f'<span class="chip id" title="Review ID: its file name in reviews/">{rid}</span>')
    if r.notes:
        chips.append(f'<span class="chip">{_plural(len(r.notes), "note")}</span>')
    written = f"Review written {esc(r.created)}" + (f" · updated {esc(r.updated)}" if r.updated != r.created else "")
    out = [f'<section class="review" id="r-{rid}">',
           f'<div class="when"><time>{esc(day)}</time><span>{esc(clock)}</span></div>',
           '<div class="rbody">',
           f'<h2><a class="hash" href="#r-{rid}" title="Link to this review">#</a>{esc(r.subject) or "(no message)"}</h2>',
           f'<div class="meta">{"".join(chips)}</div>',
           f'<div class="written">{written}</div>']
    if r.summary.strip():
        out.append(f'<div class="md summary">{site.md(r.summary)}</div>')
    if not r.summary.strip() and not r.notes:
        out.append('<p class="empty">Nothing written in this review.</p>')
    for n in r.notes:
        times = ""
        if n.created:
            times = f"Written {esc(n.created)}" + (f" · edited {esc(n.edited)}" if n.edited else "")
        kind = next((f" t-{t}" for t in n.tags if t in _TAG_KINDS), "")
        out.append(
            f'<article class="note{kind}" id="n-{esc(n.id)}" data-tags="{esc(" ".join(n.tags))}">'
            f'<div class="nhead"><h3>{esc(n.title) or "Note"}</h3>'
            f'<div class="noterow">{_anchor_html(n)}{"".join(_tag(t) for t in n.tags)}</div></div>'
            + (f'<div class="md">{site.md(n.body)}</div>' if n.body.strip() else "")
            + (f'<div class="times">{times}</div>' if times else "")
            + "</article>")
    out.append("</div></section>")
    return "\n".join(out)


def render(project_dir: str | Path, name: str = "", files_url: str = "") -> str:
    """The whole page for the project's notes and written reviews. files_url:
    where links to other files in reviews/ point (the GUI serves them)."""
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
    docs.sort(key=lambda d: d.edited, reverse=True)

    # What [[links]] and ![[embeds]] can reach.
    if root.is_dir():
        for p in sorted(root.rglob("*")):
            if p.is_file():
                site.files.setdefault(p.name.lower(), p)
    taken: set[str] = set()
    for d in docs:
        base = slug = "d-" + _slug(d.path.relative_to(root).with_suffix("").as_posix())
        n = 2
        while slug in taken:  # "a b.md" and "a-b.md"
            slug, n = f"{base}-{n}", n + 1
        d.anchor = slug
        taken.add(slug)
        for key in (d.title, d.path.stem, d.path.relative_to(root).with_suffix("").as_posix()):
            site.names.setdefault(key.lower(), f"#{slug}")
        site.paths[d.path.resolve()] = f"#{slug}"
    for r, p in reviews:
        for key in (r.id, p.stem):
            site.names.setdefault(key.lower(), f"#r-{r.id}")
        site.paths[p.resolve()] = f"#r-{r.id}"
    for r, _ in reviews:  # [[commit subject]] too, after IDs and notes
        if r.subject:
            site.names.setdefault(review.one_line(r.subject).lower(), f"#r-{r.id}")

    counts: dict[str, int] = {}
    for t in [t for r, _ in reviews for n in r.notes for t in n.tags] + [t for d in docs for t in d.tags]:
        counts[t] = counts.get(t, 0) + 1
    nav, body = [], []
    if docs:
        nav.append(f'<div class="group">Notes <span>{len(docs)}</span></div>')
        nav += [f'<a href="#{d.anchor}" data-r="{d.anchor}"><span class="s">{esc(d.title)}</span>'
                f'<span class="m">{esc(d.edited[:10])}</span></a>' for d in docs]
        body.append('<h1 class="group">Notes</h1>')
        body += [_doc_html(d, site, root) for d in docs]
    if reviews:
        nav.append(f'<div class="group">Reviews <span>{len(reviews)}</span></div>')
        nav += [f'<a href="#r-{esc(r.id)}" data-r="r-{esc(r.id)}"><span class="s">{esc(r.subject) or "(no message)"}'
                f'</span><span class="m"><code>{esc(_short(r.commit))}</code>{esc(r.date[:10])}'
                + (f'<span class="n">{len(r.notes)}</span>' if r.notes else "") + "</span></a>"
                for r, _ in reviews]
        body.append('<h1 class="group">Reviews</h1><div class="timeline">')
        body += [_review_html(r, site) for r, _ in reviews]
        body.append("</div>")
    if not body:
        body.append('<div class="empty-state"><div class="big">No reviews yet</div><p>In kigit, pick a commit, '
                    'press <b>Review</b>, write why it changed, then <b>Write</b>. Markdown notes you put in the '
                    '<code>reviews/</code> folder show up here too.</p><p class="empty">Nothing here yet.</p></div>')
    note_count = sum(len(r.notes) for r, _ in reviews)
    count = f"{_plural(len(docs), 'note')} · {_plural(len(reviews), 'review')}"
    stats = [(len(reviews), "reviews" if len(reviews) != 1 else "review"),
             (note_count, "notes in reviews" if note_count != 1 else "note in reviews"),
             (len(docs), "own notes" if len(docs) != 1 else "own note")]
    latest = reviews[0][0].date[:10] if reviews else ""
    stat_html = "".join(f'<div class="stat"><b>{n}</b><span>{w}</span></div>' for n, w in stats)
    if latest:
        stat_html += f'<div class="stat"><b>{esc(latest)}</b><span>latest commit</span></div>'
    tag_buttons = "".join(f'<button class="tagf{" t-" + esc(t) if t in _TAG_KINDS else ""}" data-tag="{esc(t)}">'
                          f'{esc(t)}<span>{c}</span></button>' for t, c in sorted(counts.items()))
    made = datetime.now().strftime("%Y-%m-%d %H:%M")
    page = _PAGE
    for key, value in (("TITLE", esc(f"{name} reviews")), ("NAME", esc(name)), ("COUNT", count), ("MADE", made),
                       ("NAV", "\n".join(nav)), ("BODY", "\n".join(body)), ("TAGS", tag_buttons),
                       ("STATS", stat_html), ("LOGO", _LOGO)):
        page = page.replace(f"%%{key}%%", value)
    return page


@app.get("/reviews-doc/{key}")
async def _doc(key: str) -> Response:
    from .review_panel import _projects  # project folders the GUI has handed out keys for

    project = _projects.get(key)
    if project is None:
        return Response("Unknown project: open it in kigit first.", status_code=404)
    return HTMLResponse(render(project, files_url=f"/reviews-doc/{key}/files/"))


@app.get("/reviews-doc/{key}/files/{path:path}")
async def _file(key: str, path: str) -> Response:
    """A file in the project's reviews/ folder, for links on the page."""
    from .review_panel import _projects

    project = _projects.get(key)
    if project is None:
        return Response(status_code=404)
    found = Site(review.folder(project)).inside(review.folder(project) / path)
    return FileResponse(found) if found and found.is_file() else Response(status_code=404)


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
  --pcb: #5fc48a; --sch: #79a8ff;
  --t-reason: #79a8ff; --t-todo: #e8b84d; --t-question: #c39bff; --t-risk: #f07178;
  color-scheme: dark;
}
:root[data-theme="light"] {
  --bg: #fbfaf8; --side: #f4f3f0; --card: #ffffff; --card2: #f7f6f3; --line: #e6e3de; --line2: #d6d2cb;
  --text: #1c2026; --muted: #59616c; --faint: #8b929b; --accent: #b07a0c; --accent-soft: rgba(176,122,12,.10);
  --on-accent: #ffffff; --link: #1d5fc2; --removed: #c4314b; --code-bg: #f3f1ed; --shadow: 0 1px 2px rgba(0,0,0,.06);
  --pcb: #1f8a4c; --sch: #2f63c9;
  --t-reason: #2f63c9; --t-todo: #a06e05; --t-question: #7a4bd1; --t-risk: #c4314b;
  color-scheme: light;
}
@media (prefers-color-scheme: light) {
  :root:not([data-theme="dark"]) {
    --bg: #fbfaf8; --side: #f4f3f0; --card: #ffffff; --card2: #f7f6f3; --line: #e6e3de; --line2: #d6d2cb;
    --text: #1c2026; --muted: #59616c; --faint: #8b929b; --accent: #b07a0c; --accent-soft: rgba(176,122,12,.10);
    --on-accent: #ffffff; --link: #1d5fc2; --removed: #c4314b; --code-bg: #f3f1ed; --shadow: 0 1px 2px rgba(0,0,0,.06);
    --pcb: #1f8a4c; --sch: #2f63c9;
    --t-reason: #2f63c9; --t-todo: #a06e05; --t-question: #7a4bd1; --t-risk: #c4314b;
    color-scheme: light;
  }
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 16px; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 15.5px/1.65 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  -webkit-font-smoothing: antialiased; }
code, kbd, pre, .id { font-family: ui-monospace, "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace; }
a { color: var(--link); text-underline-offset: 2px; text-decoration-thickness: 1px; }
.layout { display: grid; grid-template-columns: 300px minmax(0, 1fr); min-height: 100vh; }

/* ---------------------------------------------------------------- sidebar */
.side { position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; background: var(--side);
  border-right: 1px solid var(--line); }
.side-top { padding: 18px 16px 10px; }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 700; letter-spacing: .01em; }
.brand small { color: var(--faint); font-weight: 500; }
.proj { font-size: 19px; font-weight: 650; margin: 12px 0 0; overflow-wrap: anywhere; }
.count { color: var(--muted); font-size: 12.5px; margin-bottom: 12px; }
.search { position: relative; display: block; }
.search svg { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--faint); }
.search input { width: 100%; padding: 8px 34px 8px 32px; border-radius: 8px; border: 1px solid var(--line2);
  background: var(--card); color: var(--text); font: inherit; font-size: 13.5px; outline: none; }
.search input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft); }
.search kbd { position: absolute; right: 8px; top: 50%; transform: translateY(-50%); font-size: 11px; color: var(--faint);
  border: 1px solid var(--line2); border-radius: 4px; padding: 0 5px; background: var(--side); }
.tags { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0 2px; }
.tagf { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--line2); background: none;
  color: var(--muted); border-radius: 999px; padding: 1px 4px 1px 9px; font: inherit; font-size: 12px; cursor: pointer; }
.tagf span { background: var(--card2); color: var(--faint); border-radius: 999px; padding: 0 6px; font-size: 11px; }
.tagf:hover { color: var(--text); border-color: var(--faint); }
.tagf.on { color: var(--on-accent); background: var(--accent); border-color: var(--accent); }
.tagf.on span { background: rgba(0,0,0,.18); color: inherit; }
#toc { flex: 1; overflow: auto; padding: 4px 10px 16px; }
#toc .group { display: flex; justify-content: space-between; font-size: 11px; font-weight: 650; letter-spacing: .08em;
  text-transform: uppercase; color: var(--faint); margin: 16px 8px 6px; }
#toc a { display: block; padding: 7px 10px; border-radius: 8px; text-decoration: none; color: var(--text);
  font-size: 13.5px; line-height: 1.4; border-left: 2px solid transparent; }
#toc a:hover { background: var(--card2); }
#toc a.cur { background: var(--accent-soft); border-left-color: var(--accent); }
#toc .s { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
#toc .m { display: flex; gap: 8px; align-items: center; color: var(--faint); font-size: 12px; margin-top: 2px; }
#toc .m code { color: var(--muted); font-size: 11.5px; }
#toc .m .n { margin-left: auto; background: var(--card2); border-radius: 999px; padding: 0 7px; font-size: 11px; }
.side-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 16px;
  border-top: 1px solid var(--line); color: var(--faint); font-size: 12px; }
.iconbtn { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line2); background: var(--card);
  color: var(--muted); border-radius: 8px; padding: 4px 9px; font: inherit; font-size: 12px; cursor: pointer; }
.iconbtn:hover { color: var(--text); }

/* ------------------------------------------------------------------- main */
main { padding: 36px 48px 96px; max-width: 1020px; width: 100%; }
.hero { padding-bottom: 26px; margin-bottom: 30px; border-bottom: 1px solid var(--line); }
.eyebrow { color: var(--accent); font-size: 12px; font-weight: 650; letter-spacing: .1em; text-transform: uppercase; }
.hero h1 { font-size: 34px; line-height: 1.15; margin: 6px 0 6px; letter-spacing: -.01em; }
.lede { color: var(--muted); margin: 0 0 18px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
.stat { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px;
  box-shadow: var(--shadow); }
.stat b { display: block; font-size: 20px; font-weight: 650; font-variant-numeric: tabular-nums; }
.stat span { color: var(--muted); font-size: 12.5px; }
h1.group { display: flex; align-items: center; gap: 12px; font-size: 12px; font-weight: 650; letter-spacing: .1em;
  text-transform: uppercase; color: var(--muted); margin: 8px 0 18px; }
h1.group::after { content: ""; flex: 1; height: 1px; background: var(--line); }
h2 { margin: 0 0 8px; font-size: 23px; line-height: 1.3; letter-spacing: -.005em; }
.hash { color: var(--faint); text-decoration: none; margin-left: -1.15em; width: 1.15em; display: inline-block;
  font-weight: 400; opacity: 0; transition: opacity .15s; }
h2:hover .hash, .hash:focus { opacity: 1; }

/* Your own notes */
.doc { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 20px 26px 16px;
  margin-bottom: 22px; box-shadow: var(--shadow); }
.crumb { display: flex; align-items: center; gap: 6px; color: var(--faint); font-size: 12.5px; margin-bottom: 6px; }
.crumb code { color: var(--muted); font-size: 12px; }
.crumb .ico { display: inline-flex; }
.props { border-collapse: collapse; font-size: 13.5px; margin: 10px 0 12px; width: auto; }
.props th { text-align: left; color: var(--muted); font-weight: 500; padding: 3px 18px 3px 0; vertical-align: top;
  white-space: nowrap; }
.props td { padding: 3px 0; } .props td p { margin: 0; }
.itag { color: var(--accent); background: var(--accent-soft); border-radius: 4px; padding: 0 4px; font-size: .92em; }

/* Reviews: a timeline, newest first */
.timeline { position: relative; }
.review { display: grid; grid-template-columns: 96px minmax(0, 1fr); gap: 0 30px; position: relative;
  padding-bottom: 40px; }
.review::before { content: ""; position: absolute; left: 115px; top: 8px; bottom: 0; width: 2px; background: var(--line); }
.review:last-child::before { bottom: auto; height: 24px; }
.review::after { content: ""; position: absolute; left: 110px; top: 6px; width: 8px; height: 8px; border-radius: 50%;
  background: var(--bg); border: 2px solid var(--accent); }
.when { text-align: right; padding-top: 1px; color: var(--muted); font-size: 13px; line-height: 1.3; }
.when time { display: block; color: var(--text); font-weight: 600; font-variant-numeric: tabular-nums; }
.when span { color: var(--faint); font-size: 12px; }
.rbody { min-width: 0; padding-left: 12px; }
.meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-bottom: 4px; }
.chip { display: inline-flex; align-items: center; gap: 6px; background: var(--card); border: 1px solid var(--line);
  border-radius: 999px; padding: 1px 10px; font-size: 12.5px; color: var(--muted); }
.chip code { font-size: 12px; color: var(--text); }
.chip .arrow { color: var(--faint); }
.chip.id { color: var(--accent); font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }
.av { display: inline-grid; place-items: center; width: 17px; height: 17px; margin-left: -6px; border-radius: 50%;
  background: var(--accent-soft); color: var(--accent); font-size: 10.5px; font-weight: 700; }
.written { color: var(--faint); font-size: 12px; margin-bottom: 12px; }
.summary { font-size: 16px; }
.note { position: relative; background: var(--card); border: 1px solid var(--line); border-left: 3px solid var(--line2);
  border-radius: 10px; padding: 14px 18px 12px; margin: 14px 0; box-shadow: var(--shadow); scroll-margin-top: 16px; }
.note.t-reason { border-left-color: var(--t-reason); } .note.t-todo { border-left-color: var(--t-todo); }
.note.t-question { border-left-color: var(--t-question); } .note.t-risk { border-left-color: var(--t-risk); }
.nhead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px 12px; margin-bottom: 4px; }
.note h3 { margin: 0; font-size: 16.5px; line-height: 1.35; }
.noterow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12px; }
.doc > .noterow { margin-bottom: 4px; }
.anchor { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line2); border-radius: 6px;
  padding: 0 8px 0 0; color: var(--text); overflow: hidden; }
.anchor .tab { padding: 0 6px; font-size: 10.5px; letter-spacing: .04em; color: #fff; align-self: stretch;
  display: inline-flex; align-items: center; }
.tab-pcb { background: var(--pcb); } .tab-sch { background: var(--sch); }
.anchor.removed { border-color: var(--removed); color: var(--removed); }
.anchor.removed .tab { background: var(--removed); }
.anchor.general { color: var(--muted); padding: 0 8px; border-style: dashed; }
.tag { border-radius: 999px; padding: 0 9px; background: var(--card2); color: var(--muted); border: 1px solid var(--line); }
.tag.t-reason { color: var(--t-reason); border-color: currentColor; }
.tag.t-todo { color: var(--t-todo); border-color: currentColor; }
.tag.t-question { color: var(--t-question); border-color: currentColor; }
.tag.t-risk { color: var(--t-risk); border-color: currentColor; }
.tagf.t-reason:not(.on) { color: var(--t-reason); } .tagf.t-todo:not(.on) { color: var(--t-todo); }
.tagf.t-question:not(.on) { color: var(--t-question); } .tagf.t-risk:not(.on) { color: var(--t-risk); }
.times { color: var(--faint); font-size: 11.5px; margin-top: 8px; }

/* Markdown */
.md > :first-child { margin-top: 0; } .md > :last-child { margin-bottom: 0; }
.md p { margin: .55em 0; }
.md h1, .md h2, .md h3, .md h4 { line-height: 1.3; margin: 1.2em 0 .4em; }
.md h1 { font-size: 1.35em; } .md h2 { font-size: 1.2em; } .md h3 { font-size: 1.07em; } .md h4 { font-size: 1em; }
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
.md tr:nth-child(even) td { background: color-mix(in srgb, var(--card2) 50%, transparent); }
.md hr { border: 0; border-top: 1px solid var(--line); margin: 1.4em 0; }
.md a { overflow-wrap: anywhere; }
math { font-size: 1.1em; }
math[display=block] { margin: .8em 0; overflow-x: auto; overflow-y: hidden; }
.math-error { color: var(--removed); border-bottom: 1px dotted var(--removed); cursor: help; }
.wl { text-decoration: none; border-bottom: 1px dashed var(--link); }
.wl:hover { border-bottom-style: solid; }
.wl.missing { color: var(--muted); border-bottom-color: var(--faint); cursor: help; }
a[target=_blank]::after { content: "↗"; font-size: .75em; margin-left: 2px; color: var(--faint); }

.empty { color: var(--muted); font-style: italic; }
.empty-state { text-align: center; padding: 60px 20px; border: 1px dashed var(--line2); border-radius: 12px;
  color: var(--muted); }
.empty-state .big { font-size: 20px; font-weight: 650; color: var(--text); margin-bottom: 6px; }
#none { display: none; text-align: center; color: var(--muted); padding: 40px 0; }
#none.show { display: block; }
.foot { color: var(--faint); font-size: 12px; margin-top: 30px; padding-top: 16px; border-top: 1px solid var(--line); }
.hidden { display: none !important; }
#top { position: fixed; right: 22px; bottom: 22px; width: 40px; height: 40px; border-radius: 50%; display: grid;
  place-items: center; background: var(--card); border: 1px solid var(--line2); color: var(--muted); text-decoration: none;
  box-shadow: 0 4px 14px rgba(0,0,0,.25); opacity: 0; pointer-events: none; transition: opacity .2s; }
#top.show { opacity: 1; pointer-events: auto; }
#toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%); background: var(--text); color: var(--bg);
  padding: 6px 14px; border-radius: 8px; font-size: 13px; opacity: 0; transition: opacity .2s; pointer-events: none; }
#toast.show { opacity: 1; }
:target .note, .note:target { box-shadow: 0 0 0 2px var(--accent-soft); }

@media (max-width: 860px) {
  .layout { grid-template-columns: 1fr; }
  .side { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
  #toc { max-height: 40vh; }
  .side .proj, .side .count { display: none; }  /* the header below shows them */
  main { padding: 24px 16px 72px; }
  .hero h1 { font-size: 28px; }
  .review { grid-template-columns: 1fr; padding-left: 20px; padding-bottom: 32px; }
  .review::before { left: 4px; }
  .review::after { left: -1px; }
  .when { text-align: left; display: flex; gap: 8px; align-items: baseline; margin-bottom: 4px; }
  .when time { display: inline; }
  .rbody { padding-left: 0; }
  .doc { padding: 16px 16px 12px; }
  .hash { display: none; }
}
@media print {
  :root { --bg: #fff; --card: #fff; --card2: #f6f6f6; --text: #000; --muted: #444; --faint: #777; --line: #ddd;
    --line2: #ccc; --shadow: none; color-scheme: light; }
  .side, #top, #toast { display: none !important; }
  .layout { display: block; } main { max-width: none; padding: 0; }
  .note, .doc, .stat { break-inside: avoid; }
  a[target=_blank]::after { content: ""; }
}
</style>
</head>
<body>
<div class="layout">
<aside class="side">
  <div class="side-top">
    <div class="brand">%%LOGO%% kigit <small>reviews</small></div>
    <div class="proj">%%NAME%%</div>
    <div class="count">%%COUNT%%</div>
    <label class="search">
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M7 2a5 5 0 0 1 3.9 8.1l3 3-.8.8-3-3A5 5 0 1 1 7 2zm0 1.2a3.8 3.8 0 1 0 0 7.6 3.8 3.8 0 0 0 0-7.6z"/></svg>
      <input id="q" type="search" placeholder="Search notes and reviews" aria-label="Search notes and reviews" autocomplete="off">
      <kbd>/</kbd>
    </label>
    <div class="tags">%%TAGS%%</div>
  </div>
  <nav id="toc" aria-label="Notes and reviews">%%NAV%%</nav>
  <div class="side-foot">
    <span>Built %%MADE%%</span>
    <button class="iconbtn" id="theme" type="button" title="Switch between light and dark">Theme</button>
  </div>
</aside>
<main>
<header class="hero">
  <div class="eyebrow">Design reviews</div>
  <h1>%%NAME%%</h1>
  <p class="lede">Why the board changed, commit by commit, and the notes behind it.</p>
  <div class="stats">%%STATS%%</div>
</header>
%%BODY%%
<p id="none">Nothing matches. <a href="#" id="clear">Clear the search</a></p>
<p class="foot">Built by kigit from reviews/ on %%MADE%%.</p>
</main>
</div>
<a id="top" href="#" aria-label="Back to the top">↑</a>
<div id="toast" role="status"></div>
<script>
(() => {
  const q = document.getElementById("q");
  const on = new Set();
  const none = document.getElementById("none");
  // Search text and tags: hide notes and reviews that don't match.
  function filter() {
    const words = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
    const active = words.length > 0 || on.size > 0;
    const hit = (text) => words.every((w) => text.toLowerCase().includes(w));
    let shown = 0;
    document.querySelectorAll(".review").forEach((r) => {
      // The review's own text: subject, commit details, summary.
      const head = [...r.querySelectorAll("h2, .meta, .summary")].map((e) => e.textContent).join(" ");
      let any = false;
      r.querySelectorAll(".note").forEach((n) => {
        const tagged = !on.size || n.dataset.tags.split(" ").some((t) => on.has(t));
        const show = !active || (tagged && (hit(n.textContent) || hit(head)));
        n.classList.toggle("hidden", !show);
        any = any || show;
      });
      const showReview = !active || any || (!on.size && hit(head));
      r.classList.toggle("hidden", !showReview);
      shown += showReview;
      document.querySelector(`#toc [data-r="${r.id}"]`)?.classList.toggle("hidden", !showReview);
    });
    // Your own notes: their tags and all their text.
    document.querySelectorAll(".doc").forEach((d) => {
      const tagged = !on.size || d.dataset.tags.split(" ").some((t) => on.has(t));
      const show = !active || (tagged && hit(d.textContent));
      d.classList.toggle("hidden", !show);
      shown += show;
      document.querySelector(`#toc [data-r="${d.id}"]`)?.classList.toggle("hidden", !show);
    });
    none.classList.toggle("show", active && shown === 0);
  }
  q.addEventListener("input", filter);
  document.querySelectorAll(".tagf").forEach((b) => b.addEventListener("click", () => {
    b.classList.toggle("on");
    b.classList.contains("on") ? on.add(b.dataset.tag) : on.delete(b.dataset.tag);
    filter();
  }));
  document.getElementById("clear").addEventListener("click", (e) => {
    e.preventDefault();
    q.value = "";
    on.clear();
    document.querySelectorAll(".tagf.on").forEach((b) => b.classList.remove("on"));
    filter();
  });
  // "/" jumps to the search box, Escape clears it.
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== q && !e.ctrlKey && !e.metaKey) { e.preventDefault(); q.focus(); }
    else if (e.key === "Escape" && document.activeElement === q) { q.value = ""; filter(); q.blur(); }
  });
  // Links out of the page (web, files) open in a new tab; links within it don't.
  document.querySelectorAll(".md a[href], .props a[href]").forEach((a) => {
    if (!a.getAttribute("href").startsWith("#")) { a.target = "_blank"; a.rel = "noopener"; }
  });
  // The # next to a heading copies a link to it.
  const toast = document.getElementById("toast");
  let toastTimer;
  function say(text) {
    toast.textContent = text;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1400);
  }
  document.querySelectorAll("a.hash").forEach((a) => a.addEventListener("click", () => {
    const url = location.href.split("#")[0] + a.getAttribute("href");
    navigator.clipboard?.writeText(url).then(() => say("Link copied"), () => {});
  }));
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
  // Back to the top, once scrolled down.
  const top = document.getElementById("top");
  addEventListener("scroll", () => top.classList.toggle("show", scrollY > 600), { passive: true });
  // Mark the review in view in the list.
  const links = new Map([...document.querySelectorAll("#toc a")].map((a) => [a.dataset.r, a]));
  const seen = new IntersectionObserver((entries) => entries.forEach((e) => {
    if (!e.isIntersecting) return;
    links.forEach((a) => a.classList.remove("cur"));
    const cur = links.get(e.target.id);
    if (cur) { cur.classList.add("cur"); cur.scrollIntoView({ block: "nearest" }); }
  }), { rootMargin: "0px 0px -70% 0px" });
  document.querySelectorAll(".review, .doc").forEach((r) => seen.observe(r));
})();
</script>
</body>
</html>
"""
