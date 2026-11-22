"""The BOM page: picks kept next to the board, and the page's script."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kigit_gui import bom

DATA = {"lines": [{"refs": ["R1", "R2"], "qty": 2, "value": "10k", "footprint": "R_0603", "package": "0603",
                   "mpn": "", "manufacturer": "", "digikey": "", "mouser": "", "lcsc": "", "dnp": False,
                   "description": "", "query": "10k 0603 resistor",
                   "links": {"digikey": "https://d", "mouser": "https://m", "lcsc": "https://l"}}],
        "summary": {"lines": 1, "parts": 2, "dnp_parts": 0, "without_number": 1}}


def test_drafts_kept_next_to_the_board(tmp_path: Path) -> None:
    board = tmp_path / "x.kicad_pcb"
    assert bom.load_drafts(board) == {"drafts": {}, "columns": [], "tracking": {"columns": [], "done": {}}, "carts": {}}
    state = bom.set_draft(board, "10k|R_0603", "MPN", " RC0603FR-0710KL ")
    assert state["drafts"]["10k|R_0603"]["MPN"] == "RC0603FR-0710KL"
    saved = json.loads((tmp_path / bom.DRAFTS).read_text(encoding="utf-8"))
    assert saved["version"] == 2 and saved["drafts"]["10k|R_0603"]["MPN"] == "RC0603FR-0710KL"
    bom.set_draft(board, "100n|C_0603", "LCSC Part #", "C1525")
    assert set(bom.load_drafts(board)["drafts"]) == {"10k|R_0603", "100n|C_0603"}  # re-read, not overwritten
    bom.add_column(board, "Supplier")
    assert bom.load_drafts(board)["columns"] == ["Supplier"]
    bom.set_draft(board, "10k|R_0603", "MPN", None)
    bom.set_draft(board, "100n|C_0603", "LCSC Part #", None)
    assert bom.load_drafts(board)["drafts"] == {}
    state = bom.load_drafts(board)
    state["columns"] = []
    bom.save_drafts(board, state)
    assert not (tmp_path / bom.DRAFTS).exists()  # nothing left: no file


def test_trackers_belong_to_a_build_and_stay_out_of_the_schematic(tmp_path: Path) -> None:
    """Trackers are tick columns of a build (its build.json), per part
    reference; the drafts (kigit-bom.json) never hold them."""
    from kigit_gui import builds
    board = tmp_path / "x.kicad_pcb"
    bom.set_draft(board, "10k|R_0603", "MPN", "RC0603FR-0710KL")
    b = builds.new(board, "Proto", 3).id
    other = builds.new(board, "Bulk", 50).id
    with pytest.raises(bom.NoBuild):
        bom.add_tracker(board, "", "Carted")                 # no build: nowhere to keep it
    bom.add_tracker(board, b, "Carted")
    bom.add_tracker(board, b, "Placed")
    bom.add_tracker(board, b, "Carted")  # once
    state = bom.set_tracked(board, b, "Carted", ["R1", "R2"], True)
    assert state["tracking"] == {"columns": ["Carted", "Placed"], "done": {"Carted": ["R1", "R2"]}}
    state = bom.set_tracked(board, b, "Carted", ["R2", "R3"], True)
    assert state["tracking"]["done"]["Carted"] == ["R1", "R2", "R3"]
    state = bom.set_tracked(board, b, "Carted", ["R1"], False)
    assert state["tracking"]["done"]["Carted"] == ["R2", "R3"]
    assert state["drafts"]["10k|R_0603"]["MPN"] == "RC0603FR-0710KL"  # the drafts are there too, untouched
    assert bom.state(board, other)["tracking"] == {"columns": [], "done": {}}  # another build starts fresh
    assert bom.state(board, "")["tracking"]["columns"] == []                    # and so does the design
    saved = json.loads((tmp_path / "kigit-builds" / b / "build.json").read_text(encoding="utf-8"))
    assert saved["tracking"]["columns"] == ["Carted", "Placed"] and saved["boards"] == 3
    assert "tracking" not in json.loads((tmp_path / bom.DRAFTS).read_text(encoding="utf-8"))
    builds.update(board, b, boards=4)                         # editing the build keeps what's in it
    assert bom.state(board, b)["tracking"]["done"]["Carted"] == ["R2", "R3"]
    state = bom.remove_tracker(board, b, "Carted")
    assert state["tracking"] == {"columns": ["Placed"], "done": {}}
    # Trackers and carts from before builds (in kigit-bom.json) are left behind.
    (tmp_path / bom.DRAFTS).write_text('{"version": 2, "tracking": {"columns": ["Old"], "done": {}}, "carts": {}}',
                                      encoding="utf-8")
    assert bom.load_drafts(board)["tracking"] == {"columns": [], "done": {}}


def test_renaming_columns_keeps_their_drafts_and_ticks(tmp_path: Path) -> None:
    board = tmp_path / "x.kicad_pcb"
    bom.add_column(board, "Voltage")
    bom.add_column(board, "Supplier")
    bom.set_draft(board, "10k|R_0603", "Voltage", "50V")
    state = bom.rename_column(board, "Voltage", "Voltage rating")
    assert state["columns"] == ["Voltage rating", "Supplier"]  # in place
    assert state["drafts"]["10k|R_0603"] == {"Voltage rating": "50V"}
    from kigit_gui import builds
    b = builds.new(board, "Proto", 1).id
    bom.add_tracker(board, b, "Carted")
    bom.set_tracked(board, b, "Carted", ["R1"], True)
    state = bom.rename_tracker(board, b, "Carted", "In cart")
    assert state["tracking"] == {"columns": ["In cart"], "done": {"In cart": ["R1"]}}


def test_version_1_picks_are_read_as_drafts(tmp_path: Path) -> None:
    (tmp_path / bom.DRAFTS).write_text(json.dumps({"version": 1, "picks": {
        "10k|R_0603": {"mpn": "RC0603FR-0710KL", "manufacturer": "Yageo", "note": "cheap", "updated": "2026-11-18"}}}),
        encoding="utf-8")
    state = bom.load_drafts(tmp_path / "x.kicad_pcb")
    assert state["drafts"]["10k|R_0603"] == {"MPN": "RC0603FR-0710KL", "Manufacturer": "Yageo", "Note": "cheap"}
    assert state["columns"] == ["Note"]


def test_broken_drafts_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / bom.DRAFTS).write_text("{not json", encoding="utf-8")
    assert bom.load_drafts(tmp_path / "x.kicad_pcb") == {"drafts": {}, "columns": [], "tracking": {"columns": [], "done": {}}, "carts": {}}


def test_line_key() -> None:
    assert bom.line_key({"value": "10k", "footprint": "R_0603"}) == "10k|R_0603"
    assert bom.line_key({"value": "10k", "footprint": "R_0603", "lcsc": "C25804"}) == "10k|R_0603|C25804"


def _page() -> str:
    return bom.page("k", bom.Job(str(Path("/p/owl.kicad_pcb")), "owl · working tree", DATA))


def test_page_has_the_data_and_no_html_injection() -> None:
    evil = json.loads(json.dumps(DATA))
    evil["lines"][0]["value"] = "</script><script>alert(1)</script>"
    page = bom.page("k", bom.Job("/p/owl.kicad_pcb", "<b>t</b>", evil))
    assert "</script><script>alert" not in page and "&lt;b&gt;t&lt;/b&gt;" in page
    assert "EDITABLE = true" in page
    commit = bom.page("k", bom.Job("/p/owl.kicad_pcb", "t", DATA, rev="abc123"))
    assert "EDITABLE = false" in commit  # a commit's BOM can't be written


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js to check the script")
def test_page_scripts_parse(tmp_path: Path) -> None:
    page = _page()
    plain = re.findall(r"<script>(.*?)</script>", page, re.S)
    module = re.findall(r'<script type="module">(.*?)</script>', page, re.S)
    assert len(plain) == 1 and len(module) == 1  # the list and 2D board; the 3D board
    # The module's imports are resolved by the importmap; node only needs to parse.
    module = [re.sub(r'^import .*? from "\w+";$', "", module[0], flags=re.M)]
    for name, text in (("page.js", plain[0]), ("page3d.mjs", module[0])):
        f = tmp_path / name
        f.write_text(text, encoding="utf-8")
        r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{name}: {r.stderr}"


def test_page_file_is_not_ignored_by_git() -> None:
    """bom_page.html ships with the GUI: the repo's "*.html" ignore rule
    (for generated diff pages) must not hide it from git."""
    page = Path(bom.__file__).with_name("bom_page.html")
    if not shutil.which("git"):
        pytest.skip("needs git")
    r = subprocess.run(["git", "-C", str(page.parent), "check-ignore", "-q", str(page)], capture_output=True)
    if r.returncode == 128:
        pytest.skip("not in a git checkout")
    assert r.returncode == 1, f"{page.name} is ignored by .gitignore"


REPO = Path(__file__).resolve().parents[2]
KIGIT_BIN = os.environ.get("KIGIT_BIN") or next(
    (str(p) for p in (REPO / "build" / "kigit", REPO / "build" / "kigit.exe") if p.exists()), "")


@pytest.mark.skipif(sys.platform == "win32" or not KIGIT_BIN, reason="needs the built kigit and a shell for the stand-in curl")
def test_look_up_through_kigit_with_a_stand_in_curl(tmp_path: Path, monkeypatch) -> None:
    """Look up: the key goes to kigit on stdin, the page learns only that one
    is set, and the lookup's result and progress are kept with the job."""
    part = {"MouserPartNumber": "603-RC0603FR-071KL", "ManufacturerPartNumber": "RC0603FR-071KL",
            "Manufacturer": "YAGEO", "Description": "Thick Film Resistors 1K 0603", "AvailabilityInStock": "5000",
            "Min": "1", "Mult": "1", "PriceBreaks": [{"Quantity": 1, "Price": "$0.10", "Currency": "USD"}]}
    (tmp_path / "reply.json").write_text(json.dumps({"Errors": [], "SearchResults": {"Parts": [part]}}), encoding="utf-8")
    curl = tmp_path / "curl"
    curl.write_text(f'#!/bin/sh\necho "$*" >> "{tmp_path}/args.log"\ncat > /dev/null\n'
                    f'cat "{tmp_path}/reply.json"\nprintf "\\n200"\n', encoding="utf-8")
    curl.chmod(0o755)
    monkeypatch.setenv("KIGIT_BIN", KIGIT_BIN)
    monkeypatch.setenv("KIGIT_CURL", str(curl))
    monkeypatch.setenv("KIGIT_LOOKUP_PACE_MS", "0")
    monkeypatch.delenv("KIGIT_MOUSER_API_KEY", raising=False)
    monkeypatch.setenv("KIGIT_LOG_DIR", str(tmp_path / "state" / "log"))  # keys and cache go in state/

    from kigit_gui import kigit

    assert asyncio.run(kigit.bom_keys())["mouser"] == {"set": False, "env": False, "name": "Mouser", "where": ""}
    asyncio.run(kigit.bom_set_key("mouser", " SECRET-1 "))
    keys = asyncio.run(kigit.bom_keys())
    assert keys["mouser"]["set"] and "SECRET-1" not in json.dumps(keys)
    assert json.loads((tmp_path / "state" / "parts-keys.json").read_text(encoding="utf-8")) == {"mouser": "SECRET-1"}

    board = str(REPO / "tests" / "fixtures" / "v2" / "demo.kicad_pcb")
    job = bom.Job(board, "demo", asyncio.run(kigit.bom(board)))
    asyncio.run(bom.run_lookup(job, 3, False))
    state = job.lookup.state()
    assert not state["running"] and not state["error"]
    assert state["done"] == state["total"] == 4 and state["boards"] == 3
    lines = {l["key"]: l for l in state["result"]["lines"]}
    one_k = lines[bom.line_key(next(l for l in job.data["lines"] if l["value"] == "1k"))]
    assert one_k["need"] == 9  # 3 parts x 3 boards
    assert one_k["sites"]["mouser"]["status"] == "choose"
    assert one_k["sites"]["mouser"]["candidates"][0]["mpn"] == "RC0603FR-071KL"
    assert list(state["result"]["sites"]) == ["mouser"]  # only the sites with a key
    assert state["sites"] == "Mouser"
    assert "SECRET-1" not in (tmp_path / "args.log").read_text(encoding="utf-8")

    asyncio.run(kigit.bom_set_key("digikey", "DK-ID", "DK-SECRET", "UK GBP"))
    dk = asyncio.run(kigit.bom_keys())["digikey"]
    assert dk["set"] and dk["site"] == "UK" and dk["currency"] == "GBP" and "DK-SECRET" not in json.dumps(dk)

    asyncio.run(kigit.bom_set_key("mouser", ""))
    asyncio.run(kigit.bom_set_key("digikey", ""))
    keys = asyncio.run(kigit.bom_keys())
    assert not keys["mouser"]["set"] and not keys["digikey"]["set"]


