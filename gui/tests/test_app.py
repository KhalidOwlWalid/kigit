"""Drives the GUI with NiceGUI's simulated user (no browser needed).

By default the tests use the demo project (fixture_repo.py, built in a
temporary folder) and kigit from ../build, so just:
    uv run pytest
Or point them at your own project and binary:
    KIGIT_BIN=../build/kigit KIGIT_PROJECT=~/my/board uv run pytest
KIGIT_PROJECT is the project folder itself (the tests also open its parent
folder to check the 2-level search).
"""

import asyncio
import json
import atexit
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.events import TableSelectionEventArguments
from nicegui.testing import User

from kigit_gui import app

from fixture_repo import make_fixture_repo

REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_bin() -> str:
    for name in ("kigit", "kigit.exe", "Release/kigit.exe", "Debug/kigit.exe"):
        built = REPO_ROOT / "build" / name
        if built.exists():
            return str(built)
    return ""


def _fixture_project() -> str:
    """Builds the demo repo once per test run and returns its project folder."""
    tmp = Path(tempfile.mkdtemp(prefix="kigit-gui-test-"))
    atexit.register(shutil.rmtree, tmp, True)
    return str(make_fixture_repo(tmp / "repo"))


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
    """Started outside a project: the landing page. Opening that folder on
    purpose: it says there's no project."""
    await open_at(user, monkeypatch, str(tmp_path))
    await user.should_see(marker="landing", retries=50)
    user.find(marker="open-button").click()
    await user.should_see("No KiCad project found", retries=50)


async def test_start_in_a_project_without_board_shows_landing(user: User, monkeypatch, tmp_path: Path) -> None:
    """A .kicad_pro without a board (like the kigit repo's test fixtures):
    nothing to open, so kigit gui starts on the landing page."""
    (tmp_path / "x.kicad_pro").write_text("{}")
    await open_at(user, monkeypatch, str(tmp_path))
    await user.should_see(marker="landing", retries=50)
    user.find(marker="open-button").click()  # opened on purpose: it says why
    await user.should_see("Found a KiCad project, but no board file.", retries=50)


async def test_project_three_levels_down_is_not_found(user: User, monkeypatch, tmp_path: Path) -> None:
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "x.kicad_pro").write_text("{}")
    (deep / "x.kicad_pcb").write_text("(kicad_pcb)")
    await open_at(user, monkeypatch, str(tmp_path))
    await user.should_see(marker="landing", retries=50)
    user.find(marker="open-button").click()
    await user.should_see("No KiCad project found", retries=50)


async def test_landing_page_recent_projects(user: User, monkeypatch, tmp_path: Path) -> None:
    """Opening a project lists it on the landing page; from there it opens
    again, or resumes the last comparison."""
    from kigit_gui import sessions

    monkeypatch.setattr(sessions, "path", lambda: tmp_path / "sessions.json")
    project = make_fixture_repo(tmp_path / "repo")
    empty = tmp_path / "empty"
    empty.mkdir()
    await open_at(user, monkeypatch, str(empty))
    await user.should_see(marker="landing-empty", retries=50)  # nothing opened yet

    # Open it, compare two commits: both remembered.
    user.find(marker="folder-input").clear().type(str(project))
    user.find(marker="open-button").click()
    await user.should_see("Pick two commits on the left", retries=50)
    rows = commit_table(user).rows
    await select(user, [rows[1], rows[2]])
    user.find(marker="compare-button").click()
    viewer = marked(user, "viewer")
    for _ in range(100):
        if "/diffs/" in (viewer.props.get("src") or "") and sessions.load() and sessions.load()[0].last:
            break
        await asyncio.sleep(0.1)
    s = sessions.load()[0]
    assert s.name == "demo" and s.last.new_label == rows[1]["short"]

    # Home (the header's "kigit"): the project's card; Resume compares again.
    user.find(marker="home").click()
    await user.should_see(marker="session-card")
    await user.should_see(f"Last compared {rows[2]['short']} ↔ {rows[1]['short']}")
    viewer.props["src"] = ""
    user.find(marker="session-resume").click()
    for _ in range(100):
        if "/diffs/" in (viewer.props.get("src") or ""):
            break
        await asyncio.sleep(0.1)
    assert "/diffs/" in viewer.props["src"] and not marked(user, "landing").visible


async def test_landing_cards_show_board_pictures(user: User, monkeypatch, tmp_path: Path) -> None:
    """Opening a project takes a picture of its board (kigit --render) for
    its card on the landing page; once, until the board changes."""
    from kigit_gui import kigit, sessions

    monkeypatch.setattr(sessions, "path", lambda: tmp_path / "state" / "sessions.json")
    made = []

    async def fake_render(board: str, out: Path) -> None:
        made.append(board)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr(kigit, "render", fake_render)
    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    for _ in range(50):
        if made:
            break
        await asyncio.sleep(0.1)
    board = str(project / "demo.kicad_pcb")
    assert made == [board] and sessions.thumb_fresh(board)
    user.find(marker="home").click()
    await user.should_see(marker="session-thumb", retries=30)
    img = user.find(marker="session-thumb").elements.pop()
    assert img.source.startswith(f"/session-thumb/{sessions.thumb_key(board)}.png")
    assert made == [board]  # fresh: not made again
    from kigit_gui import app as gui_app
    response = await gui_app._session_thumb(sessions.thumb_key(board))  # noqa: SLF001
    assert response.status_code == 200
    assert (await gui_app._session_thumb("../../etc")).status_code == 404  # noqa: SLF001


async def test_shortcuts_list(user: User, monkeypatch) -> None:
    """The header's keyboard button (and "?") lists every shortcut, by area."""
    from kigit_gui import shortcuts

    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find(marker="shortcuts-button").click()
    await user.should_see("Shortcuts")
    assert len(user.find(marker="shortcut-group").elements) == len(shortcuts.GROUPS)
    await user.should_see("Render stats")
    await user.should_see("Up to the parent sheet")


async def test_try_the_example_project(user: User, monkeypatch, tmp_path: Path) -> None:
    """The landing page's example button makes the example project (kigit
    example) in the app folder and opens it: its history, its reviews and
    its discussions."""
    from kigit_gui import sessions

    monkeypatch.setattr(sessions, "path", lambda: tmp_path / "state" / "sessions.json")
    empty = tmp_path / "empty"
    empty.mkdir()
    await open_at(user, monkeypatch, str(empty))
    await user.should_see(marker="landing", retries=50)
    user.find(marker="landing-example").click()
    await user.should_see("Pick two commits on the left", retries=100)
    rows = commit_table(user).rows
    assert rows[0]["hash"] == app.LOCAL and "uncommitted" in rows[0]["subject"]
    assert [r["subject"] for r in rows[1:3]] == ["Add design notes: reviews and discussions",
                                                 "Move the project into hardware/"]
    assert sum(r["reviewed"] for r in rows) == 2
    assert marked(user, "discussions-badge").text == "2"  # one needs attention, one done
    assert (tmp_path / "state" / "example" / "hardware" / "blinky.kicad_pcb").exists()


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
    user.find(kind=ui.input, content="Old").type("HEAD~1")
    user.find(kind=ui.input, content="New").type("LOCAL")
    user.find("Find manually").click()
    await user.should_see(marker="viewer", retries=100)
    assert user.find(marker="viewer").elements.pop().props["src"].endswith("#sch")


