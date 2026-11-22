"""The inventory (inventory.py): your CSV, anywhere; kigit reads it, finds
BOM lines in it, and changes only Quantity (and adds rows)."""

import json
from pathlib import Path

import pytest

from kigit_gui import bom, inventory

CSV = ("MPN,Manufacturer,LCSC,Mouser,Kind,Value,Package,Quantity,Location,Notes,My own column\r\n"
       "RC0603FR-0710KL,YAGEO,C98220,,resistor,10k,0603,400,Drawer 2,,keep me\r\n"
       "STM32F103C8T6,STMicroelectronics,,511-STM32F103C8T6,,,,6,Box A,\"two have bent pins, careful\",x\r\n"
       ",,,,capacitor,100nF,0603,\"1,200\",Drawer 1,mixed brands,\r\n"
       ",,,,resistor,4K7,0603,50,,,\r\n"
       ",,,,,,,3,,a row with nothing to say what it is,\r\n"
       "STM32F103C8T6,,,,,,,1,,the same part again,\r\n"
       "LTST-C191KEKT,,,,,,,lots,,,\r\n")


def write(tmp_path: Path, text: str = CSV) -> Path:
    p = tmp_path / "shelf" / "inventory.csv"
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(text.encode("utf-8"))
    return p


def test_reads_your_csv(tmp_path: Path) -> None:
    inv = inventory.read(write(tmp_path))
    assert [r.label() for r in inv.rows] == ["RC0603FR-0710KL", "STM32F103C8T6", "capacitor 100nF 0603", "resistor 4K7 0603"]
    assert inv.rows[2].qty == 1200 and inv.rows[0].ids["location"] == "Drawer 2"
    assert len(inv.problems) == 3  # nothing to identify it; the same part twice; a quantity that isn't a number
    assert "line 6" in inv.problems[0] and "line 7" in inv.problems[1] and "line 8" in inv.problems[2]
    assert inventory.read(write(tmp_path, "Part;Qty;MPN\nx;5;ABC\n")).rows[0].qty == 5  # ; separated, Qty


def test_finding_parts(tmp_path: Path) -> None:
    inv = inventory.read(write(tmp_path))
    row, by = inv.find({"mpn": "rc0603fr-07 10kl"})                  # part numbers as letters and digits
    assert row.qty == 400 and by == "mpn"
    assert inv.find({"mouser": "511-STM32F103C8T6"})[1] == "mouser"
    assert inv.find({"lcsc": "C98220", "mpn": "OTHER"})[1] == "lcsc"  # an MPN that isn't there doesn't stop the LCSC one
    # Passives without a part number: kind + value + package, values written any way.
    assert inv.find({"kind": "capacitor", "value": "100n", "package": "0603"})[0].qty == 1200
    assert inv.find({"kind": "resistor", "value": "4k7", "package": "0603"})[0].qty == 50
    assert inv.find({"kind": "resistor", "value": "10k", "package": "0603"})[0].qty == 400
    assert inv.find({"kind": "resistor", "value": "10k", "package": "0402"})[0] is None
    assert inv.find({"kind": "other", "value": "DEMO", "package": "SOIC-8"})[0] is None  # only passives by value
    for a, b in (("10kΩ", "10k"), ("10 k ohm", "10k"), ("4R7", "4.7"), ("100R", "100"), ("1uF", "1u"), ("µ1", "u1")):
        assert inventory.norm_value(a) == b
    # However it's written, the same value: 5.1k = 5k1 = 5k1R = 5.1kR, 1.8nF = 1n8 = 1n8F, 10k = 10kR.
    for same in (("5.1k", "5k1", "5k1R", "5.1kR", "5K1"), ("1.8nF", "1n8", "1n8F", "1.8n"), ("10k", "10kR", "10K"),
                 ("4.7uF", "4u7", "4u7F", "4µ7F"), ("100", "100R", "100Ω")):
        assert len({inventory.norm_value(v) for v in same}) == 1, same


