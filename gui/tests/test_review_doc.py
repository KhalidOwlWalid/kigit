"""The reviews site (review_doc.py): tabs, one page per review, note and
discussion, the timeline, search."""

import asyncio
import json
from pathlib import Path

from kigit_gui import review, review_doc
from kigit_gui.review import Anchor, Note, Review, Seen
from kigit_gui.review_panel import project_key

A = "0123456789abcdef0123456789abcdef01234567"
B = "fedcba9876543210fedcba9876543210fedcba98"
PNG = b"\x89PNG not really"


def make(tmp_path: Path) -> tuple[Review, Review]:
    img = review.save_image(tmp_path, PNG, "image/png")
    old = Review(commit=B, subject="first <board>", date="2025-01-10 12:00", author="Author B")
    new = Review(commit=A, parent=B, subject="remove C1", date="2025-03-01 12:00", author="Author B",
                 summary="See [issue](https://example.com/1).",
                 notes=[Note(title="Dropped C1", body=f"Gone. ![shot]({img})", tags=["reason"],
                             anchor=Anchor("pcb", "footprint", "C1", Seen(B, A, "old"))),
                        Note(title="General thought")])
    review.save(tmp_path, old)
    review.save(tmp_path, new)
    return old, new


def page(tmp_path: Path, url: str = "", **kw) -> str:
    out = review_doc.render(tmp_path, url, **kw)
    assert out is not None, f"no page {url!r}"
    assert "%%" not in out  # every placeholder filled
    return out


def own(tmp_path: Path, rel: str, text: str) -> Path:
    p = tmp_path / "reviews" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_tabs_one_per_section_and_folder(tmp_path: Path) -> None:
    """Home, Reviews, Discussions (when there are some), a tab per top folder
    of your own notes, Notes for loose files, Tags."""
    from kigit_gui import threads

    make(tmp_path)
    own(tmp_path, "decisions/buck.md", "# Buck\n")
    own(tmp_path, "meetings/2025/kickoff.md", "# Kickoff\n")
    own(tmp_path, "scratch.md", "x")
    threads.start(tmp_path, "Check C1", "", A, "Author A", A)
    book = review_doc.build(tmp_path)
    assert [t.label for t in book.tabs] == ["Home", "Reviews", "Discussions", "decisions", "meetings", "Notes",
                                            "Tags"]
    home = page(tmp_path)
    assert '<a class="tabl cur" href="/">Home</a>' in home and 'href="/notes/meetings/">meetings</a>' in home
    meet = page(tmp_path, "notes/meetings/")  # the folder's overview, subfolders as groups
    assert "Kickoff" in meet and "2025/" in meet and '<a class="tabl cur" href="/notes/meetings/">' in meet
    assert review_doc.render(tmp_path, "nope") is None


def test_timeline_newest_first_by_month(tmp_path: Path) -> None:
    old, new = make(tmp_path)
    t = page(tmp_path, "reviews", name="owl")
    assert "<title>Timeline · owl</title>" in t
    assert t.index(f'id="r-{new.id}"') < t.index(f'id="r-{old.id}"')  # newest commit first
    assert '<h2 class="month" id="m-2025-03">March 2025</h2>' in t and "January 2025" in t
    assert f'<a href="/reviews/{new.id}">remove C1</a>' in t  # each links to its page
    assert f'href="/reviews/{new.id}#n-{new.notes[0].id}">Dropped C1</a>' in t  # its notes' headlines
    assert "first &lt;board&gt;" in t and "first <board>" not in t  # escaped
    assert f'<code title="{A}">0123456</code>' in t
    assert '<div class="timeline">' in t and '<div class="when"><time>' in t


def test_review_page_has_its_notes(tmp_path: Path) -> None:
    old, new = make(tmp_path)
    r = page(tmp_path, f"reviews/{new.id}")
    assert '<span class="anchor removed"' in r and "Footprint C1 · removed" in r
    assert '<span class="anchor general">General note</span>' in r
    assert '<span class="tag t-reason">reason</span>' in r
    assert f"Written {new.notes[0].created}" in r
    assert '<a href="https://example.com/1">issue</a>' in r  # Markdown rendered
    assert "data:image/png;base64," in r and 'src="assets/' not in r  # no file route: embedded
    assert f'href="#n-{new.notes[0].id}">Dropped C1</a>' in r  # on this page
    assert f'<a class="pn next" href="/reviews/{old.id}"><small>Older →</small>' in r
    assert f'class="nl cur" href="/reviews/{new.id}"' in r  # marked in the sidebar
    served = page(tmp_path, f"reviews/{new.id}", files_url="/reviews-doc/K/files/")
    assert 'src="/reviews-doc/K/files/assets/' in served  # in the GUI: served, not embedded