async def test_diff_manually_reports_bad_commit(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find("Diff commits manually").click()
    user.find(kind=ui.input, content="Old").type("no-such-commit")
    user.find(kind=ui.input, content="New").type("HEAD")
    user.find("Find manually").click()
    await user.should_see("unknown revision", retries=50)


async def test_diff_manually_needs_both(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    user.find("Diff commits manually").click()
    user.find(kind=ui.input, content="Old").type("HEAD")
    user.find("Find manually").click()
    await user.should_see("Enter both an old and a new commit")


async def test_include_silkscreen_checkbox(user: User, monkeypatch) -> None:
    """Off by default; when ticked, the compared page includes the silkscreen."""
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    box = user.find(marker="include-silkscreen").elements.pop()
    assert box.value is False
    rows = commit_table(user).rows

    async def compare() -> str:
        frame = next(e for e in user.client.elements.values() if e.tag == "iframe")  # hidden at first
        before = frame.props.get("src")
        await select(user, [rows[1], rows[-1]])
        user.find("Compare").click()
        for _ in range(100):  # until the viewer shows the new page
            if frame.props.get("src") != before:
                break
            await asyncio.sleep(0.1)
        src = frame.props["src"]
        return (app.CACHE / src.split("/diffs/")[1].split("?")[0]).read_text(encoding="utf-8")

    assert '"silk":null' in await compare()
    box.value = True
    page = await compare()
    assert '"silk":[' in page


async def test_include_source_checkbox(user: User, monkeypatch) -> None:
    """Off by default; when ticked, the page has the changed items' file text."""
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    box = user.find(marker="include-source").elements.pop()
    assert box.value is False
    rows = commit_table(user).rows

    async def compare() -> str:
        frame = next(e for e in user.client.elements.values() if e.tag == "iframe")  # hidden at first
        before = frame.props.get("src")
        await select(user, [rows[1], rows[-1]])
        user.find("Compare").click()
        for _ in range(100):  # until the viewer shows the new page
            if frame.props.get("src") != before:
                break
            await asyncio.sleep(0.1)
        src = frame.props["src"]
        return (app.CACHE / src.split("/diffs/")[1].split("?")[0]).read_text(encoding="utf-8")

    assert '"src":[' not in await compare()
    box.value = True
    page = await compare()
    assert '"src":[{' in page
    assert "demo.kicad_pcb" in page


def emit(user: User, event: str, args) -> None:
    """Sends a page event (emitEvent in the browser), e.g. what the viewer
    reports as pinned."""
    from nicegui.events import GenericEventArguments, handle_event

    with user.client:
        for listener in list(user.client.layout._event_listeners.values()):  # noqa: SLF001
            if listener.type == event:  # handle_event: async handlers run too, as in the app
                handle_event(listener.handler, GenericEventArguments(sender=user.client.layout, client=user.client,
                                                                     args=args))


async def test_review_a_commit(user: User, monkeypatch, tmp_path: Path) -> None:
    """Review one commit: it's diffed against its parent, notes point at what's
    pinned in the viewer, and Write puts it in <project>/reviews/."""
    from kigit_gui import review

    project = make_fixture_repo(tmp_path / "repo")  # its own repo: this test writes files
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    rows = commit_table(user).rows
    v2 = next(r for r in rows if r["subject"].startswith("v2"))
    docs = next(r for r in rows if r["subject"] == "docs only")
    assert v2["parent"] == docs["hash"] and not v2["reviewed"]

    await select(user, [rows[0]])  # the working tree can't be reviewed (yet)
    assert not user.find(marker="review-button").elements.pop().enabled
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(marker="viewer", retries=100)
    assert user.find(marker="review-panel").elements.pop().value  # the drawer is open
    src = user.find(marker="viewer").elements.pop().props["src"]
    page = (app.CACHE / src.split("/diffs/")[1].split("?")[0]).read_text(encoding="utf-8")
    assert docs["short"] in page and v2["short"] in page  # its parent .. it

    # Nothing is written until there's something to keep.
    assert not (project / "reviews").exists()
    user.find(marker="review-summary").type("Rev B feedback.")
    # What the viewer reports when C1 is pinned (pcb.js tellPinned).
    seen = {"old": docs["hash"], "new": v2["hash"], "side": "new"}
    emit(user, "kigit_pinned", {"tab": "pcb", "kind": "footprint", "name": "C1", "seen": seen})
    await user.should_see("Footprint C1")
    user.find(marker="review-add-note").click()
    user.find(marker="review-note-title").type("Added C1")
    user.find(marker="review-note-body").type("Decoupling for U1.")

    # Nothing is written until Write.
    await user.should_see("Unsaved changes")
    await asyncio.sleep(0.3)
    assert not (project / "reviews").exists()
    await user.should_see("Not written yet")  # the note
    user.find(marker="review-write").click()
    await user.should_see("Written to reviews/")
    assert not user.find(marker="review-write").elements.pop().enabled
    times = user.find(marker="review-note-times").elements.pop()
    assert times.text.startswith("Written 20") and "edited" not in times.text
    user.find(marker="review-note-body").type(" Plus bulk.")
    user.find(marker="review-write").click()
    for _ in range(20):
        if "edited" in times.text:
            break
        await asyncio.sleep(0.05)
    assert " · edited 20" in times.text
    r = review.load(review.all_reviews(project)[v2["hash"]])
    assert (r.parent, r.summary) == (docs["hash"], "Rev B feedback.")
    assert [(n.title, n.body, n.anchor) for n in r.notes] == [
        ("Added C1", "Decoupling for U1. Plus bulk.", review.Anchor("pcb", "footprint", "C1", review.Seen(**seen)))]
    assert r.notes[0].created and r.notes[0].edited
    assert next(x for x in commit_table(user).rows if x["hash"] == v2["hash"])["reviewed"]
    assert (r.date, r.author) == (v2["date"], "kigit tests")
    await user.should_see(f"ID {r.id}")
    assert f"[{r.id}]({r.id}.md)" in (project / "reviews" / "index.md").read_text(encoding="utf-8")

    # Something this commit removed is marked so.
    emit(user, "kigit_pinned", {"tab": "sch", "kind": "part", "name": "R9", "seen": {**seen, "side": "old"}})
    await user.should_see("Part R9 · removed")


async def test_add_a_link(user: User, monkeypatch, tmp_path: Path) -> None:
    """The link button asks for an address and puts a Markdown link around
    the selected text."""
    import re as regex

    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    v2 = next(r for r in commit_table(user).rows if r["subject"].startswith("v2"))
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-summary", retries=100)
    user.find(marker="review-summary").type("See the datasheet for limits.")
    user.javascript_rules[regex.compile(r"window\.kigitSelection")] = lambda _: [8, 17]  # "datasheet"
    user.find(marker="review-summary-link").click()
    await user.should_see(marker="link-url")
    assert user.find(marker="link-text").elements.pop().value == "datasheet"
    user.find(marker="link-url").type("ti.com/lit/ds/tps62130.pdf")
    user.find(marker="link-add").click()
    await user.should_not_see(marker="link-url")
    box = user.find(marker="review-summary").elements.pop()
    assert box.value == "See the [datasheet](https://ti.com/lit/ds/tps62130.pdf) for limits."
    await user.should_see("Unsaved changes")


async def test_markdown_editor(user: User, monkeypatch, tmp_path: Path) -> None:
    """The review's text boxes are Markdown editors like GitHub's: Write and
    Preview, a toolbar, and files added by paste, drop or click: stored in
    reviews/assets/ and served back (pictures shown, others downloaded)."""
    from starlette.requests import Request

    from kigit_gui import review_panel

    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    v2 = next(r for r in commit_table(user).rows if r["subject"].startswith("v2"))
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-summary", retries=100)
    for action in ("heading", "bold", "italic", "quote", "code", "link", "bullets", "numbers", "tasks"):
        button = marked(user, f"review-summary-{action}")
        assert action == "link" or button.props.get("data-md") == action  # the page formats those
    await user.should_see("Paste, drop, or click to add files")

    # Preview renders what's written; Write goes back to the text.
    user.find(marker="review-summary").type("**Rev B** and $x^2$")
    user.find(marker="review-summary-preview").click()
    rendered = marked(user, "review-summary-rendered")
    assert rendered.visible and "<strong>Rev B</strong>" in rendered.content and "<math" in rendered.content
    assert not marked(user, "review-summary").visible
    user.find(marker="review-summary-write").click()
    assert marked(user, "review-summary").visible and not rendered.visible

    # The upload route (what the page calls with a dropped file).
    key = marked(user, "review-summary-editor").props["data-key"]

    async def post(body: bytes, name: str, mime: str):
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        headers = [(b"content-type", mime.encode()), (b"x-filename", name.encode())]
        scope = {"type": "http", "method": "POST", "path": "/", "headers": headers, "query_string": b""}
        return await review_panel._upload(key, Request(scope, receive))  # noqa: SLF001

    r = await post(b"%PDF-1.7", "data%20sheet.pdf", "application/pdf")
    got = json.loads(r.body)
    assert got["markdown"] == f"[data sheet.pdf]({got['path']})"
    assert (project / "reviews" / got["path"]).read_bytes() == b"%PDF-1.7"
    served = await review_panel._image(key, got["path"].split("/")[1])  # noqa: SLF001
    assert served.media_type == "application/pdf"
    r = await post(b"MZ\x90", "tool.exe", "application/octet-stream")
    exe = json.loads(r.body)["path"]
    served = await review_panel._image(key, exe.split("/")[1])  # noqa: SLF001
    assert served.media_type == "application/octet-stream" and "attachment" in served.headers["content-disposition"]
    assert (await post(b"", "empty.txt", "text/plain")).status_code == 400
    assert (await review_panel._image(key, "../review.md")).status_code == 404  # noqa: SLF001


async def test_emptied_review_loses_its_mark(user: User, monkeypatch, tmp_path: Path) -> None:
    """A review emptied of everything and written is removed, so the commit
    list doesn't mark the commit as reviewed; an empty file already there
    doesn't mark it either."""
    from kigit_gui import review

    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    v2 = next(r for r in commit_table(user).rows if r["subject"].startswith("v2"))
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-summary", retries=100)
    user.find(marker="review-summary").type("Worth a look.")
    user.find(marker="review-write").click()
    row = lambda: next(r for r in commit_table(user).rows if r["hash"] == v2["hash"])  # noqa: E731
    for _ in range(30):
        if row()["reviewed"]:
            break
        await asyncio.sleep(0.1)
    assert row()["reviewed"] and v2["hash"] in review.all_reviews(project)

    with user.client:
        marked(user, "review-summary").value = ""  # everything deleted
    user.find(marker="review-write").click()
    await user.should_see("Nothing left in the review")
    assert not row()["reviewed"] and v2["hash"] not in review.all_reviews(project)
    assert v2["hash"] not in (project / "reviews" / "index.md").read_text(encoding="utf-8")

    # An empty review file from before this fix: no mark.
    review.save(project, review.Review(commit=v2["hash"], parent=v2["parent"], subject=v2["subject"]))
    assert v2["hash"] not in review.reviewed_commits(project)


async def test_unwritten_review_is_kept_as_a_draft(user: User, monkeypatch, tmp_path: Path) -> None:
    """Switching to another commit without writing keeps the edits for later."""
    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    rows = commit_table(user).rows
    v2 = next(r for r in rows if r["subject"].startswith("v2"))
    moved = next(r for r in rows if r["subject"] == "move project folder")

    async def review(row: dict) -> None:
        frame = next(e for e in user.client.elements.values() if e.tag == "iframe")  # hidden at first
        before = frame.props.get("src")
        await select(user, [row])
        user.find(marker="review-button").click()
        for _ in range(100):  # until the viewer shows the new page
            if frame.props.get("src") != before:
                break
            await asyncio.sleep(0.1)

    await review(v2)
    user.find(marker="review-summary").type("Half a thought")
    await review(moved)
    await user.should_see("unwritten draft: " + v2["short"])
    assert not (project / "reviews").exists()
    await review(v2)
    await user.should_see("Unsaved changes")
    await user.should_see("Half a thought")  # shown as rendered text
    user.find(marker="review-write").click()
    await user.should_see("Written to reviews/")


def marked(user: User, marker: str):
    """The element with this marker, shown or not (find() skips hidden ones)."""
    return next(e for e in user.client.elements.values() if marker in e._markers)  # noqa: SLF001


def split_of(user: User):
    return marked(user, "dock-grip").parent_slot.parent


def git(repo: Path, *args: str) -> str:
    import subprocess
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


async def test_review_of_an_amended_commit_is_moved(user: User, monkeypatch, tmp_path: Path) -> None:
    """After an amend (or rebase) the review's commit is on no branch; the
    GUI says so and moves it to the commit it became."""
    from kigit_gui import review

    project = make_fixture_repo(tmp_path / "repo")
    old, parent = git(project, "rev-parse", "HEAD"), git(project, "rev-parse", "HEAD~1")
    seen = review.Seen(parent, old, "new")
    path = review.save(project, review.Review(commit=old, parent=parent, subject="move project folder",
                                              notes=[review.Note(title="Why", anchor=review.Anchor(
                                                  "pcb", "net", "GND", seen))]))
    git(project, "commit", "-q", "--amend", "-m", "move the project folder")
    new = git(project, "rev-parse", "HEAD")

    await open_at(user, monkeypatch, str(project))
    await user.should_see("1 review is of commits on no branch any more", retries=50)
    user.find(marker="fix-strays").click()
    await user.should_see("Reviews of rewritten commits")
    user.find(marker="stray-ok").click()
    await user.should_see("Moved 1 review")
    r = review.load(path)
    assert (r.commit, r.parent, r.subject) == (new, parent, "move the project folder")
    assert r.notes[0].anchor.seen == review.Seen(parent, new, "new")
    assert next(x for x in commit_table(user).rows if x["hash"] == new)["reviewed"]
    assert not marked(user, "stray-bar").visible


async def test_reviews_of_squashed_commits_are_brought_in(user: User, monkeypatch, tmp_path: Path) -> None:
    """A squash makes one new commit: its review takes in the old commits'
    reviews (ticked when its message names them), and Write removes their files."""
    from kigit_gui import review

    project = make_fixture_repo(tmp_path / "repo")
    files = []
    for rev, title in (("HEAD", "Moved folder"), ("HEAD~1", "Added C1")):
        files.append(review.save(project, review.Review(
            commit=git(project, "rev-parse", rev), subject=git(project, "log", "-1", "--format=%s", rev),
            notes=[review.Note(title=title)])))
    git(project, "reset", "-q", "--soft", "HEAD~2")
    git(project, "commit", "-q", "-m", "Board rev B\n\n* v2: add C1, move R2, widen a track\n* move project folder")
    head = git(project, "rev-parse", "HEAD")

    await open_at(user, monkeypatch, str(project))
    await user.should_see("2 reviews are of commits on no branch any more", retries=50)
    row = next(x for x in commit_table(user).rows if x["hash"] == head)
    await select(user, [row])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-bring-in", retries=100)
    user.find(marker="review-bring-in").click()
    await user.should_see(marker="bring-in-ok")
    assert all(b.value for b in user.find(marker="bring-in-pick").elements)  # both named in the message
    user.find(marker="bring-in-ok").click()
    await user.should_see("Unsaved changes")
    assert all(f.exists() for f in files)  # nothing changes until Write
    user.find(marker="review-write").click()
    await user.should_see("Written to reviews/")
    assert list(review.all_reviews(project)) == [head]
    r = review.load(review.all_reviews(project)[head])
    assert sorted(n.title for n in r.notes) == ["Added C1", "Moved folder"]
    assert not any(f.exists() for f in files)
    for _ in range(50):
        if not marked(user, "stray-bar").visible:
            break
        await asyncio.sleep(0.1)
    assert not marked(user, "stray-bar").visible


async def test_note_tags_dropdown(user: User, monkeypatch, tmp_path: Path) -> None:
    """A note's tags come from a dropdown of the built-in and the project's
    tags; a typed one is tidied into a single word."""
    from kigit_gui import review

    project = make_fixture_repo(tmp_path / "repo")
    head = git(project, "rev-parse", "HEAD")
    review.save(project, review.Review(commit=head, notes=[review.Note(title="Old", tags=["thermal"])]))
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    v2 = next(r for r in commit_table(user).rows if r["subject"].startswith("v2"))
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-add-note", retries=100)
    user.find(marker="review-add-note").click()
    tags = user.find(marker="review-note-tags").elements.pop()
    assert tags.options[:4] == review.TAGS and "thermal" in tags.options  # used elsewhere in the project
    with user.client:
        tags.value = ["reason", "Needs Review"]  # as if picked, and typed + Enter
    assert tags.value == ["reason", "needs-review"]
    user.find(marker="review-write").click()
    await user.should_see("Written to reviews/")
    r = review.load(review.all_reviews(project)[v2["hash"]])
    assert r.notes[0].tags == ["reason", "needs-review"]


async def test_3d_view_of_a_commit(user: User, monkeypatch) -> None:
    """3D on one commit: kigit --3d makes the model, the viewer shows it,
    and the same commit again comes from the cache."""
    from kigit_gui import kigit

    calls = []

    async def fake_board3d(project: str, rev: str, out: Path) -> list[str]:
        calls.append(rev)
        out.write_bytes(b"glTF")
        return []

    monkeypatch.setattr(kigit, "board3d", fake_board3d)
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    rows = commit_table(user).rows
    button = user.find(marker="view3d-button").elements.pop()
    assert not button.enabled
    await select(user, [rows[1], rows[2]])
    assert button.enabled  # several side by side, too
    await select(user, [rows[1]])
    assert button.enabled
    frame = next(e for e in user.client.elements.values() if e.tag == "iframe")
    for _ in range(2):
        user.find(marker="view3d-button").click()
        for _ in range(50):
            if "/board3d/" in (frame.props.get("src") or ""):
                break
            await asyncio.sleep(0.1)
    assert "/board3d/" in frame.props["src"] and rows[1]["short"] in frame.props["src"]
    assert calls == [rows[1]["hash"]]  # made once


async def test_3d_side_by_side(user: User, monkeypatch) -> None:
    """Up to four commits in 3D side by side, oldest first, made at once;
    Compare still wants exactly two."""
    from kigit_gui import kigit

    calls = []

    async def fake_board3d(project: str, rev: str, out: Path) -> list[str]:
        calls.append(rev)
        out.write_bytes(b"glTF")
        return []

    monkeypatch.setattr(kigit, "board3d", fake_board3d)
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    rows = commit_table(user).rows
    await select(user, rows[1:5])  # four commits, newest first in the list
    assert user.find(marker="view3d-button").elements.pop().enabled
    compare = next(e for e in user.client.elements.values() if isinstance(e, ui.button) and e.text == "Compare")
    assert not compare.enabled
    await select(user, rows[0:5])  # five: the four last picked are kept
    assert len(commit_table(user).selected) == app.MAX_3D
    await select(user, rows[1:4])
    user.find(marker="view3d-button").click()
    frame = next(e for e in user.client.elements.values() if e.tag == "iframe")
    for _ in range(50):
        if "/board3d-grid" in (frame.props.get("src") or ""):
            break
        await asyncio.sleep(0.1)
    src = frame.props["src"]
    assert src.startswith("/board3d-grid?") and src.count("b=") == 3
    assert sorted(calls) == sorted(r["hash"] for r in rows[1:4])
    # Oldest first: the lowest row in the list comes first.
    assert src.index(rows[3]["short"]) < src.index(rows[2]["short"]) < src.index(rows[1]["short"])


async def test_3d_dock_beside_a_comparison(user: User, monkeypatch) -> None:
    """While comparing, the 3D dock shows the new board beside it, or the
    old one, or both (oldest first); it goes when the comparison does."""
    from kigit_gui import kigit

    calls = []

    async def fake_board3d(project: str, rev: str, out: Path) -> list[str]:
        calls.append(rev)
        out.write_bytes(b"glTF")
        return []

    monkeypatch.setattr(kigit, "board3d", fake_board3d)
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    rows = commit_table(user).rows
    old, new = rows[3], rows[1]
    dock_button = marked(user, "dock-button")
    assert not dock_button.visible  # nothing compared yet
    await select(user, [new, old])  # picked newest first: still old .. new
    user.find(marker="compare-button").click()
    await user.should_see(marker="viewer", retries=100)
    for _ in range(100):
        if dock_button.visible:
            break
        await asyncio.sleep(0.1)
    assert dock_button.visible

    dock_frame = marked(user, "dock-viewer")

    async def dock_src(part: str) -> str:
        for _ in range(50):
            if part in (dock_frame.props.get("src") or ""):
                break
            await asyncio.sleep(0.1)
        return dock_frame.props["src"]

    user.find(marker="dock-button").click()
    src = await dock_src("/board3d/")
    assert new["short"] in src and calls == [new["hash"]]
    assert "/diffs/" in user.find(marker="viewer").elements.pop().props["src"]  # the comparison stays
    with user.client:
        marked(user, "dock-side").value = "both"
    src = await dock_src("/board3d-grid")
    assert src.index(old["short"]) < src.index(new["short"])  # oldest first
    assert sorted(calls) == sorted([new["hash"], old["hash"]])  # each made once

    # Below the comparison instead of beside it, and back.
    place = marked(user, "dock-place")
    user.find(marker="dock-place").click()
    assert "below" in marked(user, "dock-grip").parent_slot.parent.classes and place.text == ""
    user.find(marker="dock-place").click()
    assert "below" not in marked(user, "dock-grip").parent_slot.parent.classes

    # Folded to its bar and back: the 3D page stays loaded meanwhile.
    loaded = dock_frame.props["src"]
    assert loaded.endswith("&dock=1")  # the page leaves its own new-tab button out
    user.find(marker="dock-fold").click()
    assert "folded" in split_of(user).classes and dock_frame.props["src"] == loaded
    assert not marked(user, "dock-place").visible
    user.find(marker="dock-fold").click()
    assert "folded" not in split_of(user).classes and marked(user, "dock-place").visible

    # In another tab: the dock shrinks to its bar; the tab gets what the
    # dock would show; closing the tab (kigit_dock_back) brings it back.
    from nicegui.events import GenericEventArguments

    def popout_click(opened: bool) -> None:
        button = marked(user, "dock-popout")
        with user.client:
            for listener in list(button._event_listeners.values()):  # noqa: SLF001
                if listener.type == "click":
                    listener.handler(GenericEventArguments(sender=button, client=user.client, args=opened))

    split = marked(user, "dock-grip").parent_slot.parent
    popout_click(False)  # blocked by the browser: stays docked
    assert "popped" not in split.classes
    popout_click(True)
    assert "popped" in split.classes and marked(user, "dock-bring-back").visible
    assert dock_frame.props["src"] == "about:blank"
    with user.client:
        marked(user, "dock-side").value = "new"  # still works while it's out
    await asyncio.sleep(0.3)
    assert dock_frame.props["src"] == "about:blank"  # the other tab shows it, not the dock
    with user.client:  # the page's emitEvent("kigit_dock_back"); its handler is async
        for listener in list(user.client.layout._event_listeners.values()):  # noqa: SLF001
            if listener.type == "kigit_dock_back":
                await listener.handler(None)
    src = await dock_src("/board3d/")
    assert "popped" not in split.classes and new["short"] in src

    # Showing a commit in 3D on its own: no comparison, no dock.
    await select(user, [new])
    user.find(marker="view3d-button").click()
    for _ in range(50):
        if not dock_button.visible:
            break
        await asyncio.sleep(0.1)
    assert not dock_button.visible and not marked(user, "dock-grip").visible


async def test_3d_build_shows_progress(user: User, monkeypatch, tmp_path: Path) -> None:
    """kicad-cli reports no progress: the GUI shows time against the board's
    last build, and remembers this one."""
    from kigit_gui import buildtime, kigit

    monkeypatch.setattr(buildtime, "FILE", tmp_path / "times.json")
    monkeypatch.setattr(buildtime, "MIN_SECONDS", 0.5)
    release = asyncio.Event()

    async def slow_board3d(project: str, rev: str, out: Path) -> list[str]:
        await release.wait()
        out.write_bytes(b"glTF")
        return []

    monkeypatch.setattr(kigit, "board3d", slow_board3d)
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    await select(user, [commit_table(user).rows[1]])
    user.find(marker="view3d-button").click()
    await user.should_see("so far · the first build of this board", retries=30)
    assert "indeterminate" in marked(user, "build-progress").props  # no estimate yet
    await asyncio.sleep(0.6)
    release.set()
    for _ in range(50):
        if not marked(user, "build-progress").visible:
            break
        await asyncio.sleep(0.1)
    assert not marked(user, "build-progress").visible
    assert (tmp_path / "times.json").exists()  # remembered for next time


async def test_missing_parts_in_notifications(user: User, monkeypatch) -> None:
    """Parts without a 3D model: a red "!" on the bell, and the list in the
    notification centre."""
    from kigit_gui import kigit, notices

    notices.clear()

    async def fake_board3d(project: str, rev: str, out: Path) -> kigit.Made3d:
        out.write_bytes(b"glTF")
        return kigit.Made3d(["2 parts have no 3D model: KiCad couldn't find the file (the log lists them)"],
                            [("U405", "/Users/pico/x.step"), ("J1", "${KIPRJMOD}/3d/usb.wrl")])

    monkeypatch.setattr(kigit, "board3d", fake_board3d)
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    badge = marked(user, "notices-badge")
    assert not badge.visible
    await select(user, [commit_table(user).rows[1]])
    user.find(marker="view3d-button").click()
    for _ in range(50):
        if badge.visible:
            break
        await asyncio.sleep(0.1)
    assert badge.visible  # the red "!"
    assert notices.items[0].rows == [("U405", "/Users/pico/x.step"), ("J1", "${KIPRJMOD}/3d/usb.wrl")]
    user.find(marker="notices-button").click()
    await user.should_see("2 parts without a 3D model")
    table = user.find(marker="notice-table").elements.pop()
    assert "U405" in table.content and "/Users/pico/x.step" in table.content
    for _ in range(30):
        if not badge.visible:
            break
        await asyncio.sleep(0.1)
    assert not badge.visible  # read


async def test_3d_view_without_kicad(user: User, monkeypatch) -> None:
    from kigit_gui import kigit

    async def no_kicad(project: str, rev: str, out: Path) -> list[str]:
        raise kigit.KigitError("the 3D view needs KiCad's kicad-cli (KiCad 8 or newer), which wasn't found.")

    monkeypatch.setattr(kigit, "board3d", no_kicad)
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    await select(user, [commit_table(user).rows[1]])
    user.find(marker="view3d-button").click()
    await user.should_see("Couldn't make the 3D board.")
    await user.should_see("which wasn't found")
    assert user.find(marker="view3d-button").elements.pop().enabled  # can try again


async def test_discussion_from_request_to_accepted(user: User, monkeypatch, tmp_path: Path) -> None:
    """PR-style review: ask for attention on something in a commit's review;
    it shows in the header and the commit list, people reply, mark it done,
    and it's accepted. Everything goes to reviews/threads/ as it's sent."""
    from kigit_gui import threads

    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    badge = marked(user, "discussions-badge")
    assert not badge.visible
    v2 = next(r for r in commit_table(user).rows if r["subject"].startswith("v2"))
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-request", retries=100)
    emit(user, "kigit_pinned", {"tab": "pcb", "kind": "footprint", "name": "C1"})
    user.find(marker="review-request").click()
    await user.should_see("About Footprint C1")
    user.find(marker="request-title").type("C1 too close to U1")
    user.find(marker="request-body").type("Move it 1 mm.")
    user.find(marker="request-go").click()
    await user.should_see("Asked for attention: C1 too close to U1")

    t = threads.all_threads(project)[0]
    assert (t.title, t.status, t.commit, t.by, t.anchor.name) == ("C1 too close to U1", "open", v2["hash"], "kigit tests", "C1")
    assert badge.visible and badge.text == "1"
    assert next(r for r in commit_table(user).rows if r["hash"] == v2["hash"])["thread"] == "open"
    await user.should_see(marker="review-discussion")  # in this commit's review too

    # Reviewing another commit (where the fix would go): still listed there.
    moved = next(r for r in commit_table(user).rows if r["subject"] == "move project folder")
    await select(user, [moved])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-discussions-carried", retries=100)
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-discussions-here", retries=100)

    # The list, then the chat: a reply, done, accepted.
    user.find(marker="discussions-button").click()
    await user.should_see(marker="discussion-row")
    user.find(marker="discussion-row").click()
    await user.should_see(marker="discussion-title")
    user.find(marker="discussion-reply").type("Moved it.")
    user.find(marker="discussion-done").click()
    await user.should_see(marker="discussion-accept")
    assert threads.all_threads(project)[0].status == "done"
    user.find(marker="discussion-accept").click()
    await user.should_see(marker="status-accepted")
    t = threads.all_threads(project)[0]
    assert t.status == "accepted" and [m.kind for m in t.messages] == ["comment", "done", "accepted"]
    assert t.messages[1].text == "Moved it." and t.messages[1].head == git(project, "rev-parse", "HEAD")
    for _ in range(30):
        if not badge.visible:
            break
        await asyncio.sleep(0.1)
    assert not badge.visible  # nothing active


async def test_discussion_commit_links_compare_and_show(user: User, monkeypatch, tmp_path: Path) -> None:
    """A discussion's commit hashes are links: one compares the commit it was
    opened on with that commit and shows its anchor; the opening commit's
    own link compares it with HEAD (where it stands now)."""
    from kigit_gui import kigit

    hardware = await kigit.example(tmp_path / "ex")
    await open_at(user, monkeypatch, str(hardware))
    await user.should_see("Pick two commits on the left", retries=100)
    rows = {r["subject"].split(":")[0].split(",")[0]: r for r in commit_table(user).rows}
    opened_on = rows["Rework the power"]["hash"]
    done_at = rows["Rename VIN to VBUS"]["hash"]
    head = commit_table(user).rows[1]["hash"]
    asked = []
    monkeypatch.setattr(ui, "run_javascript", lambda code, **kw: asked.append(code))

    user.find(marker="discussions-button").click()
    await user.should_see(marker="discussion-row")
    user.find(marker="discussion-7e3a90c4").click()  # TP1's, in the example
    await user.should_see("TP1 is in the way of the rail")
    links = [e for e in user.client.elements.values() if "discussion-commit" in e._markers]  # noqa: SLF001
    # The header's (opened on), then one per message: Author B's (opened on), Author A's (done at).
    assert [e.text for e in links] == [opened_on[:7], opened_on[:7], done_at[:7]]

    # Done at d627454: compared with where it was opened, TP1 shown (gone by then: removed).
    user.find(marker="discussion-commit", content=done_at[:7]).click()
    viewer = marked(user, "viewer")
    for _ in range(100):
        if "/diffs/" in (viewer.props.get("src") or ""):
            break
        await asyncio.sleep(0.1)
    await user.should_see(f"{opened_on[:7]} ↔ {done_at[:7]}", retries=50)
    assert any('"name": "TP1"' in c and "postMessage" in c for c in asked)  # shown once it's loaded

    # The opening commit's own link: where it stands now, at HEAD.
    asked.clear()
    user.find(marker="discussions-button").click()
    user.find(marker="discussion-7e3a90c4").click()
    await user.should_see("TP1 is in the way of the rail")
    links = [e for e in user.client.elements.values() if "discussion-commit" in e._markers]  # noqa: SLF001
    with user.client:  # links[0], the header's (two links have that text)
        from nicegui.events import GenericEventArguments, handle_event
        for listener in list(links[0]._event_listeners.values()):  # noqa: SLF001
            handle_event(listener.handler, GenericEventArguments(sender=links[0], client=user.client, args=None))
    await user.should_see(f"{opened_on[:7]} ↔ {head[:7]}", retries=50)
    assert any('"name": "TP1"' in c for c in asked)


async def test_discussion_stays_open_and_messages_can_be_edited(user: User, monkeypatch, tmp_path: Path) -> None:
    """Opened from the review panel, the chat stays open after Send (the panel
    redraws its list then); your own messages can be edited, others' can't."""
    from kigit_gui import threads

    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    v2 = next(r for r in commit_table(user).rows if r["subject"].startswith("v2"))
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-request", retries=100)
    user.find(marker="review-request").click()
    await user.should_see(marker="request-title")
    user.find(marker="request-title").type("C1 placement")
    user.find(marker="request-body").type("Too clsoe to U1.")
    user.find(marker="request-go").click()
    await user.should_see(marker="review-discussion")
    t = threads.all_threads(project)[0]
    threads.add(project, t.id, "Someone else", "", "Why?")  # a colleague's reply, pulled

    user.find(marker="review-discussion").click()  # from the review panel
    await user.should_see(marker="discussion-title")
    user.find(marker="discussion-reply").type("Moving it.")
    user.find(marker="discussion-send").click()
    await user.should_see("Moving it.")
    dialog = marked(user, "discussion-title")
    while not isinstance(dialog, ui.dialog):
        dialog = dialog.parent_slot.parent
    assert dialog.value and not dialog.is_deleted  # still open
    assert marked(user, "discussion-reply").value == ""  # sent, so emptied

    # Edit: a pencil on your own messages only (two of three here).
    assert len([e for e in user.client.elements.values() if "discussion-edit" in e._markers]) == 2  # noqa: SLF001
    first = next(e for e in user.client.elements.values() if "discussion-edit" in e._markers)  # noqa: SLF001
    from nicegui.events import GenericEventArguments, handle_event
    with user.client:
        for listener in list(first._event_listeners.values()):  # noqa: SLF001
            handle_event(listener.handler, GenericEventArguments(sender=first, client=user.client, args=None))
    await user.should_see(marker="discussion-edit-box")
    box = marked(user, "discussion-edit-box")
    assert box.value == "Too clsoe to U1."
    with user.client:
        box.value = "Too close to U1."
    user.find(marker="discussion-edit-save").click()
    await user.should_see(marker="discussion-edited")
    m = threads.all_threads(project)[0].messages
    assert m[0].text == "Too close to U1." and m[0].edited and m[1].text == "Why?" and not m[1].edited
    assert dialog.value  # still open


async def test_discussion_links_and_deleting(user: User, monkeypatch, tmp_path: Path) -> None:
    """Copy a discussion's link; clicking one opens it; a link to one that's
    gone warns (pop-up, log, bell), also when a review with it is opened.
    Your own comments can be deleted."""
    from kigit_gui import notices, threads

    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    t = threads.start(project, "C1 placement", "Too close.", "a" * 40, "kigit tests", "a" * 40)
    gone = threads.start(project, "Old point", "x", "a" * 40, "kigit tests", "a" * 40)
    copied = []
    monkeypatch.setattr(ui.clipboard, "write", lambda text: copied.append(text))

    emit(user, "kigit_open_thread", t.id)  # a link clicked in a note or message
    await user.should_see(marker="discussion-title")
    user.find(marker="discussion-copy-link").click()
    assert copied == [f"[C1 placement](threads/{t.id}.md)"]
    await user.should_see("Link copied")

    threads.path_of(project, gone).unlink()  # deleted (or not pulled)
    before = len(notices.items)
    emit(user, "kigit_open_thread", gone.id)
    await user.should_see(f"That discussion ({gone.id}) is gone")
    assert notices.items[0].level == "warning" and gone.id in notices.items[0].title and len(notices.items) == before + 1

    # A review that links to it: warned once when it's opened.
    v2 = next(r for r in commit_table(user).rows if r["subject"].startswith("v2"))
    from kigit_gui import review as review_mod
    review_mod.save(project, review_mod.Review(commit=v2["hash"], parent=v2["parent"], subject=v2["subject"],
                                               summary=f"See {copied[0]} and [old](threads/{gone.id}.md)."))
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(f"links to a discussion that's gone ({gone.id})", retries=100)
    review_warnings = lambda: [n for n in notices.items if "links to a discussion that's gone" in n.title  # noqa: E731
                               and gone.id in n.title]
    assert len(review_warnings()) == 1 and t.id not in review_warnings()[0].title  # only the one that's gone
    user.find(marker="review-button").click()  # opened again: not warned again
    await asyncio.sleep(0.5)
    assert len(review_warnings()) == 1

    # Delete your own comment, after a confirmation.
    emit(user, "kigit_open_thread", t.id)
    await user.should_see(marker="discussion-delete")
    user.find(marker="discussion-delete").click()
    await user.should_see(marker="discussion-delete-confirm")
    user.find(marker="discussion-delete-confirm").click()
    for _ in range(30):
        if not threads.all_threads(project)[0].messages:
            break
        await asyncio.sleep(0.1)
    assert next(x for x in threads.all_threads(project) if x.id == t.id).messages == []


async def test_copy_review_links_from_the_commit_list(user: User, monkeypatch, tmp_path: Path) -> None:
    """Right-click a commit: copy its review's link or file path, or its
    hash. A review link opens that review; one that's gone warns. Discussion
    rows in the review panel have their own copy button."""
    from kigit_gui import notices, review as review_mod, threads

    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    copied = []
    monkeypatch.setattr(ui.clipboard, "write", lambda text: copied.append(text))
    rows = commit_table(user).rows
    v2 = next(r for r in rows if r["subject"].startswith("v2"))
    other = next(r for r in rows if r["subject"] == "docs only")
    path = review_mod.save(project, review_mod.Review(commit=v2["hash"], parent=v2["parent"], subject=v2["subject"],
                                                      summary="x"))
    user.find(marker="open-button").click()  # reload: v2 is now reviewed
    for _ in range(100):
        v2 = next((r for r in commit_table(user).rows if r["hash"] == v2["hash"]), v2)
        if v2["reviewed"]:
            break
        await asyncio.sleep(0.1)
    assert v2["reviewed"]

    table = commit_table(user)

    def right_click(row: dict) -> None:
        from nicegui.events import GenericEventArguments, handle_event
        with user.client:
            for listener in list(table._event_listeners.values()):  # noqa: SLF001
                if listener.type == "rowContextmenu":
                    handle_event(listener.handler, GenericEventArguments(sender=table, client=user.client,
                                                                         args=[{}, row, 0]))

    right_click(other)  # no review: only the hash
    assert not marked(user, "menu-review-link").enabled and marked(user, "menu-hash").enabled
    right_click(v2)
    assert marked(user, "menu-review-link").enabled and marked(user, "menu-review-path").enabled
    for item in ("menu-review-link", "menu-review-path", "menu-hash"):
        user.find(marker=item).click()
    assert copied == [f"[{v2['subject']}]({path.name})", str(path), v2["hash"]]

    emit(user, "kigit_open_review", path.stem)  # the link, clicked in a note
    await user.should_see(f"ID {path.stem}", retries=100)
    assert marked(user, "review-panel").value and marked(user, "review-id").text == f"ID {path.stem}"
    emit(user, "kigit_open_review", "deadbeef")
    await user.should_see("That review (deadbeef) is gone")
    assert "deadbeef" in notices.items[0].title

    t = threads.start(project, "C1 placement", "x", v2["hash"], "kigit tests", v2["hash"])
    user.find(marker="review-button").click()  # the panel lists it now
    await user.should_see(marker="review-discussion-link", retries=100)
    user.find(marker="review-discussion-link").click()
    assert copied[-1] == f"[C1 placement](threads/{t.id}.md)"
    assert not [e for e in user.client.elements.values() if "discussion-title" in e._markers]  # not opened  # noqa: SLF001


async def test_pulled_discussions_show_up(user: User, monkeypatch, tmp_path: Path) -> None:
    """A discussion that arrives on disk (a git pull) is picked up by itself."""
    from kigit_gui import threads

    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    head = git(project, "rev-parse", "HEAD")
    threads.start(project, "From a colleague", "Please check the GND pour.", head, "Author B", head)
    badge = marked(user, "discussions-badge")
    for _ in range(80):  # checked every 4 s
        if badge.visible:
            break
        await asyncio.sleep(0.1)
    assert badge.visible and badge.text == "1"


async def test_first_commit_has_nothing_to_review_against(user: User, monkeypatch) -> None:
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    first = next(r for r in commit_table(user).rows if r["subject"] == "v1: first board")
    await select(user, [first])
    user.find(marker="review-button").click()
    await user.should_see("This is the first commit")


async def test_panels_are_resizable(user: User, monkeypatch) -> None:
    """Both side panels have a drag handle; a drag's end sets the drawer's width."""
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    for key in ("commits", "review"):
        grip = user.find(marker=f"grip-{key}").elements.pop()
        drawer = user.client.elements[int(grip.props["data-drawer"])]
        assert drawer.props["width"] == 480
        emit(user, "kigit_panel_width", {"id": drawer.id, "width": 700})
        assert drawer.props["width"] == 700
        emit(user, "kigit_panel_width", {"id": drawer.id, "width": "wide"})  # ignored
        assert drawer.props["width"] == 700


async def test_panels_hide_to_a_rail(user: User, monkeypatch, tmp_path: Path) -> None:
    """The commit list and the review panel hide to a rail on their edge (a
    mini drawer), come back from it, remember it, and open in a new tab."""
    project = make_fixture_repo(tmp_path / "repo")
    await open_at(user, monkeypatch, str(project))
    await user.should_see("Pick two commits on the left", retries=50)
    opened = []
    monkeypatch.setattr(ui.navigate, "to", lambda url, new_tab=False: opened.append((url, new_tab)))
    commits = marked(user, "grip-commits").parent_slot.parent
    assert not commits.props.get("mini")
    user.find(marker="commits-hide").click()
    assert commits.props.get("mini") is True
    assert "q-mini-drawer-only" in marked(user, "commits-rail").classes  # what shows while hidden
    assert "q-mini-drawer-hide" in marked(user, "commits-hide").parent_slot.parent.parent_slot.parent.classes
    user.find(marker="commits-rail").click()
    assert not commits.props.get("mini")
    emit(user, "kigit_panel_hidden", {"key": "commits", "hidden": True})  # remembered from last time
    assert commits.props.get("mini") is True
    emit(user, "kigit_panel_hidden", {"key": "nope", "hidden": True})  # ignored
    user.find(marker="commits-rail").click()

    # The commit list's new tab: this project in another kigit tab.
    user.find(marker="commits-newtab").click()
    assert opened and opened[-1][1] is True and opened[-1][0].startswith("/?folder=")
    import urllib.parse
    q = urllib.parse.parse_qs(opened[-1][0][2:])
    assert Path(q["folder"][0]) == project and q["board"][0].endswith(".kicad_pcb")

    # The review panel: hide, rail, and back when a review is asked for again.
    rows = commit_table(user).rows
    v2 = next(r for r in rows if r["subject"].startswith("v2"))
    await select(user, [v2])
    user.find(marker="review-button").click()
    await user.should_see(marker="review-hide", retries=100)
    drawer = marked(user, "review-panel")
    user.find(marker="review-hide").click()
    assert drawer.props.get("mini") is True and drawer.value
    marked(user, "review-rail")  # exists, shown by Quasar while mini
    user.find(marker="review-rail").click()
    assert not drawer.props.get("mini")

    # Not written yet: no page to open; written: the Reviews page at it.
    user.find(marker="review-newtab").click()
    await user.should_see("isn't written yet")
    user.find(marker="review-summary").type("Looks fine.")
    user.find(marker="review-write").click()
    await user.should_see("Written", retries=50)
    user.find(marker="review-newtab").click()
    url = opened[-1][0]
    assert url.startswith("/reviews-doc/") and "/reviews/" in url  # the review's own page

    user.find(marker="review-hide").click()
    user.find(marker="review-button").click()  # asking for it shows it again
    for _ in range(50):
        if not drawer.props.get("mini"):
            break
        await asyncio.sleep(0.1)
    assert not drawer.props.get("mini")


async def test_reviews_page_button(user: User, monkeypatch) -> None:
    """The Reviews button opens the project's reviews page in a new tab."""
    from kigit_gui import review_doc

    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    # Catch the new tab instead of following it (the test app has no page routes).
    opened = []
    monkeypatch.setattr(ui.navigate, "to", lambda url, new_tab=False: opened.append((url, new_tab)))
    user.find(marker="reviews-doc").click()
    for _ in range(20):
        if opened:
            break
        await asyncio.sleep(0.05)
    assert len(opened) == 1 and opened[0][1] is True
    url = opened[0][0]
    assert url.startswith("/reviews-doc/")
    page = await review_doc._doc(url.rsplit("/", 1)[1])  # noqa: SLF001
    assert page.status_code == 200 and b"Home</a>" in page.body and b">Reviews</a>" in page.body  # the home page


async def test_wrap_messages(user: User, monkeypatch) -> None:
    """The switch wraps long commit messages instead of cutting them off."""
    await open_at(user, monkeypatch, PROJECT)
    await user.should_see("Pick two commits on the left", retries=50)
    table = commit_table(user)
    assert "kigit-wrap" not in table.classes
    user.find(marker="wrap-messages").click()
    assert "kigit-wrap" in table.classes
    assert [c["name"] for c in table.columns] == ["short", "tags", "subject"]  # date moved under the hash
    user.find(marker="wrap-messages").click()
    assert "kigit-wrap" not in table.classes
    assert [c["name"] for c in table.columns] == ["short", "tags", "date", "subject"]
