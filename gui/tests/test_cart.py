"""Carts exported from Mouser, LCSC and Digi-Key (cart.py), and matching them to a BOM
(bom.match_carts). The two example files are real exports, from the owl
board (tests/test_examples/exported_boms_from_distributor); the BOM here is
made up to meet them, so nothing depends on that board."""

import io
import zipfile
from pathlib import Path

import pytest

from kigit_gui import bom, cart

EXAMPLES = Path(__file__).resolve().parents[2] / "tests" / "test_examples" / "exported_boms_from_distributor"
LCSC = EXAMPLES / "exported_boms_lcsc.csv"
MOUSER = EXAMPLES / "exported_boms_mouser.xls"
DIGIKEY = EXAMPLES / "exported_boms_digikey.csv"


def line(refs, value, mpn="", **kw) -> dict:
    return {"refs": refs, "value": value, "footprint": kw.pop("footprint", "fp"), "mpn": mpn, "manufacturer": "",
            "digikey": "", "mouser": kw.pop("mouser", ""), "lcsc": kw.pop("lcsc", ""), "dnp": kw.pop("dnp", False),
            "qty": len(refs), "fields": {}, **kw}


def test_lcsc_cart_csv() -> None:
    """LCSC's cart CSV: LCSC#, MPN, Customer # (the references, from kigit's export), Quantity."""
    rows = cart.parse_cart(LCSC.read_bytes(), LCSC.name, "lcsc")
    assert len(rows) == 7
    assert rows[0] == {"sku": "C69082", "mpn": "FT230XS-R", "manufacturer": "FTDI",
                       "description": "USB to UART 3Mbps SSOP-16-150mil Controllers RoHS", "qty": 3, "refs": ["U3"],
                       "backorder": 0}
    assert rows[1]["refs"] == ["R1", "R2", "R11", "R19", "R20"] and rows[1]["qty"] == 100  # the MOQ, as ordered


def test_mouser_cart_xls() -> None:
    """Mouser's cart: an old .xls with a title block above the header and
    totals below; Mouser No, Mfr. No, Order Qty."""
    rows = cart.parse_cart(MOUSER.read_bytes(), MOUSER.name, "mouser")
    assert len(rows) == 20  # not the title, the header or "Merchandise:" / "Delivery Charge:"
    assert rows[0]["sku"] == "815-ABLS3-8MD4YT" and rows[0]["mpn"] == "ABLS3-8.000MHZ-D4Y-T"
    assert rows[0]["qty"] == 3 and rows[0]["manufacturer"] == "ABRACON" and rows[0]["refs"] == []
    stm = next(r for r in rows if r["mpn"] == "STM32F103C8T6")
    assert stm["sku"] == "511-STM32F103C8T6" and stm["qty"] == 2


