"""The 3D diff page (beta): its script must at least parse, since nothing
else runs it outside a browser."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from kigit_gui import board3d_diff


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js to check the script")
def test_page_script_parses(tmp_path: Path) -> None:
    page = board3d_diff.page(board3d_diff.Job("t", "new.glb", "old.glb", "d.json"))
    scripts = re.findall(r'<script type="module">(.*?)</script>', page, re.S)
    assert len(scripts) == 1
    # The imports are resolved by the importmap; node only needs to parse.
    body = re.sub(r'^import .*? from "\w+";$', "", scripts[0], flags=re.M)
    f = tmp_path / "page.mjs"
    f.write_text(body, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_page_has_hover_and_stats() -> None:
    page = board3d_diff.page(board3d_diff.Job("t", "new.glb", "old.glb", "d.json"))
    assert 'id="tip"' in page and "kigit3dPick" in page  # hovering a part
    assert "statsTable" in page and "UNMASKED_RENDERER_WEBGL" in page
