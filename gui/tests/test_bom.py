"""The BOM page: picks kept next to the board, and the page's script."""

import json
import re
import shutil
import subprocess
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
