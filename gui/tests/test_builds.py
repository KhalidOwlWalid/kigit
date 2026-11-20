"""Builds (builds.py): batches of boards, a folder each in kigit-builds/."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from kigit_gui import builds

sys.path.insert(0, str(Path(__file__).parent))
from fixture_repo import make_fixture_repo  # noqa: E402


def test_new_list_update_delete(tmp_path: Path) -> None:
    project = make_fixture_repo(tmp_path / "repo")
    board = project / "demo.kicad_pcb"
    head = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert builds.all_builds(board) == []

    proto = builds.new(board, "  Proto   run ", 3)                       # the working tree
    assert proto.id == "proto-run" and proto.name == "Proto run" and proto.boards == 3
    assert proto.revision is None and proto.head == head
    saved = json.loads((project / "kigit-builds" / "proto-run" / "build.json").read_text(encoding="utf-8"))
    assert saved["version"] == 1 and saved["boards"] == 3 and saved["name"] == "Proto run"

    bulk = builds.new(board, "Proto run", 50, rev=head)                    # same name: its own folder
    assert bulk.id == "proto-run-2" and bulk.revision["hash"] == head and bulk.revision["subject"]
    assert {b.id for b in builds.all_builds(board)} == {"proto-run", "proto-run-2"}

    b = builds.update(board, "proto-run-2", name="December bulk", boards=48)
    assert (b.id, b.name, b.boards) == ("december-bulk", "December bulk", 48)  # the folder follows the name
    assert not (project / "kigit-builds" / "proto-run-2").exists()
    assert builds.get(board, "december-bulk").boards == 48
    assert builds.update(board, "december-bulk", name="December bulk").id == "december-bulk"  # same name: stays

    builds.delete(board, "proto-run")
    assert [x.id for x in builds.all_builds(board)] == ["december-bulk"]


def test_refused_and_broken(tmp_path: Path) -> None:
    board = tmp_path / "x.kicad_pcb"
    for name, n, why in (("", 1, "needs a name"), ("A", 0, "1 to"), ("A", "lots", "whole number")):
        with pytest.raises(builds.BuildError, match=why):
            builds.new(board, name, n)
    with pytest.raises(builds.BuildError):
        builds.get(board, "../../etc")                                     # never outside kigit-builds/
    with pytest.raises(builds.BuildError, match="no build"):
        builds.get(board, "nope")
    (tmp_path / "kigit-builds" / "broken").mkdir(parents=True)
    (tmp_path / "kigit-builds" / "broken" / "build.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "kigit-builds" / "empty").mkdir()
    builds.new(board, "Good", 2)
    assert [b.id for b in builds.all_builds(board)] == ["good"]          # the others are skipped, not fatal
