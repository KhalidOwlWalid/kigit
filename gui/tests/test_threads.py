"""Discussions: the file format and how their status follows the messages (threads.py)."""

from pathlib import Path

import pytest

from kigit_gui import threads
from kigit_gui.review import Anchor, Seen

C1 = "1" * 40
C2 = "2" * 40


def test_a_discussion_from_open_to_accepted(tmp_path: Path) -> None:
    a = Anchor("pcb", "footprint", "R704", Seen("0" * 40, C1, "new"))
    t = threads.start(tmp_path, "R704 too close to <H1>", "Courtyard overlaps.\n\n- check it", C1, "Author A", C1, a)
    assert t.status == "open" and (tmp_path / "reviews" / "threads" / f"{t.id}.md").exists()
    t = threads.add(tmp_path, t.id, "Author B", C2, "Moved it 1 mm.", "done")
    assert t.status == "done"
    t = threads.add(tmp_path, t.id, "Author A", C2, "Still tight.", "reopened")
    assert t.status == "open"
    t = threads.add(tmp_path, t.id, "Author B", C2, "Why not 0402?")  # a reply doesn't change the status
    assert t.status == "open"
    threads.add(tmp_path, t.id, "Author B", C2, "Done properly now.", "done")
    t = threads.add(tmp_path, t.id, "Author A", C2, "", "accepted")
    assert t.status == "accepted"

    again = threads.all_threads(tmp_path)[0]
    assert again.title == "R704 too close to <H1>" and again.anchor == a and again.commit == C1 and again.by == "Author A"
    assert [(m.author, m.kind, m.text) for m in again.messages] == [
        ("Author A", "comment", "Courtyard overlaps.\n\n- check it"), ("Author B", "done", "Moved it 1 mm."),
        ("Author A", "reopened", "Still tight."), ("Author B", "comment", "Why not 0402?"),
        ("Author B", "done", "Done properly now."), ("Author A", "accepted", "")]
    assert again.messages[1].head == C2


def test_readable_file(tmp_path: Path) -> None:
    t = threads.start(tmp_path, "Check C1", "Value?", C1, "Author B <a@b>", C1)
    threads.add(tmp_path, t.id, "Author A", C2, "Fixed.", "done")
    text = threads.path_of(tmp_path, t).read_text(encoding="utf-8")
    assert f"**Author B <a@b>** · {t.opened} · at 1111111" in text  # a line for people
    assert "· marked done at 2222222" in text
    assert "<!-- kigit-msg" in text and "\\u003ca@b\\u003e" in text  # a name can't end the comment
    assert threads.loads(text).messages[0].author == "Author B <a@b>"  # read back as written


def test_order_and_counts(tmp_path: Path) -> None:
    a = threads.start(tmp_path, "a", "", C1, "x", C1)
    b = threads.start(tmp_path, "b", "", C1, "x", C1)
    c = threads.start(tmp_path, "c", "", C1, "x", C1)
    threads.add(tmp_path, a.id, "x", C1, "", "accepted")
    threads.add(tmp_path, b.id, "x", C1, "", "done")
    assert [t.title for t in threads.all_threads(tmp_path)] == ["c", "b", "a"]  # attention first, accepted last
    assert threads.counts(threads.all_threads(tmp_path)) == {"open": 1, "done": 1, "accepted": 1}
    (threads.folder(tmp_path) / "junk.md").write_text("not a discussion", encoding="utf-8")
    assert len(threads.all_threads(tmp_path)) == 3  # other files are skipped
    assert threads.all_threads(tmp_path / "nowhere") == []


def test_edit_your_own_message(tmp_path: Path) -> None:
    """Only the author can change a message's text: in place, marked edited,
    everything else (author, time, kind, status) as it was."""
    t = threads.start(tmp_path, "Check C1", "Too clsoe.", C1, "Author A", C1)
    t = threads.add(tmp_path, t.id, "Author B", C2, "Moved it.", "done")
    first = t.messages[0]
    with pytest.raises(ValueError):
        threads.edit(tmp_path, t.id, 0, "Author B", first.time, "not mine")  # someone else's
    with pytest.raises(ValueError):
        threads.edit(tmp_path, t.id, 0, "Author A", "1999-01-01 00:00", "x")  # not the message shown
    with pytest.raises(ValueError):
        threads.edit(tmp_path, t.id, 5, "Author A", first.time, "x")  # gone
    with pytest.raises(ValueError):
        threads.edit(tmp_path, t.id, 0, "Author A", first.time, "  ")  # a comment needs text
    t = threads.edit(tmp_path, t.id, 0, "Author A", first.time, "Too close.")
    m = t.messages[0]
    assert (m.text, m.author, m.time, m.kind) == ("Too close.", "Author A", first.time, "comment") and m.edited
    assert t.status == "done" and t.messages[1].text == "Moved it." and not t.messages[1].edited
    text = threads.path_of(tmp_path, t).read_text(encoding="utf-8")
    assert f"· edited {m.edited}" in text and '"edited": ' in text  # for people, and for kigit
    again = threads.loads(text)
    assert again.messages[0].edited == m.edited and again.messages[0].text == "Too close."
    threads.edit(tmp_path, t.id, 1, "Author B", t.messages[1].time, "")  # a status change can lose its text
    assert threads.all_threads(tmp_path)[0].messages[1].text == ""


