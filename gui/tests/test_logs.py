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
    path = logs.start(str(tmp_path), console="off")
    yield path
    logs.stop()


def test_session_file_name_format_and_tail(session: Path) -> None:
    assert re.fullmatch(r"kigit-gui_\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_\d+\.log", session.name)
    logs.log.info("hello")
    lines = logs.tail()
    assert lines and LINE.match(lines[-1]) and lines[-1].endswith("hello")
    assert os.environ[logs.SESSION_FILE_ENV] == str(session)


def test_starting_again_starts_a_new_file(tmp_path: Path) -> None:
    first = logs.start(str(tmp_path / "a"), console="off")
    second = logs.start(str(tmp_path / "b"), console="off")
    logs.log.info("only in the second")
    logs.stop()
    assert "only in the second" not in first.read_text(encoding="utf-8")
    assert "only in the second" in second.read_text(encoding="utf-8")


def test_no_log_means_no_file(tmp_path: Path) -> None:
    assert logs.start(str(tmp_path), enabled=False, console="off") is None
    assert logs.tail() == []
    assert logs.SESSION_FILE_ENV not in os.environ
    assert list(tmp_path.iterdir()) == []
    logs.stop()


def test_log_dir_from_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KIGIT_LOG_DIR", str(tmp_path))
    assert logs.default_dir() == tmp_path


async def test_kigit_calls_append_to_the_session_log(session: Path) -> None:
    await kigit.history(PROJECT)
    text = session.read_text(encoding="utf-8")
    assert "[kigit] [info] run: $ kigit -C " in text   # kigit's own lines, in the GUI's file
    assert "[kigit] [info] done: exit 0" in text
    assert "session start" not in text           # a step of the GUI's session, not its own
    assert all(LINE.match(l) for l in text.splitlines())


async def test_failed_kigit_call_is_logged(session: Path) -> None:
    with pytest.raises(kigit.KigitError):
        await kigit.diff_html(PROJECT, "no-such-commit", "HEAD", session.parent / "x.html")
    text = session.read_text(encoding="utf-8")
    assert "unknown revision 'no-such-commit'" in text
    assert "[kigit-gui] [warning]" in text


@pytest.mark.module_under_test(app)
async def test_messages_shown_to_the_user_are_logged(user: User, monkeypatch, session: Path, tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    await open_at(user, monkeypatch, str(empty))
    await user.should_see(marker="landing", retries=50)  # started outside a project
    user.find(marker="open-button").click()
    await user.should_see("No KiCad project found", retries=50)
    assert "shown to user: No KiCad project found" in session.read_text(encoding="utf-8")


@pytest.mark.module_under_test(app)
async def test_log_button_shows_the_session_log(user: User, monkeypatch, session: Path) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find(marker="log-button").click()
    await user.should_see("Session log")
    await user.should_see(str(session))


def test_levels_for_the_file_and_the_console(tmp_path: Path, capsys) -> None:
    """The file and the console each have a level; kigit calls get the same."""
    path = logs.start(str(tmp_path), file="warning", console="error")
    logs.log.debug("a step")
    logs.log.info("done something")
    logs.log.warning("look at this")
    logs.log.error("broken")
    logs.stop()
    text = path.read_text(encoding="utf-8")
    assert "a step" not in text and "done something" not in text
    assert "look at this" in text and "broken" in text
    err = capsys.readouterr().err
    assert "broken" in err and "look at this" not in err

    path = logs.start(str(tmp_path / "d"), console="off")  # the defaults: debug in the file
    logs.log.debug("a step")
    assert logs.kigit_flags() == ["--log-file", str(path), "--log-level", "debug"]
    logs.stop()
    assert "a step" in path.read_text(encoding="utf-8")
    assert capsys.readouterr().err == ""

    logs.start(str(tmp_path / "e"), file="info", console="warning")
    assert logs.kigit_flags()[2:] == ["--log-level", "info", "--console-level", "warning"]
    logs.stop()
    with pytest.raises(ValueError, match="unknown log level 'loud'"):
        logs.start(str(tmp_path), file="loud")
    logs.stop()


def test_levels_from_the_environment(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KIGIT_LOG_LEVEL", "info")
    monkeypatch.setenv("KIGIT_CONSOLE_LEVEL", "off")
    path = logs.start(str(tmp_path))
    logs.log.debug("a step")
    logs.log.info("done")
    logs.stop()
    text = path.read_text(encoding="utf-8")
    assert "a step" not in text and "done" in text
    assert logs.console_level == "off"


async def test_kigit_calls_log_their_debug_lines(session: Path) -> None:
    """At the default file level, kigit's debug lines are in the GUI's file."""
    await kigit.history(PROJECT)
    text = session.read_text(encoding="utf-8")
    assert "[kigit] [debug] $ git -C " in text and "  [exit 0, " in text  # each command, as you'd type it
    assert "[kigit-gui] [debug] $ kigit -C " in text
