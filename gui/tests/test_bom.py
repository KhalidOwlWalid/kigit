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


def test_picks_saved_next_to_the_board(tmp_path: Path) -> None:
    board = tmp_path / "x.kicad_pcb"
    assert bom.load_picks(board) == {}
    picks = bom.save_pick(board, "10k|R_0603", {"mpn": " RC0603FR-0710KL ", "manufacturer": "Yageo", "junk": "x"})
    assert picks["10k|R_0603"]["mpn"] == "RC0603FR-0710KL" and "junk" not in picks["10k|R_0603"]
    saved = json.loads((tmp_path / bom.PICKS).read_text(encoding="utf-8"))
    assert saved["version"] == 1 and saved["picks"]["10k|R_0603"]["manufacturer"] == "Yageo"
    bom.save_pick(board, "100n|C_0603", {"mpn": "CL10B104KB8NNNC"})
    assert set(bom.load_picks(board)) == {"10k|R_0603", "100n|C_0603"}  # re-read, not overwritten
    bom.save_pick(board, "10k|R_0603", {"mpn": "", "note": ""})  # emptied: gone
    bom.save_pick(board, "100n|C_0603", {})
    assert not (tmp_path / bom.PICKS).exists()  # nothing left: no file


def test_broken_picks_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / bom.PICKS).write_text("{not json", encoding="utf-8")
    assert bom.load_picks(tmp_path / "x.kicad_pcb") == {}


def _page() -> str:
    return bom.page("k", bom.Job(str(Path("/p/owl.kicad_pcb")), "owl · working tree", DATA))


def test_page_has_the_data_and_no_html_injection() -> None:
    evil = json.loads(json.dumps(DATA))
    evil["lines"][0]["value"] = "</script><script>alert(1)</script>"
    page = bom.page("k", bom.Job("/p/owl.kicad_pcb", "<b>t</b>", evil))
    assert "</script><script>alert" not in page and "&lt;b&gt;t&lt;/b&gt;" in page


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
