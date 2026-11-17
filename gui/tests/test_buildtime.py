"""The 3D build progress estimate (buildtime.py)."""

from pathlib import Path

from kigit_gui import buildtime


def test_estimate_from_the_last_builds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(buildtime, "FILE", tmp_path / "times.json")
    board = str(tmp_path / "b.kicad_pcb")
    assert buildtime.estimate(board) is None  # first time: no idea
    buildtime.record(board, 20)
    assert buildtime.estimate(board) == 20
    buildtime.record(board, 30)
    assert buildtime.estimate(board) == 25  # averaged with the last one
    assert buildtime.estimate(board, n=3) == 25 * 1.5  # three at once: each slower
    buildtime.record(board, 1)  # too quick to mean anything
    assert buildtime.estimate(board) == 25
    (tmp_path / "times.json").write_text("not json", encoding="utf-8")
    assert buildtime.estimate(board) is None  # a broken file is just forgotten


def test_progress_text() -> None:
    assert buildtime.progress(5, None) == (None, "5 s so far · the first build of this board, so no estimate yet")
    value, text = buildtime.progress(10, 20)
    assert value == 0.5 and text == "10 s of about 20 s (last time)"
    value, text = buildtime.progress(30, 20)
    assert value == 0.97 and "taking longer than last time" in text  # never "done" before it is
