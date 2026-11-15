"""The review file format (review.py) and image links (review_panel.py)."""

from pathlib import Path

import pytest

from kigit_gui import review
from kigit_gui.review import Anchor, Note, Review, Seen
from kigit_gui.review_panel import rewrite_images

COMMIT = "0123456789abcdef0123456789abcdef01234567"
PARENT = "fedcba9876543210fedcba9876543210fedcba98"


def sample() -> Review:
    return Review(
        commit=COMMIT, parent=PARENT, subject="v2: add C1, move R2", date="2025-03-01 12:00", author="Author B | L",
        created="2026-11-13 10:00",
        summary="Why: rev B feedback.\n\nSee [the issue](https://example.com/1).",
        notes=[
            Note(title="Moved U3", body="Closer to the LDO.\n\n## Not a note\nstill the body",
                 anchor=Anchor("pcb", "footprint", "U3"), tags=["reason", "risk"]),
            Note(title="Odd net --> name", body="", anchor=Anchor("sch", "net", "/a-->b")),
            Note(title="Removed R5", body="Not needed.", anchor=Anchor("sch", "part", "R5", Seen(PARENT, COMMIT, "old"))),
            Note(title="General", body="![](assets/0123456789abcdef.png)"),
        ])


def test_round_trip() -> None:
    r = sample()
    back = review.loads(review.dumps(r))
    assert (back.commit, back.parent, back.subject, back.date, back.author, back.created) == \
           (r.commit, r.parent, r.subject, r.date, r.author, r.created)
    assert back.summary == r.summary
    assert [(n.id, n.title, n.body, n.anchor, n.tags) for n in back.notes] == \
           [(n.id, n.title, n.body, n.anchor, n.tags) for n in r.notes]


def test_heading_without_note_comment_is_text() -> None:
    back = review.loads(review.dumps(sample()))
    assert len(back.notes) == 4
    assert "## Not a note" in back.notes[0].body


def test_reads_hand_edited_file() -> None:
    text = (f"---\r\ncommit: {COMMIT}\r\nsubject: x\r\n---\r\n\r\nsummary\r\n\r\n"
            "## A\r\n<!-- kigit-note {\"id\": \"aa\", \"anchor\": null, \"tags\": [\"todo\", 3]} -->\r\nbody\r\n"
            "## B\n<!-- kigit-note {broken json} -->\n")
    r = review.loads(text)
    assert r.summary == "summary"
    assert [(n.title, n.body, n.tags, n.anchor) for n in r.notes] == [("A", "body", ["todo"], None), ("B", "", [], None)]


def test_not_a_review() -> None:
    with pytest.raises(ValueError):
        review.loads("# just notes\n")


def test_save_find_and_reload(tmp_path: Path) -> None:
    r = sample()
    path = review.save(tmp_path, r)
    d = tmp_path / "reviews"
    assert r.id and path == d / f"{r.id}.md"  # given an ID, which is its file name
    assert not list(d.glob("*.tmp"))
    assert r.updated
    (d / "README.md").write_text("Not a review\n")
    assert review.all_reviews(tmp_path) == {COMMIT: path}  # index.md and README.md aren't reviews
    back = review.load(path)
    assert back.id == r.id and back.notes[0].anchor == Anchor("pcb", "footprint", "U3")
    # Saved again in place, keeping its ID and creation time.
    r.summary = "changed"
    assert review.save(tmp_path, r, path) == path
    back = review.load(path)
    assert (back.summary, back.created, back.id) == ("changed", "2026-11-13 10:00", r.id)


