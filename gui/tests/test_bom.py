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
    assert bom.load_drafts(board) == {"drafts": {}, "columns": []}
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


def test_version_1_picks_are_read_as_drafts(tmp_path: Path) -> None:
    (tmp_path / bom.DRAFTS).write_text(json.dumps({"version": 1, "picks": {
        "10k|R_0603": {"mpn": "RC0603FR-0710KL", "manufacturer": "Yageo", "note": "cheap", "updated": "2026-11-18"}}}),
        encoding="utf-8")
    state = bom.load_drafts(tmp_path / "x.kicad_pcb")
    assert state["drafts"]["10k|R_0603"] == {"MPN": "RC0603FR-0710KL", "Manufacturer": "Yageo", "Note": "cheap"}
    assert state["columns"] == ["Note"]


def test_broken_drafts_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / bom.DRAFTS).write_text("{not json", encoding="utf-8")
    assert bom.load_drafts(tmp_path / "x.kicad_pcb") == {"drafts": {}, "columns": []}


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

    assert asyncio.run(kigit.bom_keys())["mouser"] == {"set": False, "env": False, "name": "Mouser"}
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
    assert 'const PANES = ["showlist", "show2d", "show3d"]' in page
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
