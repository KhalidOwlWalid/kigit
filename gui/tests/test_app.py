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
        return (app.CACHE / src.split("/diffs/")[1].split("?")[0]).read_text()

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
        return (app.CACHE / src.split("/diffs/")[1].split("?")[0]).read_text()

    assert '"src":[' not in await compare()
    box.value = True
    page = await compare()
    assert '"src":[{' in page
    assert "demo.kicad_pcb" in page


def emit(user: User, event: str, args) -> None:
    """Sends a page event (emitEvent in the browser), e.g. what the viewer
    reports as pinned."""
    from nicegui.events import GenericEventArguments

    with user.client:
        for listener in list(user.client.layout._event_listeners.values()):  # noqa: SLF001
            if listener.type == event:
                listener.handler(GenericEventArguments(sender=user.client.layout, client=user.client, args=args))


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
    page = (app.CACHE / src.split("/diffs/")[1].split("?")[0]).read_text()
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
    assert f"[{r.id}]({r.id}.md)" in (project / "reviews" / "index.md").read_text()

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
    assert page.status_code == 200 and b"reviews</title>" in page.body


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