def test_every_panel_and_column_can_be_hidden() -> None:
    """Each panel has a header toggle (and the side panes a Hide of their
    own); columns are found by id and class, not by position."""
    page = _page()
    for button in ("showlist", "show2d", "show3d", "colsbtn"):
        assert f'id="{button}"' in page
    assert 'data-hide="show2d"' in page and 'data-hide="show3d"' in page
    assert 'const PANES = ["showlist", "show2d", "show3d", "shownotes"]' in page
    for col in ('id: "qty"', 'id: "value"', 'id: "f:" + c.name', 'id: "site:" + site', 'id: "price:" + site', 'id: "search"'):
        assert col in page
    assert 'id: "refs", label: "References", fixed: true' in page  # always shown
    assert "children[1]" not in page and "lastElementChild" not in page  # cells by class, so hidden columns don't shift them


def test_cells_wrap_and_columns_resize() -> None:
    """Part number cells are text boxes that wrap (one line of text, no
    line breaks); every column has a grip, widths are kept, Reset widths
    puts them back."""
    page = _page()
    assert '<textarea class="cell' in page and "input.cell" not in page
    assert 'class="grip" data-col=' in page
    assert '"kigit.bomColWidths"' in page
    assert 'id="resetw"' in page and 'id="colsreset"' in page
    assert '<colgroup id="colgroup">' in page


