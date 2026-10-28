"""The GUI's session logging (kigit_gui/logs.py and how the app uses it)."""

import os
import re
from pathlib import Path

import pytest
from nicegui.testing import User

from kigit_gui import app, kigit, logs
from test_app import PROJECT, open_at

LINE = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}\] \[(kigit|kigit-gui)\] \[(debug|info|warning|error)\] ")


@pytest.fixture
def session(tmp_path: Path):
    """A session log in a temporary folder, closed afterwards."""
    path = logs.start(str(tmp_path), console=False)
    yield path
    logs.stop()


def test_session_file_name_format_and_tail(session: Path) -> None:
    assert re.fullmatch(r"kigit-gui_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_\d+\.log", session.name)
    logs.log.info("hello")
    lines = logs.tail()
    assert lines and LINE.match(lines[-1]) and lines[-1].endswith("hello")
    assert os.environ[logs.SESSION_FILE_ENV] == str(session)


def test_starting_again_starts_a_new_file(tmp_path: Path) -> None:
    first = logs.start(str(tmp_path / "a"), console=False)
    second = logs.start(str(tmp_path / "b"), console=False)
    logs.log.info("only in the second")
    logs.stop()
    assert "only in the second" not in first.read_text()
    assert "only in the second" in second.read_text()


def test_no_log_means_no_file(tmp_path: Path) -> None:
    assert logs.start(str(tmp_path), enabled=False, console=False) is None
    assert logs.tail() == []
    assert logs.SESSION_FILE_ENV not in os.environ
    assert list(tmp_path.iterdir()) == []
    logs.stop()


def test_log_dir_from_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KIGIT_LOG_DIR", str(tmp_path))
    assert logs.default_dir() == tmp_path


async def test_kigit_calls_append_to_the_session_log(session: Path) -> None:
    await kigit.history(PROJECT)
    text = session.read_text()
    assert "[kigit] [info] run: kigit" in text   # kigit's own lines, in the GUI's file
    assert "[kigit] [info] done: exit 0" in text
    assert "session start" not in text           # a step of the GUI's session, not its own
    assert all(LINE.match(l) for l in text.splitlines())


async def test_failed_kigit_call_is_logged(session: Path) -> None:
    with pytest.raises(kigit.KigitError):
        await kigit.diff_html(PROJECT, "no-such-commit", "HEAD", session.parent / "x.html")
    text = session.read_text()
    assert "unknown revision 'no-such-commit'" in text
    assert "[kigit-gui] [warning]" in text


@pytest.mark.module_under_test(app)
async def test_messages_shown_to_the_user_are_logged(user: User, monkeypatch, session: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    await open_at(user, monkeypatch, str(empty))
    await user.should_see("No KiCad project found", retries=50)
    assert "shown to user: No KiCad project found" in session.read_text()


@pytest.mark.module_under_test(app)
async def test_log_button_shows_the_session_log(user: User, monkeypatch, session: Path) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find(marker="log-button").click()
    await user.should_see("Session log")
    await user.should_see(str(session))
