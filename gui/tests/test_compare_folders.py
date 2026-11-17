"""Comparing two copies of a project without git (the "Compare folders" box)."""

import asyncio
import shutil
from pathlib import Path

import pytest
from nicegui.testing import User

from fixture_repo import FIXTURES
from kigit_gui import app
from test_app import PROJECT, open_at

pytestmark = pytest.mark.module_under_test(app)


def copies(tmp: Path) -> tuple[Path, Path]:
    """Two loose copies of the demo project (v1 and v2), not in git."""
    out = []
    for name, version in (("before", "v1"), ("after", "v2")):
        d = tmp / name
        d.mkdir()
        shutil.copyfile(FIXTURES / "demo.kicad_pro", d / "demo.kicad_pro")
        for ext in ("kicad_pcb", "kicad_sch"):
            shutil.copyfile(FIXTURES / version / f"demo.{ext}", d / f"demo.{ext}")
        out.append(d)
    return out[0], out[1]


async def fill(user: User, key: str, folder: str) -> None:
    user.find(marker=f"folder-{key}").type(folder).trigger("blur")


async def compare_when_ready(user: User) -> None:
    """Clicks Compare once both boards are found (the button enables then)."""
    button = user.find(marker="compare-folders-go").elements.pop()
    for _ in range(50):
        if button.enabled:
            break
        await asyncio.sleep(0.1)
    assert button.enabled, "Compare never became available"
    user.find(marker="compare-folders-go").click()


async def test_compare_two_folders(user: User, monkeypatch, tmp_path: Path) -> None:
    before, after = copies(tmp_path)
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find(marker="compare-folders").click()
    await user.should_see("Compare two KiCad project folders")
    await fill(user, "old", str(before))
    await fill(user, "new", str(after))
    # Both folders checked (each shows its own ✓; the first may be done well
    # before the second): then Compare is enabled.
    go = user.find(marker="compare-folders-go").elements.pop()
    for _ in range(100):
        if go.enabled:
            break
        await asyncio.sleep(0.1)
    assert go.enabled
    user.find(marker="compare-folders-go").click()
    await user.should_see(marker="viewer", retries=100)
    assert user.find(marker="viewer").elements.pop().props["src"].endswith("#sch")
    await user.should_see("(no git)")


async def test_folders_in_3d(user: User, monkeypatch, tmp_path: Path) -> None:
    """Compare folders has the 3D dock too: each folder's board as it is on
    disk (kigit --3d --disk), new, old or both."""
    from kigit_gui import kigit
    from test_app import marked

    made = []

    async def fake_board3d(project: str, rev: str, out: Path):
        made.append(rev)
        out.write_bytes(b"glTF")
        return kigit.Made3d([], [])

    monkeypatch.setattr(kigit, "board3d", fake_board3d)
    before, after = copies(tmp_path)
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find(marker="compare-folders").click()
    await user.should_see("Compare two KiCad project folders")
    await fill(user, "old", str(before))
    await fill(user, "new", str(after))
    await compare_when_ready(user)
    await user.should_see("(no git)", retries=100)
    dock_button = marked(user, "dock-button")
    assert dock_button.visible  # no git, but still a 3D view
    user.find(marker="dock-button").click()
    frame = marked(user, "dock-viewer")
    for _ in range(50):
        if "/board3d/" in (frame.props.get("src") or ""):
            break
        await asyncio.sleep(0.1)
    assert made == [f"disk:{after / 'demo.kicad_pcb'}"]  # New: the after folder's board
    assert "after" in frame.props["src"]  # named after its folder
    with user.client:
        marked(user, "dock-side").value = "both"
    for _ in range(50):
        if "/board3d-grid" in (frame.props.get("src") or ""):
            break
        await asyncio.sleep(0.1)
    src = frame.props["src"]
    assert sorted(made) == sorted([f"disk:{after / 'demo.kicad_pcb'}", f"disk:{before / 'demo.kicad_pcb'}"])
    assert src.index("before") < src.index("after")  # old first


async def test_folder_without_a_board_is_flagged(user: User, monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find(marker="compare-folders").click()
    await user.should_see("Compare two KiCad project folders")
    await fill(user, "old", str(tmp_path / "empty"))
    await user.should_see("No KiCad board (.kicad_pcb) here", retries=50)


async def test_project_without_git_offers_folder_comparison(user: User, monkeypatch, tmp_path: Path) -> None:
    before, after = copies(tmp_path)
    await open_at(user, monkeypatch, str(after))
    await user.should_see("isn't in a git repository", retries=50)
    user.find(marker="no-git-compare").click()
    await user.should_see("Compare two KiCad project folders", retries=50)
    await user.should_see("✓ demo.kicad_pcb", retries=50)  # the project's own folder, filled in as "New"
    await fill(user, "old", str(before))
    await compare_when_ready(user)
    await user.should_see(marker="viewer", retries=100)