def test_every_column_kind_can_be_filtered() -> None:
    """Headers get a filter button: text columns (contains / empty / not
    empty), trackers (done / not / partly), sites (found, short, ...)."""
    page = _page()
    assert 'class="fbtn' in page and 'id="fmenu"' in page and 'id="clearf"' in page
    for kind in ("track:", "text:", "site:"):
        assert f"  {kind} [[" in page
    assert page.count('filter: "text"') >= 3  # References, Value, the fields
    assert 'filter: "site"' in page
    assert "passesFilters(l)" in page


def test_notes_on_the_page() -> None:
    """+ Notes on every line, a Notes pane (the Notebook in an iframe) with
    its own tab, all on the same notes key as kigit's Notebook."""
    from kigit_gui.review_panel import project_key
    page = _page()
    key = project_key(Path("/p/owl.kicad_pcb").parent)
    assert f'NOTESKEY = "{key}"' in page
    assert 'id="panenotes"' in page and 'id="notestab"' in page and 'data-hide="shownotes"' in page
    assert "notesButton(l, i)" in page and 'new BroadcastChannel("kigit-bom")' in page
    assert "/bom-notes/${NOTESKEY}?bom=${KEY}&pane=1" in page


def test_export_for_lcsc_and_mouser() -> None:
    """Export CSV offers LCSC's and Mouser's BOM tools (their templates'
    columns, DNP left out; Mouser needs a Mouser number or an MPN) and every column."""
    page = _page()
    for kind in ("lcsc", "mouser", "all"):
        assert f'data-export="{kind}"' in page
    assert '"Quantity", "Manufacture Part Number", "Manufacturer", "Description", "LCSC Part Number"' in page
    assert '"Mouser Part Number", "Manufacturer Part Number", "Manufacturer Name"' in page and '"Quantity 1"' in page
    assert "if (!mouser && !mpn) { left.push(l); continue; }" in page
    # Which lines: all, the ones shown (filters), or not yet in a tracker; every format uses it.
    assert 'id="xrule"' in page and '["shown", "Only the lines shown' in page and "`not:${t}`" in page
    assert page.count("for (const l of ruleLines()) {") == 3
    assert '"kigit.bomExportRule"' in page


