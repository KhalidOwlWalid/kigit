"""The notebook (notebook.py): your notes in reviews/, with pins, search,
notes about a part, and the daily log."""

from datetime import datetime
from pathlib import Path

from kigit_gui import notebook, review, threads
from kigit_gui.review import Anchor, Review

C2 = Anchor("pcb", "footprint", "C2")


def vault(tmp_path: Path) -> Path:
    """Like an Obsidian vault in reviews/: folders in folders, pictures, kigit's own files."""
    r = tmp_path / "reviews"
    (r / "OwlPCB_Notes" / "System Implementation").mkdir(parents=True)
    (r / "OwlPCB_Notes" / "images").mkdir()
    (r / "OwlPCB_Notes" / "images" / "shot.png").write_bytes(b"png")
    (r / "OwlPCB_Notes" / ".obsidian").mkdir()
    (r / "OwlPCB_Notes" / ".obsidian" / "app.md").write_text("x")
    (r / "OwlPCB_Notes" / "Logs.md").write_text("## 12th October 2026\n- Worked on [[USB-UART]]\n")
    (r / "OwlPCB_Notes" / "System Implementation" / "USB-UART.md").write_text(
        "# USB-UART\n\nThe CH340 needs C2 close to its VCC pin.\n")
    review.save(tmp_path, Review(commit="a" * 40, subject="x", summary="y"))
    threads.start(tmp_path, "T", "x", "a" * 40, "A", "a" * 40)
    return r


def test_tree_is_the_vault(tmp_path: Path) -> None:
    vault(tmp_path)
    t = notebook.tree(tmp_path)
    assert [f.path.name for f in t.folders] == ["OwlPCB_Notes"]  # not threads/, assets/ or review files
    owl = t.folders[0]
    assert [f.path.name for f in owl.folders] == ["System Implementation"]  # not images/ or .obsidian
    assert [p.name for p in owl.notes] == ["Logs.md"] and t.notes == []
    assert [p.name for p in notebook.all_notes(tmp_path)] == ["Logs.md", "USB-UART.md"]
    (tmp_path / "reviews" / "Empty").mkdir()  # a folder you just made: shown
    assert "Empty" in [f.path.name for f in notebook.tree(tmp_path).folders]


def test_pins_round_trip_and_leave_your_text_alone(tmp_path: Path) -> None:
    r = vault(tmp_path)
    path = r / "OwlPCB_Notes" / "System Implementation" / "USB-UART.md"
    before = path.read_text()
    n = notebook.read(path)
    assert n.title == "USB-UART" and n.pins == []
    n.pins = [C2]
    notebook.write(n)
    text = path.read_text()
    assert text.startswith(before.rstrip("\n")) and text.rstrip().endswith("-->") and "kigit-pins" in text
    again = notebook.read(path)
    assert again.text.rstrip() == before.rstrip() and [a.name for a in again.pins] == ["C2"]
    again.pins = []
    notebook.write(again)
    assert path.read_text() == before  # no pins: no comment


def test_new_rename_and_folders(tmp_path: Path) -> None:
    r = vault(tmp_path)
    n = notebook.new_note(r, "Boot: pin / strap?", [C2], "BOOT0 low.")
    assert n.path.name == "Boot  pin   strap .md" or n.path.parent == r  # made safe for a file name
    assert notebook.read(n.path).text.startswith("# Boot: pin / strap?") and notebook.read(n.path).pins
    other = notebook.new_note(r, "Boot: pin / strap?")
    assert other.path != n.path  # unique
    n = notebook.rename(n, "Boot pin")
    assert n.path.name == "Boot pin.md" and notebook.read(n.path).text.startswith("# Boot pin\n")
    assert [a.name for a in notebook.read(n.path).pins] == ["C2"]  # kept
    d = notebook.new_folder(r / "OwlPCB_Notes", "Power")
    assert d.is_dir() and d.name == "Power"


def test_search_and_about(tmp_path: Path) -> None:
    r = vault(tmp_path)
    pinned = notebook.new_note(r, "Decoupling", [C2])
    assert [n.title for n in notebook.search(tmp_path, "ch340 vcc")] == ["USB-UART"]
    found = notebook.about(tmp_path, Anchor("sch", "part", "C2"))  # the same part, from the schematic
    assert [(n.title, why) for n, why in found] == [("Decoupling", "pinned"), ("USB-UART", "mentions")]
    assert notebook.about(tmp_path, Anchor("pcb", "footprint", "C")) == []  # a whole word only
    assert pinned


def test_log(tmp_path: Path) -> None:
    r = vault(tmp_path)
    folder = r / "OwlPCB_Notes"
    when = datetime(2026, 11, 16, 9, 5)
    notebook.log(folder, "Swapped the crystal", when, C2, "b" * 40)
    notebook.log(folder, "Checked the load caps", when.replace(hour=10, minute=0))
    text = (folder / "Logs.md").read_text()
    assert text.startswith("## 12th October 2026\n- Worked on [[USB-UART]]\n")  # yours, untouched
    assert "## 16th November 2026\n- 09:05 Swapped the crystal (Footprint C2 · at bbbbbbb)\n" \
           "- 10:00 Checked the load caps\n" in text
    notebook.log(r, "First line", datetime(2026, 11, 1))
    assert (r / "Logs.md").read_text() == "## 1st November 2026\n- 00:00 First line\n"
    assert notebook.log_heading(datetime(2026, 11, 22)) == "## 22nd November 2026"
    assert notebook.log_heading(datetime(2026, 11, 13)) == "## 13th November 2026"