def test_note_times(tmp_path: Path, monkeypatch) -> None:
    """Written when first saved; edited when a later save changes it."""
    clock = iter(["2026-11-13 10:00", "2026-11-13 11:00", "2026-11-13 12:00", "2026-11-13 13:00"])
    monkeypatch.setattr(review, "now", lambda: next(clock))
    r = Review(commit=COMMIT, notes=[Note(title="A", body="one"), Note(title="B", body="two")])
    path = review.save(tmp_path, r)  # 10:00
    assert [(n.created, n.edited) for n in r.notes] == [("2026-11-13 10:00", "")] * 2

    r.notes[0].body = "one, changed"
    r.notes[1].body = "two  \n"  # the same once written: not an edit
    r.notes.append(Note(title="C"))
    review.save(tmp_path, r, path)  # 11:00
    back = review.load(path)
    assert [(n.title, n.created, n.edited) for n in back.notes] == [
        ("A", "2026-11-13 10:00", "2026-11-13 11:00"),
        ("B", "2026-11-13 10:00", ""),
        ("C", "2026-11-13 11:00", "")]

    # A fresh load (another session): anchors and tags count, and old times stay.
    back.notes[1].tags = ["todo"]
    review.save(tmp_path, back, path)  # 12:00
    again = review.load(path)
    assert [(n.created, n.edited) for n in again.notes] == [
        ("2026-11-13 10:00", "2026-11-13 11:00"),
        ("2026-11-13 10:00", "2026-11-13 12:00"),
        ("2026-11-13 11:00", "")]


def test_notes_from_before_times_were_kept(tmp_path: Path) -> None:
    """Notes in older files have no times; they aren't made up."""
    r = review.loads(f"---\ncommit: {COMMIT}\n---\n\n## A\n<!-- kigit-note {{\"id\": \"aa\"}} -->\nbody\n")
    d = tmp_path / "reviews"
    d.mkdir()
    path = d / "x.md"
    path.write_text(review.dumps(r))
    review.save(tmp_path, r, path)
    n = review.load(path).notes[0]
    assert (n.created, n.edited) == ("", "")


def test_index_lists_every_review(tmp_path: Path) -> None:
    old = Review(commit=PARENT, subject="first board", date="2025-01-10 12:00", author="Author B")
    review.save(tmp_path, old)
    new = sample()
    review.save(tmp_path, new)
    assert old.id != new.id
    index = (tmp_path / "reviews" / "index.md").read_text(encoding="utf-8")
    rows = [line for line in index.splitlines() if line.startswith("| [")]
    # Newest commit first; each row links its file, with the full hash.
    assert rows[0].startswith(f"| [{new.id}]({new.id}.md) | `{COMMIT}` | 2025-03-01 12:00 | Author B \\| L | ")
    assert "| 4 |" in rows[0]  # notes
    assert rows[1].startswith(f"| [{old.id}]({old.id}.md) | `{PARENT}` | 2025-01-10 12:00 | Author B | first board | 0 |")


def test_new_ids_are_unique(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "aaaaaaaa.md").write_text("x")
    ids = iter(["aaaaaaaa", "bbbbbbbb"])
    monkeypatch.setattr(review.secrets, "token_hex", lambda n: next(ids))
    assert review.new_id(tmp_path) == "bbbbbbbb"


def test_no_reviews_folder(tmp_path: Path) -> None:
    assert review.all_reviews(tmp_path) == {}


def test_save_image(tmp_path: Path) -> None:
    rel = review.save_image(tmp_path, b"\x89PNG fake", "image/png")
    assert review.ASSET_NAME.match(rel.split("/")[1]) and rel.startswith("assets/")
    assert (tmp_path / "reviews" / rel).read_bytes() == b"\x89PNG fake"
    assert review.save_image(tmp_path, b"\x89PNG fake", "image/png") == rel  # same image, same file
    with pytest.raises(ValueError):
        review.save_image(tmp_path, b"<svg/>", "image/svg+xml")