def test_carts_on_the_page() -> None:
    """Import cart (Mouser, LCSC), the Ordered column and its filter, the
    carts dialog, and the board coloured by what's covered, per board."""
    page = _page()
    assert 'id="cartbtn"' in page and 'data-cart="mouser"' in page and 'data-cart="lcsc"' in page
    assert 'accept=".csv,.xls,.xlsx"' in page and 'id="cartdlg"' in page
    assert 'id: "ordered", label: "Ordered (carts)", filter: "ordered"' in page
    assert '["from:mouser", "In the Mouser cart"]' in page
    assert page.count("data-ordered hidden") == 2  # PCB and 3D panes
    # The rule for a line the carts don't fully cover: floor(cart / boards) positions, first refs first.
    assert "Math.min(l.refs.length, Math.floor(orderedOf(l).total / b))" in page
    assert "function mark(marks)" in page and "window.kigitBomMarked" in page
    # An import shows it on the board: the PCB and 3D panes come on with it.
    assert 'for (const id of ["show2d", "show3d"]) $(id).classList.add("on");' in page


def test_builds_on_the_page() -> None:
    """The Build picker (Design only, the builds, + New build), remembered per
    board (a key that lasts across GUI sessions), its board count as Build qty."""
    page = _page()
    assert 'id="build"' in page and 'id="bmenu"' in page and "+ New build&hellip;" in page
    assert "kigit.bomBuild.${BOARDID}" in page
    assert '%%' not in page.split("<script>")[0] and 'BOARDID = "' in page and 'BOARDID = ""' not in page