def test_other_files_are_refused_with_a_reason() -> None:
    with pytest.raises(cart.CartError, match="no quantity and part number columns"):
        cart.parse_cart(b"Name,Age\nA,3\n", "x.csv", "lcsc")
    with pytest.raises(cart.CartError, match="Excel .xls"):
        cart.parse_cart(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 not really", "x.xls", "mouser")
    with pytest.raises(cart.CartError, match="not rs"):
        cart.parse_cart(LCSC.read_bytes(), LCSC.name, "rs")
    with pytest.raises(cart.CartError, match="no rows"):
        cart.parse_cart(b"LCSC#,Quantity\n", "x.csv", "lcsc")


def test_xlsx_and_other_spellings() -> None:
    """A cart saved as .xlsx (read without xlrd), with a title row and
    "Mouser #" / "Mfr. #" / "Qty" spellings; "1,000" is a thousand."""
    def cell(ref, text):
        return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'
    sheet = ('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             f'<row r="1">{cell("A1", "My cart")}</row>'
             f'<row r="2">{cell("A2", "Mouser #")}{cell("B2", "Mfr. #")}{cell("C2", "Qty")}</row>'
             f'<row r="3">{cell("A3", "511-X")}{cell("B3", "X")}<c r="C3"><v>4</v></c></row>'
             f'<row r="4">{cell("A4", "N/A")}{cell("B4", "Y")}{cell("C4", "1,000")}</row>'
             '</sheetData></worksheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    rows = cart.parse_cart(buf.getvalue(), "cart.xlsx", "mouser")
    assert [(r["sku"], r["mpn"], r["qty"]) for r in rows] == [("511-X", "X", 4), ("", "Y", 1000)]


def data() -> dict:
    """A BOM to meet the example carts: some lines by references, some by
    part number, one by a draft, one DNP, one in no cart."""
    return {"field_names": {"lcsc": "LCSC Part #"}, "lines": [
        line(["U3"], "FT230XS"),                                    # LCSC: Customer # U3
        line(["R1", "R2", "R11", "R19", "R20"], "10k"),            # LCSC: Customer # R1 R2 R11 R19 R20
        line(["R12", "R13", "R14", "R15"], "47k"),                 # LCSC row says R12-R16: R16 moved lines since
        line(["R16"], "47k", footprint="other"),
        line(["Y1"], "8MHz", "ABLS3-8.000MHZ-D4Y-T"),             # Mouser: by MPN
        line(["U1"], "STM32F103C8T6", mouser="511-STM32F103C8T6"),  # Mouser: by Mouser number
        line(["Y2"], "32k768"),                                     # Mouser: LFXTAL084885, as a draft below
        line(["C9", "C10"], "4pF", dnp=True),                      # DNP: never matched
        line(["J9"], "Conn"),                                       # in no cart
    ]}


def test_carts_matched_to_lines(tmp_path: Path) -> None:
    from kigit_gui import builds
    board = tmp_path / "x.kicad_pcb"
    b = builds.new(board, "Proto", 2).id
    bom.import_cart(board, b, "lcsc", LCSC.name, LCSC.read_bytes())
    state = bom.import_cart(board, b, "mouser", MOUSER.name, MOUSER.read_bytes())
    d = data()
    bom.set_draft(board, bom.line_key(d["lines"][6]), "MPN", "LFXTAL084885")  # Y2's MPN, typed, not written
    state = bom.state(board, b)
    m = bom.match_carts(d, state)
    key = lambda i: bom.line_key(d["lines"][i])  # noqa: E731
    assert m["lines"][key(0)]["qty"] == {"lcsc": 3}
    assert m["lines"][key(0)]["rows"][0]["by"] == "references"
    assert m["lines"][key(1)]["qty"] == {"lcsc": 100}
    assert m["lines"][key(2)]["qty"] == {"lcsc": 100}           # most of R12-R16 are here
    assert key(3) not in m["lines"]
    assert m["lines"][key(4)]["qty"] == {"mouser": 3} and m["lines"][key(4)]["rows"][0]["by"] == "MPN"
    assert m["lines"][key(5)]["qty"] == {"mouser": 2} and m["lines"][key(5)]["rows"][0]["by"] == "Mouser number"
    assert m["lines"][key(6)]["qty"] == {"mouser": 2}           # by the draft MPN
    assert key(7) not in m["lines"] and key(8) not in m["lines"]
    assert m["carts"]["lcsc"] == {"file": LCSC.name, "time": state["carts"]["lcsc"]["time"], "rows": 7, "received": ""}
    unmatched = {(u["site"], u["mpn"]) for u in m["unmatched"]}
    assert ("mouser", "STM32F103C8T6") not in unmatched and ("mouser", "CC0603KRX5R6BB105") in unmatched
    assert len(m["unmatched"]) == (7 - 3) + (20 - 3)              # 3 of LCSC's 7 rows are lines here, 3 of Mouser's 20

    # A row given to a line by hand, with its part numbers kept as drafts.
    i = next(u["i"] for u in m["unmatched"] if u["mpn"] == "CC0603KRX5R6BB105")
    state = bom.assign_row(board, b, d, "mouser", i, ["J9"], keep=True)
    m = bom.match_carts(d, state)
    assert m["lines"][key(8)]["qty"] == {"mouser": 20} and m["lines"][key(8)]["rows"][0]["by"] == "assigned"
    assert state["drafts"][key(8)] == {"MPN": "CC0603KRX5R6BB105", "Manufacturer": "YAGEO", "Mouser": "603-CC603KRX5R6BB105"}
    state = bom.assign_row(board, b, d, "mouser", i, None, keep=False)  # let go: still J9's, by the numbers kept as drafts
    assert bom.match_carts(d, state)["lines"][key(8)]["rows"][0]["by"] == "Mouser number"
    bom.set_draft(board, key(8), "Mouser", None)
    assert bom.match_carts(d, bom.state(board, b))["lines"][key(8)]["rows"][0]["by"] == "MPN"
    bom.set_draft(board, key(8), "MPN", None)                         # drafts dropped: in no line now
    state = bom.state(board, b)
    assert key(8) not in bom.match_carts(d, state)["lines"]
    with pytest.raises(ValueError):
        bom.assign_row(board, b, d, "mouser", 999, ["J9"], keep=False)

    # Kept with the build (another build has none); removing one.
    assert set(bom.state(board, b)["carts"]) == {"lcsc", "mouser"}
    assert bom.state(board, builds.new(board, "Bulk", 50).id)["carts"] == {}
    state = bom.remove_cart(board, b, "lcsc")
    assert set(state["carts"]) == {"mouser"}
    with pytest.raises(bom.NoBuild):
        bom.import_cart(board, "", "lcsc", LCSC.name, LCSC.read_bytes())


def test_receiving_a_cart_adds_it_to_the_inventory(tmp_path: Path) -> None:
    """Mark received: each row's quantity goes into your inventory CSV (by
    part number, or as its line's passive), and it's not "ordered" any more;
    undo takes exactly that back out."""
    from kigit_gui import builds, inventory
    board = tmp_path / "x.kicad_pcb"
    b = builds.new(board, "Proto", 2).id
    shelf = tmp_path / "inventory.csv"
    shelf.write_text("MPN,Kind,Value,Package,Quantity,Location\n"
                     "FT230XS-R,,,,1,Box A\n"
                     ",resistor,10k,0603,40,Drawer 2\n", encoding="utf-8")
    d = {"field_names": {}, "lines": [
        line(["U3"], "FT230XS"),
        {**line(["R1", "R2", "R11", "R19", "R20"], "10k"), "kind": "resistor", "package": "0603"},
    ]}
    bom.import_cart(board, b, "lcsc", LCSC.name, LCSC.read_bytes())
    with pytest.raises(inventory.InventoryError, match="choose your inventory"):
        bom.receive_cart(board, b, d, "lcsc")
    inventory.remember(shelf)
    try:
        state = bom.receive_cart(board, b, d, "lcsc")
        inv = inventory.read(shelf)
        assert inv.find({"mpn": "FT230XS-R"})[0].qty == 1 + 3                 # by MPN
        assert inv.find({"kind": "resistor", "value": "10k", "package": "0603"})[0].qty == 40 + 100  # as its line's passive
        assert inv.find({"mpn": "RC0603JR-070RL"})[0].qty == 100                # new to you: a row of its own (no LCSC column here)
        assert len(inv.rows) == 2 + 5                                            # 7 rows: 2 found, 5 new
        m = bom.match_carts(d, state)
        assert m["lines"] == {} and m["carts"]["lcsc"]["received"]              # received: not ordered any more
        # U3 had no part number: it gets the cart's as drafts, and so finds what arrived.
        assert state["drafts"][bom.line_key(d["lines"][0])] == {"MPN": "FT230XS-R", "Manufacturer": "FTDI", "LCSC": "C69082"}
        assert bom.stock_of(d, state, inv)[bom.line_key(d["lines"][0])]["qty"] == 4
        with pytest.raises(ValueError, match="received already"):
            bom.receive_cart(board, b, d, "lcsc")
        bom.receive_cart(board, b, d, "lcsc", undo=True)                         # exactly what was added, back out
        inv = inventory.read(shelf)
        assert inv.find({"mpn": "FT230XS-R"})[0].qty == 1
        assert inv.find({"kind": "resistor", "value": "10k", "package": "0603"})[0].qty == 40
        assert bom.match_carts(d, bom.state(board, b))["lines"][bom.line_key(d["lines"][0])]["qty"] == {"lcsc": 3}
    finally:
        inventory.remember(None)  # the test app folder is shared by the tests


def test_values_as_numbers() -> None:
    """A passive's value, however it's written, as a number."""
    for text, kind, want in (("10k", "resistor", 1e4), ("10kR", "resistor", 1e4), ("4k7", "resistor", 4700), ("4R7", "resistor", 4.7),
                             ("27R", "resistor", 27), ("1M", "resistor", 1e6), ("1m", "resistor", 1e6),
                             ("100nF", "capacitor", 1e-7), ("0.1uF", "capacitor", 1e-7), ("1µF", "capacitor", 1e-6),
                             ("27nH", "inductor", 27e-9), ("8MHz", "crystal", 8e6), ("32k768", "crystal", 32768)):
        assert bom.si_value(text, kind) == pytest.approx(want), text
    # The unit letter as the decimal point, with a trailing R / F / H too.
    for text, kind, want in (("5k1R", "resistor", 5100), ("2M2R", "resistor", 2.2e6), ("4R7", "resistor", 4.7),
                             ("1n8F", "capacitor", 1.8e-9), ("4u7F", "capacitor", 4.7e-6), ("2p2F", "capacitor", 2.2e-12),
                             ("4n7H", "inductor", 4.7e-9)):
        assert bom.si_value(text, kind) == pytest.approx(want), text
    assert bom.si_value("RED", "led") is None and bom.si_value("STM32", "other") is None


def test_unmatched_rows_get_a_suggested_line() -> None:
    """For cart rows that match no line, a likely line from the description
    (kind, value as a number, package) or the part name; only a clear best,
    and never matched until accepted. Your real Mouser cart."""
    rows = {r["mpn"]: r for r in cart.parse_cart(MOUSER.read_bytes(), MOUSER.name, "mouser")}
    lines = [{**line(["C1", "C17"], "10uF"), "kind": "capacitor", "package": "0603"},
             {**line(["C2", "C3"], "100nF"), "kind": "capacitor", "package": "0603"},
             {**line(["C9", "C10"], "4pF"), "kind": "capacitor", "package": "0603"},
             {**line(["C11", "C12"], "47pF"), "kind": "capacitor", "package": "0603"},
             {**line(["Y2"], "32k768"), "kind": "crystal", "package": ""},
             {**line(["L1"], "27nH"), "kind": "inductor", "package": "0603"},
             {**line(["U4"], "SN65HVD230"), "kind": "other", "package": "SOIC-8"},
             {**line(["C99"], "100nF", dnp=True), "kind": "capacitor", "package": "0603"}]
    sug = lambda mpn: bom.suggest_line(rows[mpn], lines, {}, {})  # noqa: E731
    assert sug("0603ZC104K4T2A")["refs"] == ["C2", "C3"]        # "0.1uF ... 0603" is the 100nF line (not the DNP one)
    assert sug("0603ZC104K4T2A")["why"] == "capacitor 100nF + 0603"
    assert sug("0603N470J100CT")["refs"] == ["C11", "C12"]      # "47 pF", with a space
    assert sug("KGM15CT71A106MT")["refs"] == ["C1", "C17"]      # "10uF"
    assert sug("LFXTAL084885")["refs"] == ["Y2"]                # "32.768kHz" is 32k768
    assert sug("AISC-0603-R027G-T")["refs"] == ["L1"]           # "27.00 nH"
    assert sug("SN65HVD230QDG4")["refs"] == ["U4"]              # the part name in its MPN
    assert sug("0603N5R0C100CT") is None                         # 5 pF: no 5 pF line (the 4pF isn't close enough)
    assert sug("S2B-PH-K-S-GW") is None                          # nothing like it
    twins = lines + [{**line(["C30"], "100nF"), "kind": "capacitor", "package": "0603", "footprint": "other"}]
    assert bom.suggest_line(rows["0603ZC104K4T2A"], twins, {}, {}) is None  # two 100nF 0603 lines: no guess


def test_digikey_cart_csv() -> None:
    """Digi-Key's cart CSV (UTF-8 with a BOM): its own number is the plain
    "Part Number" (...-ND), the maker's is "Manufacturer Part Number";
    Customer Reference holds kigit's references; Backorder says what isn't
    in stock yet."""
    rows = cart.parse_cart(DIGIKEY.read_bytes(), DIGIKEY.name, "digikey")
    assert len(rows) == 15
    assert rows[0] == {"sku": "1276-CL05X226MS6NUW8CT-ND", "mpn": "CL05X226MS6NUW8", "manufacturer": "",
                       "description": "0402 22UF X6S 2.5V 20%", "qty": 2, "refs": [], "backorder": 2}
    assert rows[1]["sku"] == "1276-CL05B104KB54PNCCT-ND" and rows[1]["backorder"] == 0
    assert [r["qty"] for r in rows if r["mpn"] == "RC0201FR-0710KL"] == [32, 1]  # the same part on two rows
    # Elsewhere a plain "Part Number" is the maker's: only Digi-Key's is its own number.
    other = cart.parse_cart(b"Part Number,Quantity\nRC0603FR-0710KL,5\n", "x.csv", "mouser")
    assert other[0]["mpn"] == "RC0603FR-0710KL" and other[0]["sku"] == ""
    # The references from kigit's Digi-Key export come back in Customer Reference.
    back = cart.parse_cart("Index,Quantity,Part Number,Manufacturer Part Number,Customer Reference\n"
                           "1,4,311-10.0KHRCT-ND,RC0603FR-0710KL,R1 R2 R3 +2\n".encode(), "c.csv", "digikey")
    assert back[0]["refs"] == ["R1", "R2", "R3"]


def test_digikey_cart_matched_with_backorders(tmp_path: Path) -> None:
    """Matched by Digi-Key number (the line's own) or MPN; both rows of a part count; backorders are kept."""
    data = {"field_names": {}, "lines": [line(["C1", "C2"], "22uF", digikey="1276-CL05X226MS6NUW8CT-ND"),
                                         line(["R1"], "10k", "RC0201FR-0710KL")]}
    board = tmp_path / "x.kicad_pcb"
    rows = cart.parse_cart(DIGIKEY.read_bytes(), DIGIKEY.name, "digikey")
    state = {"drafts": {}, "carts": bom._carts({"carts": {"digikey": {"file": "c.csv", "time": "t", "rows": rows}}})}
    m = bom.match_carts(data, state)
    c1 = m["lines"][bom.line_key(data["lines"][0])]
    assert c1["qty"] == {"digikey": 2} and c1["rows"][0]["by"] == "Digi-Key number" and c1["rows"][0]["backorder"] == 2
    r1 = m["lines"][bom.line_key(data["lines"][1])]
    assert r1["qty"] == {"digikey": 33} and {r["by"] for r in r1["rows"]} == {"MPN"}
    assert len(m["unmatched"]) == 15 - 3
    assert board  # (no files needed)
