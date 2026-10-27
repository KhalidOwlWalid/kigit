"""Drives the GUI with NiceGUI's simulated user (no browser needed).

By default the tests use the demo project from tests/make_fixture_repo.sh
(built in a temporary folder) and kigit from ../build, so just:
    uv run pytest
Or point them at your own project and binary:
    KIGIT_BIN=../build/kigit KIGIT_PROJECT=~/my/board uv run pytest
KIGIT_PROJECT is the project folder itself (the tests also open its parent
folder to check the 2-level search).
"""

import atexit
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.events import TableSelectionEventArguments
from nicegui.testing import User

from kigit_gui import app

REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_bin() -> str:
    built = REPO_ROOT / "build" / "kigit"
    return str(built) if built.exists() else ""


def _fixture_project() -> str:
    """Builds the demo repo once per test run and returns its project folder."""
    script = os.environ.get("KIGIT_MAKE_REPO", str(REPO_ROOT / "tests" / "make_fixture_repo.sh"))
    if not Path(script).exists():
        return ""
    tmp = Path(tempfile.mkdtemp(prefix="kigit-gui-test-"))
    atexit.register(shutil.rmtree, tmp, True)
    subprocess.run(["sh", script, str(tmp / "repo")], check=True, capture_output=True)
    return str(tmp / "repo" / "board")


os.environ.setdefault("KIGIT_BIN", _default_bin())
PROJECT = os.environ.get("KIGIT_PROJECT") or _fixture_project()

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("KIGIT_BIN") or not PROJECT,
        reason="build kigit first (../build/kigit) or set KIGIT_BIN and KIGIT_PROJECT",
    ),
    pytest.mark.module_under_test(app),  # re-registers the page for each test
]


async def open_at(user: User, monkeypatch, folder: str) -> None:
    """Starts the GUI in `folder`, like `kigit gui FOLDER`."""
    monkeypatch.setenv("KIGIT_PROJECT", folder)
    await user.open("/")


def commit_table(user: User):
    return user.find(ui.table).elements.pop()


async def select(user: User, rows: list[dict]) -> None:
    """Selects table rows and notifies the app, as a click in the browser would.
    (The simulated user can't send selection data, so the table's selection
    handlers are called directly.)"""
    table = commit_table(user)
    with user.client:
        table.selected = rows
        args = TableSelectionEventArguments(sender=table, client=user.client, selection=rows)
        for handler in table._selection_handlers:  # noqa: SLF001
            handler(args)


async def test_lists_commits_with_working_tree_on_top(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    rows = commit_table(user).rows
    assert rows[0]["hash"] == "LOCAL" and rows[0]["subject"].startswith("HEAD")
    assert len(rows) > 2
    assert all(r["tip"] for r in rows)  # hover text with the full message


async def test_finds_project_one_level_down(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, str(Path(PROJECT).parent))
    await user.should_see("Pick two commits on the left", retries=50)


async def test_compare_needs_two_and_opens_schematic(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    rows = commit_table(user).rows
    await select(user, [rows[1]])
    await user.should_see("pick one more")
    await select(user, [rows[1], rows[2]])
    user.find("Compare").click()
    await user.should_see(marker="viewer", retries=100)  # shown once the diff is ready
    frame = user.find(marker="viewer").elements.pop()
    assert frame.props["src"].endswith("#sch")


async def test_empty_folder_is_flagged(user: User, monkeypatch, tmp_path: Path) -> None:
    await open_at(user, monkeypatch, str(tmp_path))
    await user.should_see("No KiCad project found", retries=50)


async def test_project_three_levels_down_is_not_found(user: User, monkeypatch, tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "x.kicad_pro").write_text("{}")
    (deep / "x.kicad_pcb").write_text("(kicad_pcb)")
    await open_at(user, monkeypatch, str(tmp_path))
    await user.should_see("No KiCad project found", retries=50)


async def test_project_without_git_is_flagged(user: User, monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "board").mkdir()
    (tmp_path / "board" / "x.kicad_pro").write_text("{}")
    (tmp_path / "board" / "x.kicad_pcb").write_text("(kicad_pcb)")
    await open_at(user, monkeypatch, str(tmp_path))
    await user.should_see("isn't in a git repository", retries=50)


async def test_several_projects_ask_which(user: User, monkeypatch, tmp_path: Path) -> None:
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        (tmp_path / name / f"{name}.kicad_pro").write_text("{}")
        (tmp_path / name / f"{name}.kicad_pcb").write_text("(kicad_pcb)")
    await open_at(user, monkeypatch, str(tmp_path))
    await user.should_see("2 KiCad projects found", retries=50)


async def test_find_only_board_or_schematic_commits(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find("Only commits that changed the board or schematic").click()
    user.find("Find").click()
    await user.should_see("commits changed the board or schematic", retries=50)
    rows = commit_table(user).rows[1:]  # skip the working tree
    assert rows and all(r["pcb"] or r["sch"] for r in rows)


async def test_history_limit_and_dates() -> None:
    """The CLI wrapper: limit, total and date range."""
    from kigit_gui import kigit

    h = await kigit.history(PROJECT, max_count=5)
    assert len(h.commits) == min(5, h.total) and h.total >= len(h.commits)
    everything = await kigit.history(PROJECT, max_count=0)
    assert len(everything.commits) == everything.total
    newest = everything.commits[0].date[:10]
    recent = await kigit.history(PROJECT, max_count=0, since=newest)
    assert 1 <= len(recent.commits) <= everything.total
    assert all(c.date[:10] >= newest for c in recent.commits)


async def test_diff_commits_manually(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find("Diff commits manually").click()
    user.find("Old").type("HEAD~1")
    user.find("New").type("LOCAL")
    user.find("Find manually").click()
    await user.should_see(marker="viewer", retries=100)
    assert user.find(marker="viewer").elements.pop().props["src"].endswith("#sch")


async def test_diff_manually_reports_bad_commit(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find("Diff commits manually").click()
    user.find("Old").type("no-such-commit")
    user.find("New").type("HEAD")
    user.find("Find manually").click()
    await user.should_see("unknown revision", retries=50)


async def test_diff_manually_needs_both(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find("Diff commits manually").click()
    user.find("Old").type("HEAD")
    user.find("Find manually").click()
    await user.should_see("Enter both an old and a new commit")