def test_hidden_panes_fit_the_board_when_shown() -> None:
    """A PCB or 3D pane hidden when the page opened measures as nothing:
    the board is fitted (2D) or framed (3D) once the pane is shown."""
    page = _page()
    assert 'addEventListener("resize", () => { if (drawn && !full && measure()) fit(); })' in page
    assert 'if (model && !framed) { framed = true; view("iso"); }' in page


def test_buy_on_the_page() -> None:
    """With a build: To buy (needed - in stock - ordered), how many boards
    the stock covers, receiving carts, exporting only what's left to buy;
    every request says which build."""
    page = _page()
    assert 'body = { build: BUILD ? BUILD.id : "", ...(body || {}) };' in page
    assert "/drafts?build=" in page and "/cart?build=" in page and "&build=" in page
    assert 'id: "tobuy", label: "To buy (this build)", filter: "tobuy"' in page
    assert "toBuy: Math.max(0, need - stock - ordered)" in page
    assert "stock covers <b>" in page and "data-receive=" in page and "data-unreceive=" in page
    assert '["tobuy", "Only what\'s still to buy (and that many)"]' in page
    assert 'exportRule === "tobuy" && BUILD ? buyOf(l).toBuy : l.qty * boards' in page
    # Without a build, Import cart and + Tracker still answer (a disabled button just ignores the click):
    # the menu says why and offers a new build; + Tracker offers to make one.
    assert '$("cartbtn").disabled' not in page and '$("addtracker").disabled' not in page
    assert 'id="cnobuild"' in page and 'id="cbuild"' in page and "await newBuild()" in page
    assert "#cmenu [hidden], #xmenu [hidden] { display: none; }" in page  # else display: block shows hidden items


def test_assemble_on_the_page() -> None:
    """Buy / Assemble; boards picked and started; a placement column right
    after Value; the board view coloured by what's placed; placed parts
    aren't needed any more."""
    page = _page()
    assert 'data-view-mode="buy"' in page and 'data-view-mode="assemble"' in page and 'id="asmbar"' in page
    assert 'id: "placed", label: "Placed (this board)", filter: "placed"' in page
    assert page.index('id: "placed"') < page.index('...cols.map((c, ci) => ({ id: "f:"')
    assert "data-place=" in page and "data-placeall=" in page and "[data-place]\")) return;" in page
    assert "asm ? placedMarks() : orderedMarks()" in page
    assert "Math.max(0, l.qty * buildQty() - placedOf(l))" in page


def test_trackers_on_the_page() -> None:
    page = _page()
    assert 'id="addtracker"' in page
    assert 'id: "t:" + name' in page and "data-track=" in page  # a column like the others: hide, resize
    assert 'filter: "track"' in page  # filtered from its header
    assert "...trackers()]" in page  # and the CSV has them


def test_bom_problems_go_to_the_log_and_the_bell() -> None:
    """A BOM error answer is a warning in the session log and the bell (not
    a 404: a page left open after a restart); things done are info notices."""
    from kigit_gui import notices
    before = len(notices.items)
    r = bom._err("can't write inventory.csv: is it open in a spreadsheet?", 400, "inventory")
    assert r.status_code == 400 and json.loads(r.body) == {"error": "can't write inventory.csv: is it open in a spreadsheet?"}
    n = notices.items[0]
    assert (n.level, n.title, n.detail) == ("warning", "BOM: can't write inventory.csv: is it open in a spreadsheet?", "inventory")
    assert not n.read and notices.unread_problems() >= 1
    assert json.loads(bom._err("x", 409, locked=True).body) == {"error": "x", "locked": True}
    assert notices.items[0].level == "warning"
    assert bom._err("boom", 500).status_code == 500 and notices.items[0].level == "error"
    count = len(notices.items)
    bom._err("gone", 404)                          # just the log
    assert len(notices.items) == count
    bom._done("board #1 of build run is done", "every part placed")
    assert notices.items[0].level == "info" and notices.items[0].title == "BOM: board #1 of build run is done"
    assert len(notices.items) == before + 4  # 400, 409, 500 and the one done; not the 404
    notices.mark_read()


