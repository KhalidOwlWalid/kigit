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
        commit=COMMIT, parent=PARENT, subject="v2: add C1, move R2", created="2026-11-13 10:00",
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
    assert (back.commit, back.parent, back.subject, back.created) == (r.commit, r.parent, r.subject, r.created)
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
    assert path == tmp_path / "reviews" / "0123456-v2-add-c1-move-r2.md"
    assert not list((tmp_path / "reviews").glob("*.tmp"))
    assert r.updated
    (tmp_path / "reviews" / "README.md").write_text("Not a review\n")
    assert review.all_reviews(tmp_path) == {COMMIT: path}
    assert review.load(path).notes[0].anchor == Anchor("pcb", "footprint", "U3")
    # Saved again in place, keeping its creation time.
    r.summary = "changed"
    assert review.save(tmp_path, r, path) == path
    assert review.load(path).summary == "changed" and review.load(path).created == "2026-11-13 10:00"


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
