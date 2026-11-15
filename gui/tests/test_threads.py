"""Discussions: the file format and how their status follows the messages (threads.py)."""

from pathlib import Path

from kigit_gui import threads
from kigit_gui.review import Anchor, Seen

C1 = "1" * 40
C2 = "2" * 40


def test_a_discussion_from_open_to_accepted(tmp_path: Path) -> None:
    a = Anchor("pcb", "footprint", "R704", Seen("0" * 40, C1, "new"))
    t = threads.start(tmp_path, "R704 too close to <H1>", "Courtyard overlaps.\n\n- check it", C1, "Khalid", C1, a)
    assert t.status == "open" and (tmp_path / "reviews" / "threads" / f"{t.id}.md").exists()
    t = threads.add(tmp_path, t.id, "Ada", C2, "Moved it 1 mm.", "done")
    assert t.status == "done"
    t = threads.add(tmp_path, t.id, "Khalid", C2, "Still tight.", "reopened")
    assert t.status == "open"
    t = threads.add(tmp_path, t.id, "Ada", C2, "Why not 0402?")  # a reply doesn't change the status
    assert t.status == "open"
    threads.add(tmp_path, t.id, "Ada", C2, "Done properly now.", "done")
    t = threads.add(tmp_path, t.id, "Khalid", C2, "", "accepted")
    assert t.status == "accepted"

    again = threads.all_threads(tmp_path)[0]
    assert again.title == "R704 too close to <H1>" and again.anchor == a and again.commit == C1 and again.by == "Khalid"
    assert [(m.author, m.kind, m.text) for m in again.messages] == [
        ("Khalid", "comment", "Courtyard overlaps.\n\n- check it"), ("Ada", "done", "Moved it 1 mm."),
        ("Khalid", "reopened", "Still tight."), ("Ada", "comment", "Why not 0402?"),
        ("Ada", "done", "Done properly now."), ("Khalid", "accepted", "")]
    assert again.messages[1].head == C2


def test_readable_file(tmp_path: Path) -> None:
    t = threads.start(tmp_path, "Check C1", "Value?", C1, "Ada <a@b>", C1)
    threads.add(tmp_path, t.id, "Khalid", C2, "Fixed.", "done")
    text = threads.path_of(tmp_path, t).read_text()
    assert f"**Ada <a@b>** · {t.opened} · at 1111111" in text  # a line for people
    assert "· marked done at 2222222" in text
    assert "<!-- kigit-msg" in text and "\\u003ca@b\\u003e" in text  # a name can't end the comment
    assert threads.loads(text).messages[0].author == "Ada <a@b>"  # read back as written


def test_order_and_counts(tmp_path: Path) -> None:
    a = threads.start(tmp_path, "a", "", C1, "x", C1)
    b = threads.start(tmp_path, "b", "", C1, "x", C1)
    c = threads.start(tmp_path, "c", "", C1, "x", C1)
    threads.add(tmp_path, a.id, "x", C1, "", "accepted")
    threads.add(tmp_path, b.id, "x", C1, "", "done")
    assert [t.title for t in threads.all_threads(tmp_path)] == ["c", "b", "a"]  # attention first, accepted last
    assert threads.counts(threads.all_threads(tmp_path)) == {"open": 1, "done": 1, "accepted": 1}
    (threads.folder(tmp_path) / "junk.md").write_text("not a discussion")
    assert len(threads.all_threads(tmp_path)) == 3  # other files are skipped
    assert threads.all_threads(tmp_path / "nowhere") == []