def test_bell_and_log_on_the_page() -> None:
    page = _page()
    assert 'id="bell"' in page and 'id="bellbadge"' in page and 'id="logbtn"' in page and 'id="nmenu"' in page
    assert 'fetch("/notices.json"' in page and 'fetch("/notices/read", { method: "POST" })' in page
    assert 'window.open("/log"' in page and "/clientlog" in page and 'addEventListener("unhandledrejection"' in page


def test_panels_are_resizable() -> None:
    """A line between the list and the board, and between the side's panes:
    dragged sizes remembered, double-click to reset; a pane shown later gets
    its usual share (sizes are pixel weights, so it isn't squashed)."""
    page = _page()
    assert 'id="splitgrip"' in page and "#split.sized #side { flex: 0 0 var(--side-w); }" in page
    assert '"kigit.bomSplit"' in page and '"kigit.bomPaneSizes"' in page and "function paneGrips()" in page
    assert "unit * PANE_SHARE[id]" in page
    assert "body.resizing iframe, body.resizing canvas, body.resizing svg { pointer-events: none; }" in page


def test_page_looks_like_kigit() -> None:
    """The BOM page wears kigit's look: its fonts (NiceGUI's, served locally),
    the dark Quasar palette, the amber logo, icons on the buttons; and
    hidden always hides (buttons are inline-flex)."""
    from nicegui import __version__
    page = _page()
    assert f'href="/_nicegui/{__version__}/static/fonts.css"' in page
    assert "--bg: #121212; --panel: #1d1d1d; --bar: #161a20" in page and "prefers-color-scheme: light" not in page
    assert '<span class="logo">kigit</span>' in page and page.count('class="material-icons"') >= 19
    assert "[hidden] { display: none !important; }" in page


def test_loaded_carts_show_in_the_toolbar() -> None:
    """A build's carts are chips beside Import cart: what's loaded, with a
    plain way to remove one (not only inside the menu's dialog)."""
    page = _page()
    assert 'id="cartchips"' in page and "function cartChips()" in page and "data-rmchip=" in page
    assert "  cartChips();" in page  # drawn with the rest of the page


def test_import_cart_warns_of_unmatched_rows() -> None:
    """Import cart gets a red "!" while the build's carts have rows that
    match no line, so they get matched."""
    page = _page()
    assert ".attn {" in page and "background: var(--bad)" in page
    assert 'attn("cartbtn", left ? "!" : 0,' in page
    assert "const left = BUILD ? (CART.match.unmatched || []).length : 0;" in page


def test_unmatched_rows_are_called_out() -> None:
    """Cart rows that match no line: a bar under the header that says so and
    leads to matching them; the dialog's "Rows to match" with suggestions."""
    page = _page()
    assert 'id="unmatchbar"' in page and 'id="unmatchgo"' in page and "cartDialog(true)" in page
    assert 'id="tomatch"' in page and "data-accept=" in page and 'id="acceptall"' in page


def test_lines_select_like_files() -> None:
    """Click picks a line, Ctrl/Cmd+click adds or removes one, Shift+click a
    range (from the last clicked, in the order shown); parts clicked on the
    board pick their line; Esc or Clear selection lets go."""
    page = _page()
    assert "let sel = new Set(), anchor = null" in page and "function select(i, e, ordered)" in page
    assert "e.ctrlKey || e.metaKey" in page and "e.shiftKey && anchor !== null" in page
    assert "window.bomPick(drag.ref, e)" in page and "window.bomPick(at(e.clientX, e.clientY), e)" in page
    assert 'id="selinfo"' in page and '$("selclear").addEventListener("click", clearSel)' in page
    assert "pinned" not in page.split("// What's lit")[1].split("// ---------------------------------------------------------------- the table")[0]


