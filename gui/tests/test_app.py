"""Drives the GUI with NiceGUI's simulated user (no browser needed).

Needs a built kigit and a KiCad project in git, for example:
    KIGIT_BIN=../build/kigit KIGIT_PROJECT=~/my/board uv run pytest
"""

import os

import pytest
from nicegui import ui
from nicegui.events import TableSelectionEventArguments
from nicegui.testing import User

from kigit_gui import app  # noqa: F401  (registers the page)

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("KIGIT_BIN") or not os.environ.get("KIGIT_PROJECT"),
        reason="set KIGIT_BIN and KIGIT_PROJECT to run the GUI tests",
    ),
    pytest.mark.module_under_test(app),  # re-registers the page for each test
]


async def select(user: User, rows: list[dict]) -> None:
    """Selects table rows and notifies the app, as a click in the browser would.
    (The simulated user can't send selection data, so the table's selection
    handlers are called directly.)"""
    table = user.find(ui.table).elements.pop()
    with user.client:
        table.selected = rows
        args = TableSelectionEventArguments(sender=table, client=user.client, selection=rows)
        for handler in table._selection_handlers:  # noqa: SLF001
            handler(args)


async def test_lists_commits(user: User) -> None:
    await user.open("/")
    await user.should_see("commits", retries=50)  # status line: "<board> · N commits"
    table = user.find(ui.table).elements.pop()
    assert any(r["hash"] != "LOCAL" for r in table.rows)


async def test_one_commit_shows_what_it_changed(user: User) -> None:
    await user.open("/")
    await user.should_see("commits", retries=50)
    table = user.find(ui.table).elements.pop()
    commit = next(r for r in table.rows if r["hash"] != "LOCAL")
    await select(user, [commit])
    user.find("Show this commit").click()
    await user.should_see("→", retries=100)  # status line: "<parent> → <commit> · 0.2 s"
    frame = next(e for e in user.find(ui.element).elements if e.tag == "iframe")
    assert "/diffs/" in frame.props.get("src", "")


async def test_two_commits_compare(user: User) -> None:
    await user.open("/")
    await user.should_see("commits", retries=50)
    table = user.find(ui.table).elements.pop()
    commits = [r for r in table.rows if r["hash"] != "LOCAL"][:2]
    await select(user, commits)
    user.find("Compare").click()
    await user.should_see("→", retries=100)
