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
    # Meshes are merged per material on load, board and parts apart.
    assert 'import { mergeGeometries } from "BufferGeometryUtils"' in page
    assert 'mergeByMaterial(partNodes, "parts")' in page


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


def test_side_by_side_page() -> None:
    """Several boards: one /board3d frame each, views linked through the page."""
    page = board3d.grid_page([("a.glb", "owl · 1a2b", "Rev A"), ("b.glb", "owl · 3c4d", "Rev <B>")])
    assert page.count("<iframe") == 2 and 'src="/board3d/a.glb?title=owl' in page
    assert "Rev+%3CB%3E" in page  # quoted into the address
    assert "grid-template-columns: repeat(2, 1fr)" in page and 'id="linked" checked' in page
    assert '"setCamera" : "setLayer"' in page and "%%" not in page  # views and layers both follow
    four = board3d.grid_page([(f"{i}.glb", "", "") for i in range(4)])
    assert "repeat(2, 1fr)" in four  # 2 x 2
    # Each board sends its camera out and takes the others'.
    one = board3d.page("/diffs/a.glb")
    assert 'kigit3d: "camera"' in one and 'm.kigit3d !== "setCamera"' in one
    # Mask and silkscreen can be hidden, as in KiCad's 3D viewer, and the
    # other boards follow.
    assert 'id="mask" class="on"' in one and 'id="silk" class="on"' in one
    assert 'kigit3d: "layer", name, on' in one and 'm.kigit3d === "setLayer"' in one
    # Silkscreen: solid and in front of the mask, so it shows from low angles.
    assert "m.transparent = false; m.opacity = 1; m.depthWrite = true;" in one
    assert "m.polygonOffsetUnits = -4" in one and "m.polygonOffsetUnits = -2" in one


def test_side_by_side_route() -> None:
    from starlette.requests import Request

    for n in ("aaaaaaaaaaaa.glb", "bbbbbbbbbbbb.glb"):
        (app.CACHE / n).write_bytes(b"glTF")

    def get(query: str):
        req = Request({"type": "http", "method": "GET", "path": "/board3d-grid", "headers": [],
                       "query_string": query.encode()})
        return asyncio.run(board3d._grid(req))  # noqa: SLF001

    ok = get("b=aaaaaaaaaaaa.glb&t=A&s=x&b=bbbbbbbbbbbb.glb&t=B&s=y")
    assert ok.status_code == 200 and ok.body.count(b"<iframe") == 2
    assert get("b=aaaaaaaaaaaa.glb&b=missing.glb").status_code == 404
    assert get("b=../x.glb").status_code == 404
    assert get("&".join(["b=aaaaaaaaaaaa.glb"] * 5)).status_code == 404  # at most four


def test_cached_model_names(tmp_path) -> None:
    board = tmp_path / "b.kicad_pcb"
    board.write_text("x", encoding="utf-8")
    assert app.board3d_name(str(board), "a" * 40) == app.board3d_name(str(board), "a" * 40)
    assert app.board3d_name(str(board), "a" * 40) != app.board3d_name(str(board), "b" * 40)
    local = app.board3d_name(str(board), app.LOCAL)
    board.write_text("changed", encoding="utf-8")  # the working tree changed: a new model
    assert app.board3d_name(str(board), app.LOCAL) != local