def test_changes_touch_only_quantity(tmp_path: Path) -> None:
    p = write(tmp_path)
    inv = inventory.change(p, deltas=[({"mpn": "RC0603FR-0710KL"}, -3)],
                           sets=[({"kind": "capacitor", "value": "100n", "package": "0603"}, 1100)])
    text = p.read_bytes().decode("utf-8")  # as written (read_text would turn \r\n into \n)
    assert "RC0603FR-0710KL,YAGEO,C98220,,resistor,10k,0603,397,Drawer 2,,keep me\r\n" in text
    assert ",,,,capacitor,100nF,0603,1100,Drawer 1,mixed brands,\r\n" in text
    assert '"two have bent pins, careful",x' in text                 # your columns and quoting stay
    assert text.count("\r\n") == CSV.count("\r\n")                   # Windows line endings stay
    assert (p.parent / "inventory.csv.bak").read_bytes().decode("utf-8") == CSV  # the old one kept
    assert inv.find({"mpn": "RC0603FR-0710KL"})[0].qty == 397
    # A part new to you: a row with what's known about it; never below 0.
    inv = inventory.change(p, deltas=[({"mpn": "NEW-1", "kind": "other"}, 5), ({"mpn": "RC0603FR-0710KL"}, -1000)],
                           add_fields={"mpn:NEW1": {"manufacturer": "ACME"}})
    assert inv.find({"mpn": "NEW-1"})[0].qty == 5 and inv.find({"mpn": "NEW-1"})[0].ids["manufacturer"] == "ACME"
    assert "kind" not in inv.find({"mpn": "NEW-1"})[0].ids  # an IC's kind isn't written (only a passive's says what it is)
    assert inv.find({"mpn": "RC0603FR-0710KL"})[0].qty == 0
    # Edited outside kigit in between: the change goes onto what's on disk now.
    p.write_bytes(p.read_bytes().replace(b"0603,0,Drawer 2", b"0603,40,Drawer 2"))
    assert inventory.change(p, deltas=[({"mpn": "RC0603FR-0710KL"}, 2)]).find({"mpn": "RC0603FR-0710KL"})[0].qty == 42
    with pytest.raises(inventory.InventoryError, match="nothing to find it by"):
        inventory.change(p, deltas=[({"kind": "other", "value": "X"}, 1)])


def test_new_file_and_remembering_it(tmp_path: Path) -> None:
    p = tmp_path / "parts.csv"
    inv = inventory.create(p)
    assert inv.rows == [] and p.read_text(encoding="utf-8").startswith("MPN,Manufacturer,LCSC,Mouser,Digi-Key,Kind,")
    with pytest.raises(inventory.InventoryError, match="exists already"):
        inventory.create(p)
    with pytest.raises(inventory.InventoryError, match=".csv"):
        inventory.create(tmp_path / "parts.txt")
    with pytest.raises(inventory.InventoryError, match="no Quantity"):
        inventory.read(write(tmp_path, "MPN,Location\nX,A\n"))
    # Only where it is (and a copy) lives in kigit's app folder (conftest points that at a temp folder).
    assert inventory.current() == (None, "none")
    inventory.remember(p, inv)
    settings = json.loads(inventory._settings().read_text(encoding="utf-8"))  # noqa: SLF001
    assert settings["path"] == str(p) and settings["copy"]["rows"] == []
    assert inventory.current()[0].path == p
    p.unlink()                                                       # moved away: said, not made again
    inv, why = inventory.current()
    assert inv is None and "isn't there" in why and not p.exists()
    inventory.remember(None)
    assert inventory.location() is None


def test_bom_lines_in_the_inventory(tmp_path: Path) -> None:
    """A BOM line is found by its part numbers as shown (drafts count), else
    as a passive by value and package; DNP lines are left out."""
    inv = inventory.read(write(tmp_path))
    data = {"field_names": {}, "lines": [
        {"refs": ["R1", "R2"], "value": "10k", "footprint": "R_0603", "package": "0603", "kind": "resistor", "mpn": ""},
        {"refs": ["U1"], "value": "MCU", "footprint": "LQFP", "package": "LQFP-48", "kind": "other", "mpn": ""},
        {"refs": ["U2"], "value": "LDO", "footprint": "SOT", "package": "SOT-23", "kind": "other", "mpn": "NOPE"},
        {"refs": ["C9"], "value": "4p", "footprint": "C", "package": "0603", "kind": "capacitor", "dnp": True},
    ]}
    board = tmp_path / "x.kicad_pcb"
    state = bom.set_draft(board, bom.line_key(data["lines"][1]), "MPN", "STM32F103C8T6")  # typed, not written
    s = bom.stock_of(data, state, inv)
    key = lambda i: bom.line_key(data["lines"][i])  # noqa: E731
    assert s[key(0)] == {"qty": 400, "by": "generic", "label": "RC0603FR-0710KL", "row": 2}
    assert s[key(1)]["qty"] == 6 and s[key(1)]["by"] == "mpn"
    assert s[key(2)] == {"qty": 0, "by": "", "missing": True}
    assert key(3) not in s