def test_named_after_the_kicad_project(tmp_path: Path) -> None:
    (tmp_path / "owl.kicad_pro").write_text("{}", encoding="utf-8")
    assert "<title>owl</title>" in page(tmp_path)


def test_home(tmp_path: Path) -> None:
    empty = page(tmp_path, name="empty")
    assert "Nothing here yet" in empty and "0 notes · 0 reviews" in empty
    _, new = make(tmp_path)
    home = page(tmp_path)
    assert '<div class="stat"><b>2</b><span>reviews</span></div>' in home
    assert "Latest reviews" in home and f'href="/reviews/{new.id}"' in home


def test_routes(tmp_path: Path) -> None:
    _, new = make(tmp_path)
    key = project_key(tmp_path)
    ok = asyncio.run(review_doc._doc(key))  # noqa: SLF001
    assert ok.status_code == 200 and b"remove C1" in ok.body
    one = asyncio.run(review_doc._doc_page_route(key, f"reviews/{new.id}"))  # noqa: SLF001
    assert one.status_code == 200 and f'href="/reviews-doc/{key}/reviews"'.encode() in one.body
    assert asyncio.run(review_doc._doc_page_route(key, "reviews/zzz")).status_code == 404  # noqa: SLF001
    assert asyncio.run(review_doc._doc("nope")).status_code == 404  # noqa: SLF001


def test_search_index(tmp_path: Path) -> None:
    """Every review, note, discussion, and each note in a review on its own."""
    from kigit_gui import threads

    _, new = make(tmp_path)
    own(tmp_path, "decisions/buck.md", "---\ntags: [power]\n---\n# Buck\n\nThe LDO ran **hot**.\n")
    threads.start(tmp_path, "Check C1", "Too close.", A, "Author A", A)
    key = project_key(tmp_path)
    found = json.loads(asyncio.run(review_doc._search(key)).body)  # noqa: SLF001
    by_title = {e["t"]: e for e in found}
    assert by_title["remove C1"]["u"] == f"/reviews-doc/{key}/reviews/{new.id}"
    assert by_title["remove C1"]["x"].startswith("remove C1 See issue")  # text first, the hash last
    assert by_title["Dropped C1"]["u"].endswith(f"#n-{new.notes[0].id}") and by_title["Dropped C1"]["g"] == ["reason"]
    assert by_title["Buck"]["k"] == "Note" and "The LDO ran hot." in by_title["Buck"]["x"]
    assert by_title["Buck"]["u"] == f"/reviews-doc/{key}/notes/decisions/buck"
    assert by_title["Check C1"]["k"] == "Discussion" and "Too close." in by_title["Check C1"]["x"]


def test_own_notes(tmp_path: Path) -> None:
    """Any other Markdown in reviews/ is a page: title, properties, tags."""
    make(tmp_path)
    own(tmp_path, "decisions/buck.md",
        "---\nstatus: accepted\ntags: [decision, power]\n---\n# Buck for 3V3\n\n## Why\nLDO ran hot. #thermal\n")
    own(tmp_path, "scratch.md", "Just text, no heading.\n\n```\n#notatag [[nolink]]\n```\n")
    buck = page(tmp_path, "notes/decisions/buck")
    assert '<h1 class="title">Buck for 3V3</h1>' in buck  # title from the # heading
    assert "<code>decisions/buck.md</code>" in buck
    assert "<th>status</th><td>accepted</td>" in buck
    assert 'href="/tags/thermal">thermal</a>' in buck  # tags link to their page
    assert '<span class="itag">#thermal</span>' in buck  # a #tag in the text shows as one
    assert '<h2 id="h-why">Why</h2>' in buck and 'href="#h-why">Why</a>' in buck  # on this page
    scratch = page(tmp_path, "notes/scratch")
    assert '<h1 class="title">scratch</h1>' in scratch  # no heading: the file name
    assert "#notatag [[nolink]]" in scratch  # code is left as it is
    assert "tags/notatag" not in page(tmp_path, "tags")
    tag = page(tmp_path, "tags/thermal")
    assert 'href="/notes/decisions/buck"' in tag


def test_kigit_files_are_not_notes(tmp_path: Path) -> None:
    make(tmp_path)
    own(tmp_path, "assets/readme.md", "x")
    own(tmp_path, ".obsidian/x.md", "x")
    book = review_doc.build(tmp_path)
    assert not book.docs and [t.label for t in book.tabs] == ["Home", "Reviews", "Tags"]


