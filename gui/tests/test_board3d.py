"""The 3D view's page and the files it loads (board3d.py)."""

import asyncio

from kigit_gui import app, board3d


def test_page_loads_the_model_with_the_bundled_three() -> None:
    page = board3d.page("/diffs/abc.glb", "owl · 1a2b3c4", "Rev <B>")
    assert '"/diffs/abc.glb"' in page and '"three": "/kigit-three/three.module.js"' in page
    assert "owl · 1a2b3c4" in page and "Rev &lt;B&gt;" in page  # escaped
    assert "%%" not in page
    # Render stats: off until ?stats=1 or S; scripts can read them.
    assert 'has("stats")' in page and "window.kigit3dStats = report" in page
    assert 'id="stats"' in page and "#stats.on { display: flex; }" in page


def test_routes() -> None:
    (app.CACHE / "0123456789ab.glb").write_bytes(b"glTF")
    ok = asyncio.run(board3d._page("0123456789ab.glb", title="t"))  # noqa: SLF001
    assert ok.status_code == 200 and b"/diffs/0123456789ab.glb" in ok.body
    assert asyncio.run(board3d._page("missing.glb")).status_code == 404  # noqa: SLF001
    assert asyncio.run(board3d._page("../x.glb")).status_code == 404  # noqa: SLF001
    for f in board3d.THREE_FILES:  # NiceGUI still ships what the page imports
        assert (board3d.THREE / f).is_file(), f
    assert asyncio.run(board3d._three("three.module.js")).status_code == 200  # noqa: SLF001
    assert asyncio.run(board3d._three("../../../../nicegui.py")).status_code == 404  # noqa: SLF001


def test_cached_model_names(tmp_path) -> None:
    board = tmp_path / "b.kicad_pcb"
    board.write_text("x")
    assert app.board3d_name(str(board), "a" * 40) == app.board3d_name(str(board), "a" * 40)
    assert app.board3d_name(str(board), "a" * 40) != app.board3d_name(str(board), "b" * 40)
    local = app.board3d_name(str(board), app.LOCAL)
    board.write_text("changed")  # the working tree changed: a new model
    assert app.board3d_name(str(board), app.LOCAL) != local