def test_a_selection_is_ticked_and_placed_together() -> None:
    """With several lines selected, ticking a tracker or placing a part on one
    of them does it for every selected line (DNP left out); the board buttons
    count what's done and what's left."""
    page = _page()
    assert "function actOn(i, refs)" in page
    assert "refs: actOn(+box.dataset.i, l.refs)" in page
    assert "place(actOn(i, [chip.dataset.place])" in page and "place(actOn(i, all.dataset.placeall" in page
    assert '<span class="mk short">${left} ${asm ? "left" : "short"}</span>' in page


def test_problems_are_never_hidden() -> None:
    """Anything that needs the user: a popup (no bare alert), the bell with a
    way back to it, and a "!" on the button that leads to it."""
    page = _page()
    assert "alert(" not in page
    assert "function toast(level, title, detail, go)" in page and "function attn(id, mark, title, kind)" in page
    for place in ("keys:", "carts:", "inventory:", "lookup:"):
        assert place in page.split("const GO = {")[1].split("};")[0]
    for button in ('attn("keybtn"', 'attn("cartbtn"', 'attn("invbtn"', 'attn("lookup"'):
        assert button in page
    assert 'class="go" data-tgo=' in page  # Show in the bell's list
    assert "x.id > seenNotice" in page      # new problems pop up


def test_notices_say_where_to_fix_them() -> None:
    from kigit_gui import notices
    n = notices.add("warning", "BOM: something", "detail", go="bom:keys")
    assert n.to_dict()["go"] == "bom:keys"
    assert notices.add("info", "x").to_dict()["go"] == ""


def test_keyring_fix_steps() -> None:
    """No keyring: steps to fix it, with a command for this Linux to copy."""
    from kigit_gui.bom import keyring_fix
    no_tool = {"keyring": False, "why": "no secret-tool program (install libsecret-tools, ...)"}
    assert keyring_fix(no_tool, ["ubuntu", "debian"])["command"] == "sudo apt install libsecret-tools"
    assert keyring_fix(no_tool, ["linuxmint", "ubuntu"])["command"] == "sudo apt install libsecret-tools"
    assert keyring_fix(no_tool, ["fedora"])["command"] == "sudo dnf install libsecret"
    assert keyring_fix(no_tool, ["arch"])["command"] == "sudo pacman -S libsecret"
    assert keyring_fix(no_tool, ["gentoo"])["command"] == ""  # unknown: said in words, no guess
    off = {"keyring": False, "why": "turned off (KIGIT_KEYRING=off)"}
    assert keyring_fix(off, system="linux")["command"] == "unset KIGIT_KEYRING"
    assert "SetEnvironmentVariable" in keyring_fix(off, system="win32")["command"]  # PowerShell, not a Unix shell
    page_text = (Path(__file__).parents[1] / "kigit_gui" / "bom_page.html").read_text(encoding="utf-8")
    assert "didn't take" in page_text  # a keyring that refused the key isn't shown as "kept in" it
    ssh = keyring_fix({"keyring": False, "why": "no keyring answered: Cannot autolaunch D-Bus"})
    assert ssh["command"] == "" and "SSH" in ssh["steps"][0]
    assert keyring_fix({"keyring": True, "name": "x"}) == {}
    page = (Path(__file__).parents[1] / "kigit_gui" / "bom_page.html").read_text(encoding="utf-8")
    assert '<div id="keystore"></div>' in page and "data-copy=" in page and 'id="keycheck"' in page


def test_look_up_shows_its_progress_by_the_bell() -> None:
    """A ring by the bell fills as the lines are done and spins while kigit
    works; its panel has a bar, the line being looked up, time left, Stop and
    minimise."""
    page = _page()
    assert 'id="activity"' in page and page.index('id="activity"') < page.index('id="bell"')
    assert "#activity.working .spin" in page and "strokeDashoffset" in page
    assert 'id="actmin"' in page and 'id="actstop"' in page and 'post("lookup/stop"' in page
    assert "kigit.bomActMin" in page


def test_stopping_a_look_up(tmp_path) -> None:
    """Stop ends kigit's process; the Look up says stopped, not failed."""
    import time as _time
    from kigit_gui import bom
    look = bom.Lookup()
    assert look.state()["stopped"] is False and look.state()["what"] == ""
    look.started = _time.time() - 5
    assert 4 <= look.state()["elapsed"] <= 7