def test_links_between_pages(tmp_path: Path) -> None:
    """[[links]], [[subject]], relative note/review/file links, embeds."""
    _, new = make(tmp_path)
    (tmp_path / "reviews" / "pics").mkdir(parents=True)
    (tmp_path / "reviews" / "pics" / "scope.png").write_bytes(PNG)
    (tmp_path / "secret.png").write_bytes(PNG)
    (tmp_path / "reviews" / "docs").mkdir()
    (tmp_path / "reviews" / "docs" / "ds 1.pdf").write_bytes(b"%PDF")
    own(tmp_path, "decisions/buck.md", "# Buck for 3V3\nSee [[thermal test|the test]], [[" + new.id + "]], "
        f"[[{new.subject}]] and `#nottag`.\n![[scope.png|200]] ![](../pics/scope.png) ![](../../secret.png) "
        "[[Nowhere]]\n[the bench](../thermal%20test.md#results), [review](../" + new.id + ".md), "
        "[ds](../docs/ds%201.pdf), [[ds 1.pdf]], [gone](../nope.md), https://ti.com/x\n")
    own(tmp_path, "thermal test.md", "Back to [[Buck for 3V3]].\n")
    buck = page(tmp_path, "notes/decisions/buck", files_url="/F/")
    assert '<a class="wl" href="/notes/thermal%20test">the test</a>' in buck
    assert f'<a class="wl" href="/reviews/{new.id}">{new.id}</a>' in buck  # a review by its ID
    assert f'<a class="wl" href="/reviews/{new.id}">{new.subject}</a>' in buck  # ... by its subject
    assert '<span class="wl missing" title="Not in reviews/">Nowhere</span>' in buck
    assert 'width="200"' in buck and buck.count('src="/F/pics/scope.png"') == 2
    assert "../../secret.png" in buck  # outside reviews/: not read
    assert '<a href="/notes/thermal%20test">the bench</a>' in buck
    assert f'<a href="/reviews/{new.id}">review</a>' in buck
    assert '<a href="/F/docs/ds%201.pdf">ds</a>' in buck and '<a class="wl" href="/F/docs/ds%201.pdf">' in buck
    assert '<a href="../nope.md">gone</a>' in buck  # not there: left as written
    assert '<a href="https://ti.com/x">https://ti.com/x</a>' in buck
    assert "<code>#nottag</code>" in buck
    assert '<a class="wl" href="/notes/decisions/buck">Buck for 3V3</a>' in page(tmp_path, "notes/thermal test")


