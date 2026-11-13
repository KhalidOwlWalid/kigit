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
        commit=COMMIT, parent=PARENT, subject="v2: add C1, move R2", date="2025-03-01 12:00", author="Ada | L",
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
    d = tmp_path / ".reviews"
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
    d = tmp_path / ".reviews"
    d.mkdir()
    path = d / "x.md"
    path.write_text(review.dumps(r))
    review.save(tmp_path, r, path)
    n = review.load(path).notes[0]
    assert (n.created, n.edited) == ("", "")


def test_index_lists_every_review(tmp_path: Path) -> None:
    old = Review(commit=PARENT, subject="first board", date="2025-01-10 12:00", author="Ada")
    review.save(tmp_path, old)
    new = sample()
    review.save(tmp_path, new)
    assert old.id != new.id
    index = (tmp_path / ".reviews" / "index.md").read_text()
    rows = [line for line in index.splitlines() if line.startswith("| [")]
    # Newest commit first; each row links its file, with the full hash.
    assert rows[0].startswith(f"| [{new.id}]({new.id}.md) | `{COMMIT}` | 2025-03-01 12:00 | Ada \\| L | ")
    assert "| 4 |" in rows[0]  # notes
    assert rows[1].startswith(f"| [{old.id}]({old.id}.md) | `{PARENT}` | 2025-01-10 12:00 | Ada | first board | 0 |")


def test_new_ids_are_unique(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".reviews").mkdir()
    (tmp_path / ".reviews" / "aaaaaaaa.md").write_text("x")
    ids = iter(["aaaaaaaa", "bbbbbbbb"])
    monkeypatch.setattr(review.secrets, "token_hex", lambda n: next(ids))
    assert review.new_id(tmp_path) == "bbbbbbbb"


def test_no_reviews_folder(tmp_path: Path) -> None:
    assert review.all_reviews(tmp_path) == {}


def test_save_image(tmp_path: Path) -> None:
    rel = review.save_image(tmp_path, b"\x89PNG fake", "image/png")
    assert review.ASSET_NAME.match(rel.split("/")[1]) and rel.startswith("assets/")
    assert (tmp_path / ".reviews" / rel).read_bytes() == b"\x89PNG fake"
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
