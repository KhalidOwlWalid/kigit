"""The all-reviews page (review_doc.py)."""

import asyncio
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


def test_page_has_every_review_newest_first(tmp_path: Path) -> None:
    old, new = make(tmp_path)
    page = review_doc.render(tmp_path, "owl")
    assert "<title>owl reviews</title>" in page
    assert "0 notes · 2 reviews" in page
    assert page.index(f'id="r-{new.id}"') < page.index(f'id="r-{old.id}"')  # newest commit first
    assert f'href="#r-{new.id}"' in page  # in the list on the left
    assert "first &lt;board&gt;" in page and "first <board>" not in page  # escaped
    assert f'<code title="{A}">0123456</code>' in page


def test_page_shows_notes_with_anchor_tags_and_times(tmp_path: Path) -> None:
    _, new = make(tmp_path)
    page = review_doc.render(tmp_path)
    assert '<span class="anchor removed"' in page and "Footprint C1 · removed" in page
    assert '<span class="anchor general">General note</span>' in page
    assert '<span class="tag t-reason">reason</span>' in page and 'data-tag="reason"' in page
    assert f"Written {new.notes[0].created}" in page
    assert '<a href="https://example.com/1">issue</a>' in page  # Markdown rendered


def test_page_embeds_images(tmp_path: Path) -> None:
    make(tmp_path)
    page = review_doc.render(tmp_path)
    assert "data:image/png;base64," in page and "](assets/" not in page and 'src="assets/' not in page


def test_page_is_named_after_the_kicad_project(tmp_path: Path) -> None:
    (tmp_path / "owl.kicad_pro").write_text("{}")
    assert "<title>owl reviews</title>" in review_doc.render(tmp_path)


def test_page_without_reviews(tmp_path: Path) -> None:
    page = review_doc.render(tmp_path, "empty")
    assert "Nothing here yet" in page and "0 notes · 0 reviews" in page


def test_page_route(tmp_path: Path) -> None:
    make(tmp_path)
    ok = asyncio.run(review_doc._doc(project_key(tmp_path)))  # noqa: SLF001
    assert ok.status_code == 200 and b"remove C1" in ok.body
    assert asyncio.run(review_doc._doc("nope")).status_code == 404  # noqa: SLF001


def own(tmp_path: Path, rel: str, text: str) -> Path:
    p = tmp_path / "reviews" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def test_own_notes_are_on_the_page(tmp_path: Path) -> None:
    """Any other Markdown in reviews/ shows as a note: title, properties, tags."""
    _, new = make(tmp_path)
    own(tmp_path, "decisions/buck.md",
        "---\nstatus: accepted\ntags: [decision, power]\n---\n# Buck for 3V3\n\nLDO ran hot. #thermal\n")
    own(tmp_path, "scratch.md", "Just text, no heading.\n\n```\n#notatag [[nolink]]\n```\n")
    page = review_doc.render(tmp_path)
    assert "2 notes · 2 reviews" in page
    assert page.index('<h1 class="group">Notes</h1>') < page.index('<h1 class="group">Reviews</h1>')
    assert 'href="#d-decisions-buck" title="Link to this note">#</a>Buck for 3V3</h2>' in page  # title from the # heading
    assert "<code>decisions/buck.md</code>" in page
    assert "<th>status</th><td>accepted</td>" in page
    assert 'data-tags="decision power thermal"' in page and 'data-tag="thermal"' in page
    assert ">scratch</h2>" in page  # no heading: the file name
    assert "#notatag [[nolink]]" in page  # code is left as it is
    assert 'data-tag="notatag"' not in page
    assert '<span class="itag">#thermal</span>' in page  # a #tag in the text shows as one


def test_page_layout_bits(tmp_path: Path) -> None:
    """Header numbers, the timeline, anchor badges, [[subject]] links, and
    #tags in code or link targets left alone."""
    old, new = make(tmp_path)
    own(tmp_path, "n.md", f"See [[{new.subject}]], [top](#r-{new.id}) and `#nottag`.\n")
    page = review_doc.render(tmp_path)
    assert '<div class="stat"><b>2</b><span>reviews</span></div>' in page
    assert '<div class="timeline">' in page and '<div class="when"><time>' in page
    assert '<b class="tab tab-pcb">PCB</b>' in page or '<b class="tab tab-sch">SCH</b>' in page
    assert f'<a class="wl" href="#r-{new.id}">' in page  # a review by its commit subject
    assert "<code>#nottag</code>" in page and f'href="#r-{new.id}">top</a>' in page
    assert 'class="itag"' not in page
    assert "%%" not in page  # every placeholder filled


def test_kigit_files_are_not_notes(tmp_path: Path) -> None:
    make(tmp_path)
    own(tmp_path, "assets/readme.md", "x")
    own(tmp_path, ".obsidian/x.md", "x")
    page = review_doc.render(tmp_path)
    assert "0 notes · 2 reviews" in page and "Reviews</h1>" in page and "Notes</h1>" not in page