def test_file_route(tmp_path: Path) -> None:
    make(tmp_path)
    (tmp_path / "reviews" / "docs").mkdir()
    (tmp_path / "reviews" / "docs" / "ds.pdf").write_bytes(b"%PDF")
    (tmp_path / "reviews" / "docs" / "x.html").write_text("<script>1</script>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("no", encoding="utf-8")
    key = project_key(tmp_path)
    ok = asyncio.run(review_doc._file(key, "docs/ds.pdf"))  # noqa: SLF001
    assert ok.status_code == 200 and Path(ok.path).read_bytes() == b"%PDF" and ok.media_type == "application/pdf"
    html_file = asyncio.run(review_doc._file(key, "docs/x.html"))  # noqa: SLF001
    assert html_file.media_type == "application/octet-stream"  # a download, never a page
    assert asyncio.run(review_doc._file(key, "../secret.txt")).status_code == 404  # noqa: SLF001
    assert asyncio.run(review_doc._file(key, "docs/none.pdf")).status_code == 404  # noqa: SLF001


def test_math(tmp_path: Path) -> None:
    own(tmp_path, "filter.md", "# RC filter\n\n$f_c = \\frac{1}{2 \\pi R C}$ with [[RC filter|itself]].\n\n"
        "$$\nH(s) = \\frac{1}{1 + sRC}\n$$\n")
    p = page(tmp_path, "notes/filter")
    assert 'display="inline"' in p and 'display="block"' in p and "<mi>&#x003C0;</mi>" in p  # π
    assert '<a class="wl" href="/notes/filter">itself</a>' in p


def test_discussions(tmp_path: Path) -> None:
    """Discussions get their own tab, grouped by status; their files aren't
    notes of your own."""
    from kigit_gui import threads

    make(tmp_path)
    a = threads.start(tmp_path, "Check <C1>", "Too close.", "a" * 40, "Author A", "a" * 40)
    b = threads.start(tmp_path, "GND pour", "Fine?", "a" * 40, "Author B", "a" * 40)
    threads.add(tmp_path, b.id, "Author A", "b" * 40, "Yes.", "accepted")
    d = page(tmp_path, "discussions")
    assert d.index(f'href="/discussions/{a.id}"') < d.index(f'href="/discussions/{b.id}"')  # attention first
    assert "Check &lt;C1&gt;" in d and "Needs attention" in d and "Accepted" in d
    one = page(tmp_path, f"discussions/{b.id}")
    assert "<b>Author A</b> accepted" in one and "<code>bbbbbbb</code>" in one
    assert not review_doc.build(tmp_path).docs  # threads/ isn't a folder of notes


def test_discussion_links_on_the_site(tmp_path: Path) -> None:
    """A pasted discussion link goes to its page; one to a discussion that's
    gone shows as missing."""
    from kigit_gui import threads

    t = threads.start(tmp_path, "Check C1", "x", A, "Author A", A)
    own(tmp_path, "n.md", f"See {threads.link_markdown(t)} and [old one](threads/deadbeef.md).\n")
    p = page(tmp_path, "notes/n")
    assert f'<a href="/discussions/{t.id}">Check C1</a>' in p
    assert '<span class="wl missing" title="This discussion is gone: deleted, or not pulled yet">old one</span>' in p


def test_mentioned_in(tmp_path: Path) -> None:
    """A discussion's or review's page lists where it's linked from."""
    from kigit_gui import threads

    _, new = make(tmp_path)
    t = threads.start(tmp_path, "Check C1", "x", A, "Author A", A)
    threads.start(tmp_path, "Other", f"See {threads.link_markdown(t)} and [r]({new.id}.md)", A, "Author B", A)
    p = page(tmp_path, f"discussions/{t.id}")
    assert 'id="mentioned">Mentioned in</h2>' in p and 'the discussion "Other"</a>' in p and "by Author B" in p
    r = page(tmp_path, f"reviews/{new.id}")
    assert 'the discussion "Other"' in r and 'href="#mentioned">Mentioned in</a>' in r


def test_nested_folders_are_sub_tabs(tmp_path: Path) -> None:
    """Folders in folders, as deep as they go: a page each, a row of tabs per
    level, a tree on the left; a note's pins show on its page (not the
    kigit-pins comment)."""
    from kigit_gui import notebook

    own(tmp_path, "OwlPCB_Notes/Logs.md", "# Logs\n")
    own(tmp_path, "OwlPCB_Notes/System Implementation/USB-UART.md", "# USB-UART\n\nCH340.\n")
    own(tmp_path, "OwlPCB_Notes/System Implementation/Power/LDO.md", "# LDO\n")
    n = notebook.read(tmp_path / "reviews" / "OwlPCB_Notes" / "System Implementation" / "USB-UART.md")
    n.pins = [Anchor("pcb", "footprint", "U3")]
    notebook.write(n)
    top = page(tmp_path, "notes/OwlPCB_Notes/")
    assert 'href="/notes/OwlPCB_Notes/System%20Implementation/">📁 System Implementation</a>' in top
    assert "2 notes" in top and "Logs" in top  # the folder's card counts what's inside it
    deep = page(tmp_path, "notes/OwlPCB_Notes/System Implementation/Power/")
    assert deep.count('class="subtabs"') == 2  # OwlPCB_Notes' folders, then System Implementation's
    assert '<a class="subl cur" href="/notes/OwlPCB_Notes/System%20Implementation/Power/">📁 Power</a>' in deep
    assert "<details class=\"nf\" open>" in deep  # the tree, open down to here
    usb = page(tmp_path, "notes/OwlPCB_Notes/System Implementation/USB-UART")
    assert "Footprint U3" in usb and "kigit-pins" not in usb
    assert '<a class="subl cur" href="/notes/OwlPCB_Notes/System%20Implementation/">' in usb


def test_pictures_open_full_size(tmp_path: Path) -> None:
    """Pictures on the Reviews page (and in the GUI) open full size on click."""
    from kigit_gui import lightbox

    _, new = make(tmp_path)
    r = page(tmp_path, f"reviews/{new.id}")
    assert 'id="kigit-lightbox"' in r and 'e.target.closest("main .md img")' in r
    assert "main .md img { cursor: zoom-in; }" in r
    assert 'closest(".kigit-md-view img")' in lightbox.html(".kigit-md-view")


def test_added_pictures_show_in_notes_in_folders(tmp_path: Path) -> None:
    """A picture added in kigit's editor is linked as assets/x.png (relative
    to reviews/), even from a note in a folder: the page finds it there."""
    from kigit_gui.md_editor import rewrite_assets
    from kigit_gui.review_panel import project_key

    rel = review.save_file(tmp_path, PNG, "shot.png", "image/png")
    own(tmp_path, "Design Notes/Power.md", f"# Power\n\n![shot.png]({rel})\n\n[the picture]({rel})\n")
    p = page(tmp_path, "notes/Design Notes/Power", files_url="/F/")
    assert f'src="/F/{rel}"' in p and f'href="/F/{rel}"' in p and "No page" not in p
    key = project_key(tmp_path)
    assert f"](/review-files/{key}/" in rewrite_assets(f"![x](../{rel})", key)  # Obsidian's ../assets/x.png
