"""Mentions (mentions.py): links to a discussion or review, found where they
are, and which are news to you."""

from pathlib import Path

import pytest

from kigit_gui import mentions, review, threads
from kigit_gui.review import Note, Review

C1 = "1" * 40


@pytest.fixture(autouse=True)
def own_app_folder(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mentions, "_seen_path", lambda: tmp_path / "app" / "mentions-seen.json")


def test_found_in_discussions_and_reviews(tmp_path: Path) -> None:
    target = threads.start(tmp_path, "D4 shares LED2", "x", C1, "Author A", C1)
    link = threads.link_markdown(target)
    other = threads.start(tmp_path, "USB-C recessed", f"Related: {link}", C1, "Author B", C1)
    threads.add(tmp_path, other.id, "Author C", C1, f"Also {link} and itself {threads.link_markdown(other)}")
    r = Review(commit=C1, parent="0" * 40, subject="Rework the power", author="Author C",
               notes=[Note(title="LEDs", body=f"See {link}")])
    review.save(tmp_path, r)
    found = mentions.all_mentions(tmp_path)
    got = found[f"thread:{target.id}"]
    assert [(m.kind, m.author, m.where) for m in got][:2] == [("discussion", "Author B", "0"),
                                                              ("discussion", "Author C", "1")]
    assert ("review", "Rework the power", r.notes[0].id) in [(m.kind, m.title, m.where) for m in got]
    assert f"thread:{other.id}" not in found  # a discussion linking itself isn't a mention
    # A link to a review counts too.
    threads.add(tmp_path, target.id, "Author A", C1, f"Was in {review.review_link(r.subject, Path(r.id + '.md'))}")
    assert [m.source for m in mentions.all_mentions(tmp_path)[f"review:{r.id}"]] == [target.id]


def test_deleting_the_link_takes_the_mention(tmp_path: Path) -> None:
    target = threads.start(tmp_path, "D4", "x", C1, "Author A", C1)
    other = threads.start(tmp_path, "Other", f"See {threads.link_markdown(target)}", C1, "Author B", C1)
    assert mentions.all_mentions(tmp_path)[f"thread:{target.id}"]
    threads.edit(tmp_path, other.id, 0, "Author B", other.messages[0].time, "Never mind.")
    assert f"thread:{target.id}" not in mentions.all_mentions(tmp_path)


def test_news_for_me(tmp_path: Path) -> None:
    """Only mentions of discussions you opened or wrote in, by others, once;
    a project seen for the first time starts quiet."""
    mine = threads.start(tmp_path, "Mine", "x", C1, "Me", C1)
    theirs = threads.start(tmp_path, "Theirs", "x", C1, "Someone", C1)
    threads.start(tmp_path, "Old link", f"{threads.link_markdown(mine)}", C1, "Someone", C1)
    assert mentions.new_for_me(tmp_path, "Me") == []  # first look: what's there is old news
    threads.start(tmp_path, "New link", f"{threads.link_markdown(mine)} {threads.link_markdown(theirs)}", C1,
                  "Someone", C1)
    threads.start(tmp_path, "My own link", f"{threads.link_markdown(mine)}", C1, "Me", C1)
    new = mentions.new_for_me(tmp_path, "Me")
    assert [(m.title, m.target) for m in new] == [("New link", f"thread:{mine.id}")]  # not theirs, not mine
    assert mentions.new_for_me(tmp_path, "Me") == []  # told once
    threads.add(tmp_path, theirs.id, "Me", C1, "I'm in this one now")
    assert [m.title for m in mentions.new_for_me(tmp_path, "Me")] == ["New link"]  # theirs is mine now too
