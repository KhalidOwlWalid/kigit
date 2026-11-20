"""Carts exported from Mouser and LCSC (cart.py), and matching them to a BOM
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


def line(refs, value, mpn="", **kw) -> dict:
    return {"refs": refs, "value": value, "footprint": kw.pop("footprint", "fp"), "mpn": mpn, "manufacturer": "",
            "digikey": "", "mouser": kw.pop("mouser", ""), "lcsc": kw.pop("lcsc", ""), "dnp": kw.pop("dnp", False),
            "qty": len(refs), "fields": {}, **kw}


def test_lcsc_cart_csv() -> None:
    """LCSC's cart CSV: LCSC#, MPN, Customer # (the references, from kigit's export), Quantity."""
    rows = cart.parse_cart(LCSC.read_bytes(), LCSC.name, "lcsc")
    assert len(rows) == 7
    assert rows[0] == {"sku": "C69082", "mpn": "FT230XS-R", "manufacturer": "FTDI",
                       "description": "USB to UART 3Mbps SSOP-16-150mil Controllers RoHS", "qty": 3, "refs": ["U3"]}
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
    with pytest.raises(cart.CartError, match="not digikey"):
        cart.parse_cart(LCSC.read_bytes(), LCSC.name, "digikey")
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
    board = tmp_path / "x.kicad_pcb"
    bom.import_cart(board, "lcsc", LCSC.name, LCSC.read_bytes())
    state = bom.import_cart(board, "mouser", MOUSER.name, MOUSER.read_bytes())
    d = data()
    state = bom.set_draft(board, bom.line_key(d["lines"][6]), "MPN", "LFXTAL084885")  # Y2's MPN, typed, not written
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
    assert m["carts"]["lcsc"] == {"file": LCSC.name, "time": state["carts"]["lcsc"]["time"], "rows": 7}
    unmatched = {(u["site"], u["mpn"]) for u in m["unmatched"]}
    assert ("mouser", "STM32F103C8T6") not in unmatched and ("mouser", "CC0603KRX5R6BB105") in unmatched
    assert len(m["unmatched"]) == (7 - 3) + (20 - 3)              # 3 of LCSC's 7 rows are lines here, 3 of Mouser's 20

    # A row given to a line by hand, with its part numbers kept as drafts.
    i = next(u["i"] for u in m["unmatched"] if u["mpn"] == "CC0603KRX5R6BB105")
    state = bom.assign_row(board, d, "mouser", i, ["J9"], keep=True)
    m = bom.match_carts(d, state)
    assert m["lines"][key(8)]["qty"] == {"mouser": 20} and m["lines"][key(8)]["rows"][0]["by"] == "assigned"
    assert state["drafts"][key(8)] == {"MPN": "CC0603KRX5R6BB105", "Manufacturer": "YAGEO", "Mouser": "603-CC603KRX5R6BB105"}
    state = bom.assign_row(board, d, "mouser", i, None, keep=False)  # let go: still J9's, by the numbers kept as drafts
    assert bom.match_carts(d, state)["lines"][key(8)]["rows"][0]["by"] == "Mouser number"
    bom.set_draft(board, key(8), "Mouser", None)
    assert bom.match_carts(d, bom.load_drafts(board))["lines"][key(8)]["rows"][0]["by"] == "MPN"
    state = bom.set_draft(board, key(8), "MPN", None)                # drafts dropped: in no line now
    assert key(8) not in bom.match_carts(d, state)["lines"]
    with pytest.raises(ValueError):
        bom.assign_row(board, d, "mouser", 999, ["J9"], keep=False)

    # Kept in kigit-bom.json; importing again replaces that site's cart; removing it.
    assert set(bom.load_drafts(board)["carts"]) == {"lcsc", "mouser"}
    state = bom.remove_cart(board, "lcsc")
    assert set(state["carts"]) == {"mouser"}
