"""Recent sessions for the landing page (sessions.py)."""

import json
from pathlib import Path

import pytest

from kigit_gui import sessions


@pytest.fixture(autouse=True)
def fresh(tmp_path: Path, monkeypatch) -> Path:
    file = tmp_path / "sessions.json"
    monkeypatch.setattr(sessions, "path", lambda: file)
    return file


def test_opened_and_compared(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        (d / "x.kicad_pcb").write_text("")
    sessions.opened(str(a), str(a / "x.kicad_pcb"), "alpha")
    sessions.opened(str(b), str(b / "x.kicad_pcb"), "beta")
    assert [s.name for s in sessions.load()] == ["beta", "alpha"]  # newest first
    sessions.compared(str(a / "x.kicad_pcb"), sessions.Compared("1" * 40, "LOCAL", "1111111", "LOCAL", "wip"))
    first = sessions.load()[0]
    assert first.name == "alpha" and first.last.new == "LOCAL" and first.last.subject == "wip"
    sessions.opened(str(a), str(a / "x.kicad_pcb"), "alpha")
    assert sessions.load()[0].last.old_label == "1111111"  # opening again keeps the last comparison
    assert len(sessions.load()) == 2  # one entry per board
    sessions.forget(str(b / "x.kicad_pcb"))
    assert [s.name for s in sessions.load()] == ["alpha"]


def test_gone_folders_and_broken_files(tmp_path: Path, fresh: Path) -> None:
    sessions.opened(str(tmp_path / "gone"), str(tmp_path / "gone" / "x.kicad_pcb"), "gone")
    assert not sessions.load()[0].exists
    data = json.loads(fresh.read_text())
    fresh.write_text(json.dumps(data + [{"no": "dir"}, "junk"]))
    assert len(sessions.load()) == 1  # broken entries are skipped
    fresh.write_text("{not json")
    assert sessions.load() == []


def test_at_most_max(tmp_path: Path) -> None:
    for i in range(sessions.MAX + 3):
        sessions.opened(str(tmp_path / str(i)), str(tmp_path / str(i) / "x.kicad_pcb"), str(i))
    assert len(sessions.load()) == sessions.MAX


def test_ago() -> None:
    now = 1_000_000_000.0
    assert sessions.ago(now - 10, now) == "just now"
    assert sessions.ago(now - 300, now) == "5 min ago"
    assert sessions.ago(now - 3 * 3600, now) == "3 h ago"
    assert sessions.ago(now - 30 * 3600, now) == "yesterday"
    assert sessions.ago(now - 4 * 86400, now) == "4 days ago"


def test_snapshot_paths(tmp_path: Path) -> None:
    import os
    import time

    board = tmp_path / "x.kicad_pcb"
    board.write_text("")
    assert sessions.thumb_key(str(board)) == sessions.thumb_key(str(tmp_path / "." / "x.kicad_pcb"))  # same file
    assert not sessions.thumb_fresh(str(board))  # none yet
    sessions.thumb(str(board)).parent.mkdir(parents=True)
    sessions.thumb(str(board)).write_bytes(b"png")
    assert sessions.thumb_fresh(str(board))
    later = time.time() + 10
    os.utime(board, (later, later))  # the board was saved again since
    assert not sessions.thumb_fresh(str(board))