def test_delete_your_own_comment(tmp_path: Path) -> None:
    t = threads.start(tmp_path, "Check C1", "First.", C1, "Author A", C1)
    t = threads.add(tmp_path, t.id, "Author A", C2, "Oops, wrong board.")
    t = threads.add(tmp_path, t.id, "Author B", C2, "Done.", "done")
    with pytest.raises(ValueError):
        threads.delete(tmp_path, t.id, 2, "Author A", t.messages[2].time)  # someone else's
    with pytest.raises(ValueError):
        threads.delete(tmp_path, t.id, 2, "Author B", t.messages[2].time)  # a status change stays
    t = threads.delete(tmp_path, t.id, 1, "Author A", t.messages[1].time)
    assert [m.text for m in t.messages] == ["First.", "Done."] and t.status == "done"
    assert [m.text for m in threads.all_threads(tmp_path)[0].messages] == ["First.", "Done."]
    with pytest.raises(ValueError):  # the same index is now another message
        threads.delete(tmp_path, t.id, 1, "Author A", t.messages[0].time)


def test_discussion_links(tmp_path: Path) -> None:
    """A link to a discussion is Markdown to its file; links to ones that are
    gone are found."""
    t = threads.start(tmp_path, "C1 [placement]", "x", C1, "Author A", C1)
    link = threads.link_markdown(t)
    assert link == f"[C1 placement](threads/{t.id}.md)"
    text = f"See {link}, again {link}, and [old](../threads/deadbeef.md) [x](threads/nothex.md)."
    assert threads.linked(text) == [t.id, "deadbeef"]
    assert threads.exists(tmp_path, t.id) and not threads.exists(tmp_path, "deadbeef")
    assert threads.missing(tmp_path, text) == ["deadbeef"]


def test_repoint(tmp_path: Path) -> None:
    """Whoever opened a discussion can change what it's about; it's said in
    the chat, and the status stays."""
    y1 = Anchor("pcb", "footprint", "Y1", Seen("0" * 40, C1, "new"))
    t = threads.start(tmp_path, "Crystal", "SMD instead?", C1, "Author A", C1, y1)
    t = threads.add(tmp_path, t.id, "Author B", C2, "Done.", "done")
    x1 = Anchor("pcb", "footprint", "X1", Seen("0" * 40, C2, "new"))
    with pytest.raises(ValueError):
        threads.repoint(tmp_path, t.id, "Author B", C2, [x1])  # not the opener
    t = threads.repoint(tmp_path, t.id, "Author A", C2, [x1])
    assert t.anchor.name == "X1" and t.status == "done"
    assert (t.messages[-1].kind, t.messages[-1].text) == ("repointed", "Now about Footprint X1 (was Footprint Y1).")
    again = threads.all_threads(tmp_path)[0]
    assert again.anchor.name == "X1" and again.messages[-1].kind == "repointed"
    same = Anchor("pcb", "footprint", "X1", Seen(C1, C2, "new"))  # the same part, pinned elsewhere
    assert len(threads.repoint(tmp_path, t.id, "Author A", C2, [same]).messages) == 3  # nothing to say
    t = threads.repoint(tmp_path, t.id, "Author A", C2, [])
    assert t.anchor is None and t.messages[-1].text == "Now about the commit in general (was Footprint X1)."


def test_about_several_things(tmp_path: Path) -> None:
    """A discussion can be about several parts; the first stays in "anchor"
    (what older kigit reads), the rest in "more"."""
    y1 = Anchor("pcb", "footprint", "Y1")
    c5, c6 = Anchor("sch", "part", "C5"), Anchor("sch", "part", "C6")
    t = threads.start(tmp_path, "Crystal", "x", C1, "Author A", C1, y1)
    t = threads.repoint(tmp_path, t.id, "Author A", C1, [y1, c5, c6, Anchor("sch", "part", "C5")])  # C5 once
    assert [a.name for a in t.anchors] == ["Y1", "C5", "C6"]
    assert t.messages[-1].text == "Now about Footprint Y1, Part C5, Part C6 (was Footprint Y1)."
    text = threads.path_of(tmp_path, t).read_text(encoding="utf-8")
    assert '"name": "Y1"' in text.split("more:")[0] and "more: [" in text
    assert [a.name for a in threads.all_threads(tmp_path)[0].anchors] == ["Y1", "C5", "C6"]


def test_rename(tmp_path: Path) -> None:
    t = threads.start(tmp_path, "Crystl", "x", C1, "Author A", C1)
    with pytest.raises(ValueError):
        threads.rename(tmp_path, t.id, "Author B", C1, "Crystal")  # not the opener
    with pytest.raises(ValueError):
        threads.rename(tmp_path, t.id, "Author A", C1, "   ")  # needs a title
    t = threads.rename(tmp_path, t.id, "Author A", C1, "Crystal\nfootprint")
    assert t.title == "Crystal footprint" and threads.all_threads(tmp_path)[0].title == "Crystal footprint"
    assert (t.messages[-1].kind, t.messages[-1].text) == ("renamed", "Was: Crystl") and t.status == "open"
    assert len(threads.rename(tmp_path, t.id, "Author A", C1, "Crystal footprint").messages) == 2  # same: nothing