def test_anchor_seen() -> None:
    """Where an anchor was pinned; files without it still load."""
    gone = Anchor("pcb", "footprint", "U3", Seen(PARENT, COMMIT, "old"))
    assert gone.removed and gone.where == "Pinned in fedcba9 → 0123456 (removed there)"
    assert Anchor.from_dict(gone.to_dict()) == gone
    here = Anchor.from_dict({"tab": "sch", "kind": "net", "name": "GND", "seen": {"old": PARENT, "new": "", "side": "new"}})
    assert not here.removed and here.where.endswith("→ working tree (present there)")
    old_file = Anchor.from_dict({"tab": "pcb", "kind": "net", "name": "GND"})
    assert old_file.seen is None and not old_file.removed and old_file.where == ""
    assert "seen" not in old_file.to_dict()
    assert Anchor.from_dict({"tab": "pcb", "kind": "net", "name": "X", "seen": {"old": 1}}).seen is None
    assert Anchor.from_dict({"tab": "pcb", "kind": "net", "name": "X",
                             "seen": {"old": "", "new": "", "side": "sideways"}}).seen.side == "new"


def test_anchor_labels() -> None:
    assert Anchor("pcb", "net", "GND").label == "PCB net GND"
    assert Anchor("pcb", "net", "").label == "PCB net (no net)"
    assert Anchor("sch", "part", "R1").label == "Part R1"
    assert Anchor.from_dict({"tab": "pcb"}) is None


def test_preview_image_links() -> None:
    md = "a ![](assets/0123456789abcdef.png) b [x](https://e.com/assets/y)"
    assert rewrite_images(md, "k") == "a ![](/review-files/k/0123456789abcdef.png) b [x](https://e.com/assets/y)"


def test_autolink() -> None:
    text = ("see https://a.com/x. and www.b.org, [x](https://c.com) <https://d.com> `https://e.com`\n"
            "```\nhttps://f.com\n```\nmail me@www.g.com ![](https://h.com/p.png)")
    assert review.autolink(text) == (
        "see <https://a.com/x>. and [www.b.org](https://www.b.org), [x](https://c.com) <https://d.com> "
        "`https://e.com`\n```\nhttps://f.com\n```\nmail me@www.g.com ![](https://h.com/p.png)")


def test_link_markdown() -> None:
    assert review.link_markdown("", "example.com/ds.pdf") == "[https://example.com/ds.pdf](https://example.com/ds.pdf)"
    assert review.link_markdown("Data [v2]", "https://x.com/a (1).pdf") == r"[Data \[v2\]](https://x.com/a%20%281%29.pdf)"
    assert review.link_markdown("Buck", "decisions/buck.md") == "[Buck](decisions/buck.md)"
    assert review.link_markdown("Bench", "Bench test.md") == "[Bench](Bench%20test.md)"
    assert review.link_markdown("me", "mailto:a@b.c") == "[me](mailto:a@b.c)"
    assert review.link_markdown("top", "#r-abc") == "[top](#r-abc)"


def test_math() -> None:
    """$inline$ and $$block$$ LaTeX become MathML; prices, code and \\$ don't."""
    inline = review.to_html(r"Gain $G = \frac{R_f}{R_g}$ and $x$.")
    assert inline.count('<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline">') == 2
    assert "<mfrac>" in inline and "$" not in inline

    block = review.to_html("Divider:\n\n$$\nV_{out} = V_{in} \\frac{R_2}{R_1 + R_2}\n$$\n\nafter")
    assert '<math xmlns="http://www.w3.org/1998/Math/MathML" display="block">' in block
    assert "<p><math" not in block  # a block on its own, not inside a paragraph

    assert review.to_html("Costs $5 and $10.") == "<p>Costs $5 and $10.</p>\n"
    assert review.to_html("a $ b $ c") == "<p>a $ b $ c</p>\n"  # spaces inside: not math
    assert "<code>$x$</code>" in review.to_html("`$x$`")
    assert "<math" not in review.to_html("```\n$$x$$\n```")
    assert review.to_html(r"\$x$") == "<p>&#36;x$</p>\n"
    # Underscores and stars inside math aren't Markdown.
    assert "<em>" not in review.to_html("$a_1 * b_2 * c_3$")


def test_bad_math_is_shown_as_written() -> None:
    out = review.to_html(r"bad $\frac{$ end")
    assert '<code class="math-error" title="Not valid LaTeX: ' in out and r"$\frac{$</code>" in out


