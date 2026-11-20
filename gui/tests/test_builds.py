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


def test_boards_are_made_when_started(tmp_path: Path) -> None:
    board = tmp_path / "x.kicad_pcb"
    b = builds.new(board, "Run", 3).id
    assert builds.boards(board, b) == []
    one = builds.start_board(board, b)                  # the next one: #1
    assert one["board"] == 1 and one["placed"] == [] and one["status"] == "in progress"
    assert builds.start_board(board, b, 3)["board"] == 3
    assert builds.start_board(board, b)["board"] == 2   # the first not started
    assert builds.start_board(board, b, 2)["board"] == 2  # again: the same one
    with pytest.raises(builds.BuildError, match="#1 to #3"):
        builds.start_board(board, b, 4)
    assert [x["board"] for x in builds.boards(board, b)] == [1, 2, 3]
    assert (tmp_path / "kigit-builds" / b / "boards" / "2.json").exists()
    builds.delete_board(board, b, 2)
    assert [x["board"] for x in builds.boards(board, b)] == [1, 3]
    with pytest.raises(builds.BuildError, match="isn't started"):
        builds.get_board(board, b, 2)
    builds.update(board, b, name="Renamed run")           # boards move with the build's folder
    assert [x["board"] for x in builds.boards(board, "renamed-run")] == [1, 3]


def test_placing_takes_from_the_inventory(tmp_path: Path) -> None:
    """Placing a part takes one out of your inventory (if it's in it);
    taking it off puts back what was taken; a board is done when all its
    parts (not DNP) are placed."""
    from kigit_gui import bom, inventory
    board = tmp_path / "x.kicad_pcb"
    b = builds.new(board, "Run", 2).id
    shelf = tmp_path / "inventory.csv"
    shelf.write_text("MPN,Kind,Value,Package,Quantity\n"
                     ",resistor,10k,0603,10\n"
                     "STM32F103C8T6,,,,1\n", encoding="utf-8")
    data = {"field_names": {}, "lines": [
        {"refs": ["R1", "R2"], "value": "10k", "footprint": "R", "package": "0603", "kind": "resistor", "mpn": ""},
        {"refs": ["U1"], "value": "MCU", "footprint": "Q", "package": "LQFP", "kind": "other", "mpn": "STM32F103C8T6"},
        {"refs": ["J1"], "value": "Conn", "footprint": "J", "package": "", "kind": "other", "mpn": ""},  # not in it
        {"refs": ["C9"], "value": "4p", "footprint": "C", "package": "0603", "kind": "capacitor", "dnp": True},
    ]}
    builds.start_board(board, b, 1)
    inventory.remember(shelf)
    try:
        qty = lambda ids: inventory.read(shelf).find(ids)[0].qty  # noqa: E731
        r = bom.place_parts(board, b, data, 1, ["R1", "R2", "C9", "Z9"], True)  # C9 is DNP, Z9 isn't on the BOM
        assert r["placed"] == ["R1", "R2"] and set(r["taken"]) == {"R1", "R2"}
        assert qty({"kind": "resistor", "value": "10k", "package": "0603"}) == 8
        r = bom.place_parts(board, b, data, 1, ["R1"], True)                    # already placed: nothing more
        assert qty({"kind": "resistor", "value": "10k", "package": "0603"}) == 8
        r = bom.place_parts(board, b, data, 1, ["J1"], True)                    # not in the inventory: placed, nothing taken
        assert "J1" in r["placed"] and "J1" not in r["taken"] and len(inventory.read(shelf).rows) == 2
        assert r["status"] == "in progress"
        r = bom.place_parts(board, b, data, 1, ["U1"], True)                    # the last one: done
        assert r["status"] == "done" and r["finished"] and qty({"mpn": "STM32F103C8T6"}) == 0
        r = bom.place_parts(board, b, data, 1, ["U1", "R2"], False)             # taken off: back in, in progress again
        assert r["status"] == "in progress" and not r["finished"]
        assert qty({"mpn": "STM32F103C8T6"}) == 1 and qty({"kind": "resistor", "value": "10k", "package": "0603"}) == 9
        assert builds.get_board(board, b, 1)["placed"] == ["J1", "R1"]
        # No inventory chosen: placing is still kept.
        inventory.remember(None)
        assert "U1" in bom.place_parts(board, b, data, 1, ["U1"], True)["placed"]
    finally:
        inventory.remember(None)