def test_obsidian_links_and_embeds(tmp_path: Path) -> None:
    _, new = make(tmp_path)
    (tmp_path / "reviews" / "pics").mkdir(parents=True)
    (tmp_path / "reviews" / "pics" / "scope.png").write_bytes(PNG)
    (tmp_path / "secret.png").write_bytes(PNG)
    own(tmp_path, "decisions/buck.md", "# Buck for 3V3\nSee [[thermal test|the test]] and [[" + new.id + "]].\n"
        "![[scope.png|200]] ![](../pics/scope.png) ![](../../secret.png) [[Nowhere]]\n")
    own(tmp_path, "thermal test.md", "Back to [[Buck for 3V3]].\n")
    page = review_doc.render(tmp_path)
    assert '<a class="wl" href="#d-thermal-test">the test</a>' in page
    assert f'<a class="wl" href="#r-{new.id}">{new.id}</a>' in page  # a review by its ID
    assert '<a class="wl" href="#d-decisions-buck">Buck for 3V3</a>' in page  # a note by its title
    assert '<span class="wl missing" title="Not in reviews/">Nowhere</span>' in page
    assert 'width="200"' in page and page.count("data:image/png;base64,") >= 3
    assert "../../secret.png" in page  # outside reviews/: not read


def test_links(tmp_path: Path) -> None:
    """Web, bare, relative note/review/file links and [[file]] links."""
    _, new = make(tmp_path)
    (tmp_path / "reviews" / "docs").mkdir()
    (tmp_path / "reviews" / "docs" / "ds 1.pdf").write_bytes(b"%PDF")
    own(tmp_path, "Bench test.md", "# Bench\n")
    own(tmp_path, "decisions/buck.md",
        "# Buck\nSee https://ti.com/x, [the bench](../Bench%20test.md#results), "
        f"[review](../{new.id}.md), [ds](../docs/ds%201.pdf), [[ds 1.pdf]], [gone](../nope.md), "
        "[web](https://example.com).\n")
    page = review_doc.render(tmp_path, files_url="/reviews-doc/K/files/")
    assert '<a href="https://ti.com/x">https://ti.com/x</a>' in page
    assert '<a href="#d-bench-test">the bench</a>' in page
    assert f'<a href="#r-{new.id}">review</a>' in page
    assert '<a href="/reviews-doc/K/files/docs/ds%201.pdf">ds</a>' in page
    assert '<a class="wl" href="/reviews-doc/K/files/docs/ds%201.pdf">ds 1.pdf</a>' in page
    assert '<a href="../nope.md">gone</a>' in page  # not there: left as written
    assert '<a href="https://example.com">web</a>' in page


def test_file_route(tmp_path: Path) -> None:
    make(tmp_path)
    (tmp_path / "reviews" / "docs").mkdir()
    (tmp_path / "reviews" / "docs" / "ds.pdf").write_bytes(b"%PDF")
    (tmp_path / "secret.txt").write_text("no")
    key = project_key(tmp_path)
    ok = asyncio.run(review_doc._file(key, "docs/ds.pdf"))  # noqa: SLF001
    assert ok.status_code == 200 and Path(ok.path).read_bytes() == b"%PDF"
    assert asyncio.run(review_doc._file(key, "../secret.txt")).status_code == 404  # noqa: SLF001
    assert asyncio.run(review_doc._file(key, "docs/none.pdf")).status_code == 404  # noqa: SLF001


def test_math_on_the_page(tmp_path: Path) -> None:
    own(tmp_path, "filter.md", "# RC filter\n\n$f_c = \\frac{1}{2 \\pi R C}$ with [[RC filter|itself]].\n\n"
        "$$\nH(s) = \\frac{1}{1 + sRC}\n$$\n")
    page = review_doc.render(tmp_path)
    assert 'display="inline"' in page and 'display="block"' in page and "<mi>&#x003C0;</mi>" in page  # π
    assert '<a class="wl" href="#d-filter">itself</a>' in page


def test_discussions_on_the_page(tmp_path: Path) -> None:
    """Discussions get their own section (needing attention first); their
    files aren't listed as notes of your own."""
    from kigit_gui import threads

    make(tmp_path)
    a = threads.start(tmp_path, "Check <C1>", "Too close.", "a" * 40, "Author A", "a" * 40)
    b = threads.start(tmp_path, "GND pour", "Fine?", "a" * 40, "Author B", "a" * 40)
    threads.add(tmp_path, b.id, "Author A", "b" * 40, "Yes.", "accepted")
    page = review_doc.render(tmp_path)
    assert '<h1 class="group">Discussions</h1>' in page
    assert page.index(f'id="t-{a.id}"') < page.index(f'id="t-{b.id}"')  # attention first
    assert "Check &lt;C1&gt;" in page and "Needs attention" in page and "Accepted" in page
    assert "<b>Author A</b> accepted" in page and "<code>bbbbbbb</code>" in page
    assert f"threads/{a.id}" not in page  # not shown as a note of your own