NEW = "1111111111111111111111111111111111111111"
NEW_PARENT = "2222222222222222222222222222222222222222"


def test_retarget_moves_anchors_pinned_in_the_commit() -> None:
    """A rebased commit's review: anchors pinned in its own comparison follow
    it, others follow the commits that were rewritten too."""
    other = "3333333333333333333333333333333333333333"
    r = Review(commit=COMMIT, parent=PARENT, notes=[
        Note(anchor=Anchor("pcb", "net", "GND", Seen(PARENT, COMMIT, "new"))),
        Note(anchor=Anchor("sch", "part", "R1", Seen(other, COMMIT, "old"))),
        Note(anchor=Anchor("sch", "part", "R2"))])
    review.retarget(r, NEW, NEW_PARENT, "reworded", "2025-03-02 12:00", "Author B", {COMMIT: NEW})
    assert (r.commit, r.parent, r.subject, r.date, r.author) == (NEW, NEW_PARENT, "reworded", "2025-03-02 12:00", "Author B")
    assert r.notes[0].anchor.seen == Seen(NEW_PARENT, NEW, "new")
    assert r.notes[1].anchor.seen == Seen(other, NEW, "old")
    assert r.notes[2].anchor.seen is None


def test_absorb_adds_summary_and_notes() -> None:
    target = Review(commit=NEW, summary="Squashed.", notes=[Note(title="A", id="aaaa0000")])
    other = Review(commit=COMMIT, subject="v2: add C1", summary="Decoupling.",
                   notes=[Note(title="B", id="aaaa0000", created="2026-11-01 10:00")])
    review.absorb(target, other, Path("x.md"))
    assert target.summary == "Squashed.\n\n*From 0123456 (v2: add C1):*\n\nDecoupling."
    assert [n.title for n in target.notes] == ["A", "B"]
    assert target.notes[1].id != "aaaa0000" and target.notes[1].created == "2026-11-01 10:00"
    assert target.absorbed == [Path("x.md")]


def test_move_and_merge(tmp_path: Path) -> None:
    """move() rewrites the review for its new commit, or merges it into that
    commit's review and removes its file (on that write)."""
    a = review.save(tmp_path, Review(commit=COMMIT, parent=PARENT, summary="First.", notes=[Note(title="One")]))
    moved = review.move(tmp_path, a, NEW, NEW_PARENT, "new subject", "2025-03-02 12:00", "Author B")
    assert moved == a
    r = review.load(a)
    assert (r.commit, r.parent, r.subject) == (NEW, NEW_PARENT, "new subject")
    assert set(review.all_reviews(tmp_path)) == {NEW}

    b = review.save(tmp_path, Review(commit=COMMIT, summary="Second.", notes=[Note(title="Two")]))
    into = review.move(tmp_path, b, NEW, NEW_PARENT, "new subject", "2025-03-02 12:00", "Author B")
    assert into == a and not b.exists()
    merged = review.load(a)
    assert [n.title for n in merged.notes] == ["One", "Two"]
    assert "First." in merged.summary and "Second." in merged.summary
    assert b.name not in (tmp_path / "reviews" / "index.md").read_text(encoding="utf-8")


def test_clean_tag() -> None:
    assert review.clean_tag("Needs Review") == "needs-review"
    assert review.clean_tag("#Power/3V3") == "power/3v3"
    assert review.clean_tag("  risk ") == "risk"
    assert review.clean_tag("a, b!") == "a-b"
    assert review.clean_tag("#") == ""


def test_known_tags(tmp_path: Path) -> None:
    """Built-in tags first, then the ones the project's reviews use."""
    assert review.known_tags(tmp_path) == review.TAGS
    review.save(tmp_path, Review(commit=COMMIT, notes=[Note(tags=["thermal", "risk"]), Note(tags=["emc"])]))
    assert review.known_tags(tmp_path) == review.TAGS + ["emc", "thermal"]
