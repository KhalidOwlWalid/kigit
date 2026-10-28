"""kigit GUI: open a KiCad project, pick two commits, see what changed.

Started by `kigit gui [PROJECT_DIR]`. All the work is done by the kigit
command line (see kigit.py); this file is only the window around it.

Flow:
  1. Browse/Open a folder. kigit looks for a KiCad project in it and up to
     two levels below, and says so if there's none, or no git history.
  2. The project's commits are listed (newest first, with the working tree
     on top). Nothing is rendered yet.
  3. Pick two commits and press Compare: kigit diffs them and the viewer
     opens on the schematic.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from nicegui import app, ui

from . import kigit, logs
from .folder_picker import FolderPicker

LOCAL = "LOCAL"
SEARCH_DEPTH = 2

# Generated pages are served from here. Commit-to-commit diffs never change,
# so they're kept for the session; anything involving LOCAL is regenerated.
CACHE = Path(tempfile.mkdtemp(prefix="kigit-gui-"))
app.add_static_files("/diffs", str(CACHE))

# Message column: one line, the whole message on hover.
MESSAGE_CELL = r"""
<q-td :props="props">
  <div class="ellipsis" style="max-width: 10.5rem">{{ props.row.subject }}</div>
  <q-tooltip anchor="center right" self="center left" max-width="34rem"
             class="bg-grey-10 text-body2" style="white-space: pre-wrap">{{ props.row.tip }}</q-tooltip>
</q-td>
"""

# Commit column: the working tree row stands out.
COMMIT_CELL = r"""
<q-td :props="props">
  <span :class="props.row.hash === 'LOCAL' ? 'text-amber-5 text-weight-bold' : 'text-mono'">{{ props.row.short }}</span>
</q-td>
"""

TAGS_CELL = r"""
<q-td :props="props">
  <q-badge v-if="props.row.pcb" outline color="blue-4" label="PCB" class="q-mr-xs" />
  <q-badge v-if="props.row.sch" outline color="green-4" label="SCH" />
</q-td>
"""


def date_input(label: str) -> ui.input:
    """A YYYY-MM-DD text box with a calendar popup."""
    with ui.input(placeholder=label).props("dense dark outlined clearable").classes("w-36") as box:
        with ui.menu().props("no-parent-event") as menu:
            with ui.date(mask="YYYY-MM-DD").bind_value(box).props("dark"):
                with ui.row().classes("justify-end"):
                    ui.button("Close", on_click=menu.close).props("flat dense")
        with box.add_slot("append"):
            ui.icon("event").on("click", menu.open).classes("cursor-pointer text-gray-400")
    return box


def page_name(project: str, old: str, new: str) -> str:
    key = hashlib.sha1(f"{project}|{old}|{new}".encode()).hexdigest()[:12]
    return f"{key}.html"


def short_rev(rev: str) -> str:
    return rev[:7] if len(rev) == 40 else rev


def notify(message: str, type: str = "info", **kwargs) -> None:
    """Shows a message to the user and writes it to the session log.
    Problems are logged as warnings (they're the user's situation, e.g. no
    git history, not faults in the GUI)."""
    level = logging.WARNING if type in ("negative", "warning") else logging.INFO
    logs.log.log(level, "shown to user: %s", message)
    ui.notify(message, type=type, **kwargs)


def open_folder_in_os(folder: Path) -> None:
    """Opens a folder in the system file manager."""
    if sys.platform == "win32":
        os.startfile(folder)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_log() -> None:
    """A dialog with this session's log: where it is, and its latest lines."""
    with ui.dialog() as dialog, ui.card().classes("w-[60rem] max-w-full bg-[#161a20] gap-2"):
        ui.label("Session log").classes("text-base font-semibold")
        if not logs.session_file:
            ui.label("Logging to a file is off for this session (started with --no-log).").classes("text-gray-400")
        else:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.label(str(logs.session_file)).classes("text-xs text-gray-400 truncate flex-grow")
                ui.button("Open folder", icon="folder",
                          on_click=lambda: open_folder_in_os(logs.session_file.parent)).props("flat dense")
            view = ui.log(max_lines=1000).classes("w-full h-[28rem] text-xs bg-[#0f1115]")

            def refresh() -> None:
                view.clear()
                for line in logs.tail(500):
                    view.push(line)

            refresh()
        with ui.row().classes("w-full justify-end gap-2"):
            if logs.session_file:
                ui.button("Refresh", icon="refresh", on_click=refresh).props("flat")
            ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()


def build(start_folder: str):
    """Builds the page. Returns the coroutine that opens a folder, so the
    caller can open the starting folder once the page exists."""
    ui.dark_mode(True)
    ui.query(".nicegui-content").classes("p-0 gap-0")
    state: dict = {"board": None, "history": None}

    # ---------------------------------------------------------------- header
    with ui.header().classes("items-center gap-3 py-2 px-4 bg-[#161a20] border-b border-[#29303a] no-wrap"):
        ui.label("kigit").classes("text-lg font-bold text-[#e8b84d]")
        folder_input = ui.input(value=start_folder, placeholder="KiCad project folder").props(
            "dense dark outlined").classes("w-[30rem]")
        folder_input.on("keydown.enter", lambda: open_folder(folder_input.value))
        ui.button("Browse", icon="folder_open", on_click=lambda: browse()).props("flat dense")
        ui.button("Open", on_click=lambda: open_folder(folder_input.value)).props("flat dense")
        status = ui.label("").classes("text-sm text-gray-400 ml-auto truncate")
        ui.button("Compare folders", icon="difference", on_click=lambda: compare_folders()).props(
            "flat dense").tooltip("Compare two copies of a KiCad project, without git").mark("compare-folders")
        ui.button(icon="receipt_long", on_click=show_log).props("flat dense round").tooltip("Session log").mark("log-button")

    # ----------------------------------------------------------- commit list
    with ui.left_drawer(value=True, bordered=True).props("width=480").classes("bg-[#161a20] p-0"):
        with ui.column().classes("w-full p-3 gap-2"):
            project_label = ui.label("").classes("text-sm font-semibold")
            hint = ui.label("Pick two commits, then press Compare.").classes("text-xs text-gray-400")
            with ui.row().classes("w-full gap-2 items-center no-wrap"):
                compare_btn = ui.button("Compare", on_click=lambda: compare()).props("unelevated dense color=amber-8")
                picked = ui.label("").classes("text-xs text-gray-300 truncate")
            # Off by default: silkscreen makes comparisons slower and pages bigger.
            silk = ui.checkbox("Include silkscreen", value=False).props("dense dark").classes("text-xs").tooltip(
                "Also compare and draw the silkscreen (labels, outlines, logos). Applies to every comparison."
            ).mark("include-silkscreen")
            # For when the list doesn't show the commit you're after: type any
            # two revisions git understands.
            with ui.expansion("Diff commits manually", icon="edit", value=False).props(
                    "dense dense-toggle header-class=text-xs").classes("w-full bg-[#1c2128] rounded"):
                with ui.column().classes("w-full gap-2 p-2"):
                    ui.label("Any two revisions: a commit hash (short or full), HEAD~3, a branch, a tag, "
                             "or LOCAL for the working tree.").classes("text-xs text-gray-400")
                    with ui.row().classes("w-full gap-2 items-center no-wrap"):
                        old_rev = ui.input("Old", placeholder="e.g. a1b2c3d").props(
                            "dense dark outlined clearable").classes("flex-grow")
                        new_rev = ui.input("New", placeholder="e.g. HEAD").props(
                            "dense dark outlined clearable").classes("flex-grow")
                    with ui.row().classes("w-full justify-end"):
                        manual_btn = ui.button("Find manually", icon="compare_arrows",
                                               on_click=lambda: compare_manually()).props(
                            "unelevated dense color=blue-grey-8")
                    new_rev.on("keydown.enter", lambda: compare_manually())
            # Which commits to list. Find re-asks kigit, so "board/schematic only"
            # searches the whole history, not just the commits already shown.
            with ui.expansion("Filter commits", icon="filter_list", value=True).props(
                    "dense dense-toggle header-class=text-xs").classes("w-full bg-[#1c2128] rounded"):
                with ui.column().classes("w-full gap-2 p-2"):
                    with ui.row().classes("w-full gap-2 items-center no-wrap"):
                        limit = ui.select({100: "Last 100", 200: "Last 200", 500: "Last 500", 1000: "Last 1000",
                                           0: "All commits"}, value=200).props("dense dark outlined").classes(
                            "w-36")
                        since = date_input("Since")
                        until = date_input("Until")
                    with ui.row().classes("w-full gap-2 items-center no-wrap"):
                        only = ui.checkbox("Only commits that changed the board or schematic").props(
                            "dense dark").classes("text-xs")
                        ui.space()
                        ui.button("Find", icon="search", on_click=lambda: find()).props(
                            "unelevated dense color=blue-grey-8")
            count = ui.label("").classes("text-xs text-gray-400")
            columns = [
                {"name": "short", "label": "Commit", "field": "short", "align": "left"},
                {"name": "tags", "label": "", "field": "tags", "align": "left"},
                {"name": "date", "label": "Date", "field": "date", "align": "left"},
                {"name": "subject", "label": "Message", "field": "subject", "align": "left"},
            ]
            table = ui.table(columns=columns, rows=[], row_key="hash", selection="multiple",
                             on_select=lambda e: on_select()).props(
                "dense flat dark virtual-scroll hide-bottom :rows-per-page-options=[0]").classes(
                "w-full h-[calc(100vh-250px)]")
            table.add_slot("body-cell-subject", MESSAGE_CELL)
            table.add_slot("body-cell-short", COMMIT_CELL)
            table.add_slot("body-cell-tags", TAGS_CELL)

    # ---------------------------------------------------------------- viewer
    with ui.element("div").classes("w-full h-[calc(100vh-52px)] relative"):
        frame = ui.element("iframe").classes("w-full h-full border-0 bg-[#0f1115]").mark("viewer")
        frame.set_visibility(False)
        with ui.column().classes("absolute inset-0 items-center justify-center gap-2") as placeholder:
            placeholder_icon = ui.icon("folder_open").classes("text-5xl text-gray-600")
            placeholder_text = ui.label("Open a KiCad project folder to start.").classes("text-gray-400")
            placeholder_more = ui.label("").classes("text-xs text-gray-500 text-center max-w-[36rem]")
            # Shown when a project has no git history: compare two copies instead.
            no_git_button = ui.button("Compare two copies of this project", icon="difference").props(
                "unelevated dense color=amber-8").mark("no-git-compare")
            no_git_button.set_visibility(False)

    def show_message(icon: str, text: str, more: str = "", tone: str = "text-gray-400") -> None:
        no_git_button.set_visibility(False)
        frame.set_visibility(False)
        placeholder.set_visibility(True)
        placeholder_icon.name = icon
        placeholder_text.text = text
        placeholder_text.classes(replace=tone)
        placeholder_more.text = more

    # ------------------------------------------------------------- open/load
    async def browse() -> None:
        chosen = await FolderPicker(folder_input.value or str(Path.home()))
        if chosen:
            folder_input.value = chosen
            await open_folder(chosen)

    def clear_project() -> None:
        state["board"] = state["history"] = None
        table.rows = []
        table.selected = []
        table.update()
        project_label.text = ""
        count.text = ""
        on_select()

    async def open_folder(folder: str) -> None:
        folder = str(Path(folder or ".").expanduser())
        clear_project()
        if not Path(folder).is_dir():
            status.text = ""
            show_message("error_outline", f"{folder} isn't a folder.", tone="text-red-400")
            notify(f"{folder} isn't a folder", type="negative")
            return
        logs.log.info("open folder %s", folder)
        status.text = "Looking for a KiCad project..."
        try:
            found = await kigit.projects(folder, SEARCH_DEPTH)
        except kigit.KigitError as e:
            status.text = ""
            show_message("error_outline", "Couldn't search this folder.", str(e), "text-red-400")
            return

        boards = [p for p in found if p.pcb]
        if not found:
            status.text = ""
            show_message("search_off", "No KiCad project found.",
                         f"Looked in {folder} and {SEARCH_DEPTH} levels below it for a .kicad_pro or .kicad_pcb.",
                         "text-red-400")
            notify("No KiCad project found in this folder (searched 2 levels deep)", type="negative")
            return
        if not boards:
            names = ", ".join(p.name for p in found)
            status.text = ""
            show_message("developer_board_off", "Found a KiCad project, but no board file.",
                         f"{names}: kigit compares projects through their .kicad_pcb, which isn't there.",
                         "text-red-400")
            notify("KiCad project has no .kicad_pcb", type="negative")
            return

        logs.log.info("found %d KiCad project(s): %s", len(found), ", ".join(f"{p.name} ({p.dir})" for p in found))
        project = boards[0] if len(boards) == 1 else await choose_project(folder, boards)
        if project is not None:
            logs.log.info("opening project %s (%s)", project.name, "in git" if project.git else "not in git")
        if project is None:
            status.text = ""
            show_message("folder_open", "Several projects here; none chosen.")
            return
        if not project.git:
            status.text = ""
            show_message("history_toggle_off", f"{project.name} isn't in a git repository.",
                         "There's no history to pick commits from, but you can compare it with another "
                         "copy of the project (an older backup, a colleague's version, ...).",
                         "text-red-400")
            no_git_button.on_click(lambda: compare_folders(new=project.dir))
            no_git_button.set_visibility(True)
            notify(f"{project.name} isn't in a git repository", type="negative")
            return
        await load_history(project)

    async def choose_project(folder: str, boards: list[kigit.Project]):
        with ui.dialog() as dialog, ui.card().classes("w-[36rem] bg-[#161a20] gap-1"):
            ui.label(f"{len(boards)} KiCad projects found").classes("text-base font-semibold")
            ui.label("Pick the one to open:").classes("text-xs text-gray-400 mb-2")
            for p in boards:
                rel = os.path.relpath(p.dir, folder)
                with ui.row().classes(
                        "w-full items-center gap-2 px-2 py-1 rounded cursor-pointer hover:bg-[#1c2128] no-wrap").on(
                        "click", lambda p=p: dialog.submit(p)):
                    ui.icon("developer_board").classes("text-amber-500")
                    with ui.column().classes("gap-0 flex-grow min-w-0"):
                        ui.label(p.name).classes("font-medium")
                        ui.label("." if rel == "." else rel).classes("text-xs text-gray-400 truncate")
                    if not p.git:
                        ui.badge("no git", color="red-5").props("outline")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
        return await dialog

    def filtered() -> bool:
        return bool(only.value or since.value or until.value)

    async def query(board: str) -> kigit.History | None:
        try:
            return await kigit.history(board, max_count=limit.value or 0, since=since.value or "",
                                       until=until.value or "", kicad_only=only.value)
        except kigit.KigitError as e:
            notify(str(e), type="negative", multi_line=True, close_button=True)
            return None

    def show_count(h: kigit.History) -> None:
        what = "commits changed the board or schematic" if only.value else "commits"
        when = ""
        if since.value or until.value:
            when = f" between {since.value or 'the start'} and {until.value or 'now'}"
        shown = len(h.commits)
        count.text = (f"{h.total} {what}{when}" if shown == h.total
                      else f"Showing the latest {shown} of {h.total} {what}{when}")
        here = os.path.dirname(h.board) or "."
        moved = [f for f in h.folders if f != here]
        if moved:
            count.text += f" · project was also in: {', '.join(moved)}"

    async def load_history(project: kigit.Project) -> None:
        status.text = f"Reading {project.name} history..."
        h = await query(project.board)
        if h is None:
            status.text = ""
            show_message("error_outline", "Couldn't read the history.", tone="text-red-400")
            return
        logs.log.info("loaded %s: %d of %d commits listed", project.board, len(h.commits), h.total)
        state["board"], state["history"], state["name"] = project.board, h, project.name
        folder_input.value = project.dir
        project_label.text = project.name
        status.text = h.repo
        show_count(h)
        fill()
        show_message("compare_arrows", "Pick two commits on the left, then press Compare.",
                     "The newest entry is your working tree: HEAD plus any uncommitted changes.")

    async def find() -> None:
        if not state["board"]:
            notify("Open a project first", type="warning")
            return
        status.text = "Searching history..."
        h = await query(state["board"])
        status.text = state["history"].repo if state["history"] else ""
        if h is None:
            return
        state["history"] = h
        show_count(h)
        fill()

    # ------------------------------------------------------------ commit rows
    def fill() -> None:
        h = state["history"]
        if not h:
            table.rows = []
            table.update()
            return
        rows = []
        local = h.local
        head = h.commits[0] if h.commits else None
        if local.dirty:
            subject = f"HEAD + uncommitted changes ({len(local.files)} file{'s' if len(local.files) != 1 else ''})"
            tip = "Your working tree: HEAD plus these uncommitted changes:\n" + "\n".join(
                f"  {f}" for f in local.files[:20]) + ("\n  ..." if len(local.files) > 20 else "")
        else:
            subject = "HEAD (no uncommitted changes)"
            tip = "Your working tree, which matches HEAD."
        if head and not filtered():  # with filters the first row needn't be HEAD
            tip += f"\n\nHEAD is {head.short}: {head.subject}"
        rows.append({"hash": LOCAL, "short": "HEAD*" if local.dirty else "HEAD", "pcb": local.pcb,
                     "sch": local.sch, "date": "now", "subject": subject, "tip": tip})
        for c in h.commits:
            message = c.subject + (f"\n\n{c.body}" if c.body else "")
            tip = f"{message}\n\n{c.author} · {c.date}\n{c.hash}"
            rows.append({"hash": c.hash, "short": c.short, "pcb": c.pcb, "sch": c.sch, "date": c.date[:16],
                         "subject": c.subject, "tip": tip})
        table.rows = rows
        keep = {r["hash"] for r in rows}
        table.selected = [r for r in table.selected if r["hash"] in keep]
        table.update()
        on_select()

    def on_select() -> None:
        # At most two, keeping the most recently picked.
        if len(table.selected) > 2:
            table.selected = table.selected[-2:]
            table.update()
        n = len(table.selected)
        compare_btn.set_enabled(n == 2)
        names = [r["short"] for r in table.selected]
        picked.text = (" ↔ ".join(names) if n == 2 else f"{names[0]} + pick one more" if n == 1
                       else "Nothing picked")
        hint.set_visibility(state["history"] is not None)

    # ---------------------------------------------------------------- compare
    async def compare() -> None:
        if len(table.selected) != 2:
            return
        a, b = (r["hash"] for r in table.selected)
        await run_diff(a, b, compare_btn)

    async def compare_manually() -> None:
        a, b = (old_rev.value or "").strip(), (new_rev.value or "").strip()
        if not a or not b:
            notify("Enter both an old and a new commit", type="warning")
            return
        await run_diff(a, b, manual_btn)

    async def run_diff(a: str, b: str, button: ui.button) -> None:
        """Diffs two revisions and shows the viewer. kigit orders them by
        history (older first); LOCAL is always the newest."""
        board = state["board"]
        if not board:
            notify("Open a project first", type="warning")
            return
        name = page_name(board + ("|silk" if silk.value else ""), a, b)
        out = CACHE / name
        # Only full hashes always mean the same commit; names like HEAD~1 or
        # a branch can move, and LOCAL changes as you edit, so re-diff those.
        cacheable = all(len(r) == 40 and all(c in "0123456789abcdef" for c in r) for r in (a, b))
        button.props("loading")
        logs.log.info("compare %s .. %s%s", a, b, " (with silkscreen)" if silk.value else "")
        status.text = "Comparing..."
        started = time.monotonic()
        try:
            if not (cacheable and out.exists()):
                for w in await kigit.diff_html(board, a, b, out, silkscreen=silk.value):
                    notify(w, type="warning", multi_line=True, close_button=True)
        except kigit.KigitError as e:
            status.text = ""
            notify(str(e), type="negative", multi_line=True, close_button=True)
            return
        finally:
            button.props(remove="loading")
        status.text = f"{short_rev(a)} ↔ {short_rev(b)} · {time.monotonic() - started:.1f} s"
        logs.log.info("compared %s .. %s in %.2f s", a, b, time.monotonic() - started)
        # Open on the schematic; the cache-buster makes a regenerated page reload.
        frame.props(f'src="/diffs/{name}?t={int(time.time())}#sch"')
        placeholder.set_visibility(False)
        frame.set_visibility(True)

    # ------------------------------------------------- compare folders (no git)
    async def compare_folders(old: str = "", new: str = "") -> None:
        """Compare two copies of a project, each given by its folder."""
        boards: dict[str, str | None] = {"old": None, "new": None}

        with dialog_host, ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full bg-[#161a20] gap-3"):
            ui.label("Compare two KiCad project folders").classes("text-base font-semibold")
            ui.label("No git needed: pick the folder of each copy (an older backup, a colleague's version, ...). "
                     "kigit finds the board in each, and the schematic next to it.").classes("text-xs text-gray-400")

            def side(key: str, title: str, start: str):
                with ui.column().classes("w-full gap-1"):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        box = ui.input(title, value=start, placeholder="project folder").props(
                            "dense dark outlined").classes("flex-grow").mark(f"folder-{key}")
                        browse_btn = ui.button(icon="folder_open").props("flat dense round").tooltip("Browse")
                    found = ui.label("").classes("text-xs")
                    choice = ui.select([], label="Board").props("dense dark outlined").classes("w-full")
                    choice.set_visibility(False)

                async def detect() -> None:
                    folder = (box.value or "").strip()
                    boards[key] = None
                    choice.set_visibility(False)
                    if not folder:
                        found.text = ""
                    elif not Path(folder).expanduser().is_dir():
                        found.text = "Not a folder."
                        found.classes(replace="text-xs text-red-400")
                    else:
                        try:
                            projects = [p for p in await kigit.projects(str(Path(folder).expanduser()), SEARCH_DEPTH)
                                        if p.pcb]
                        except kigit.KigitError as e:
                            projects, found.text = [], str(e)
                        if not projects:
                            found.text = f"No KiCad board (.kicad_pcb) here or {SEARCH_DEPTH} levels below."
                            found.classes(replace="text-xs text-red-400")
                        elif len(projects) == 1:
                            boards[key] = projects[0].board
                            found.text = f"✓ {Path(projects[0].board).name}"
                            found.classes(replace="text-xs text-green-400")
                        else:
                            options = {p.board: os.path.relpath(p.board, folder) for p in projects}
                            choice.options = options
                            choice.value = None
                            choice.update()
                            choice.set_visibility(True)
                            found.text = f"{len(projects)} boards here; pick one:"
                            found.classes(replace="text-xs text-amber-400")
                    refresh()

                def picked(e) -> None:
                    boards[key] = e.value
                    refresh()

                async def browse_side() -> None:
                    chosen = await FolderPicker(box.value or folder_input.value or str(Path.home()))
                    if chosen:
                        box.value = chosen
                        await detect()

                box.on("blur", detect)
                box.on("keydown.enter", detect)
                browse_btn.on_click(browse_side)
                choice.on_value_change(picked)
                return detect

            detect_old = side("old", "Old (before)", old)
            detect_new = side("new", "New (after)", new)
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
                def go_compare() -> None:
                    # Checked here too: the button is disabled until both are
                    # found, but don't rely on that alone.
                    if boards["old"] and boards["new"]:
                        dialog.submit((boards["old"], boards["new"]))
                    else:
                        notify("Pick two project folders that each have a KiCad board", type="warning")

                go = ui.button("Compare", icon="compare_arrows", on_click=go_compare).props(
                    "unelevated color=amber-8").mark("compare-folders-go")

            def refresh() -> None:
                go.set_enabled(bool(boards["old"] and boards["new"]))

            refresh()

        dialog.open()
        await detect_old()
        await detect_new()
        result = await dialog
        if result:
            await run_files_diff(*result)

    async def run_files_diff(old_board: str, new_board: str) -> None:
        # Always regenerated: files on disk can change between comparisons.
        name = page_name("files" + ("|silk" if silk.value else ""), old_board, new_board)
        status.text = "Comparing..."
        logs.log.info("compare files %s .. %s", old_board, new_board)
        started = time.monotonic()
        try:
            for w in await kigit.diff_files_html(old_board, new_board, CACHE / name, silkscreen=silk.value):
                notify(w, type="warning", multi_line=True, close_button=True)
        except kigit.KigitError as e:
            status.text = ""
            notify(str(e), type="negative", multi_line=True, close_button=True)
            return
        label = lambda b: Path(b).parent.name or Path(b).name
        status.text = f"{label(old_board)} ↔ {label(new_board)} (no git) · {time.monotonic() - started:.1f} s"
        logs.log.info("compared files in %.2f s", time.monotonic() - started)
        frame.props(f'src="/diffs/{name}?t={int(time.time())}#sch"')
        placeholder.set_visibility(False)
        frame.set_visibility(True)

    # Pop-up dialogs live here, whichever button opens them.
    dialog_host = ui.element("div")

    on_select()
    return open_folder


# Anything that goes wrong inside the GUI ends up in the session log, with its traceback.
app.on_exception(lambda e: logs.log.error("unhandled error in the GUI", exc_info=e))


@ui.page("/")
async def index() -> None:
    # The starting folder comes from `kigit gui [PROJECT_DIR]` (see main()).
    folder = os.environ.get("KIGIT_PROJECT", os.getcwd())
    open_folder = build(folder)
    await open_folder(folder)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kigit gui", description="kigit desktop GUI")
    parser.add_argument("project", nargs="?", default=".", help="KiCad project folder (default: current folder)")
    parser.add_argument("--port", type=int, default=8765, help="local port (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    parser.add_argument("--log-dir", help="folder for the session log (default: $KIGIT_LOG_DIR, else the app data folder)")
    parser.add_argument("--no-log", action="store_true", help="don't write a session log file")
    parser.add_argument("-V", "--verbose", action="store_true", help="include debug lines in the log")
    args = parser.parse_args()
    os.environ["KIGIT_PROJECT"] = str(Path(args.project).expanduser().resolve())
    log_file = logs.start(args.log_dir, enabled=not args.no_log, debug=args.verbose)
    logs.log.info("session start: kigit gui | project %s | log %s", os.environ["KIGIT_PROJECT"], log_file or "(none)")
    # Ctrl+C must actually stop the GUI. The web server normally waits for
    # open connections to close first, and the browser tab keeps one open, so
    # it would wait forever (on Windows especially). Give it 2 seconds, and
    # force the exit if shutting down still hangs.
    def on_shutdown() -> None:
        logs.log.info("shutting down")

        def force_exit() -> None:
            time.sleep(5)
            logs.log.warning("shutdown took too long; exiting anyway")
            os._exit(0)

        threading.Thread(target=force_exit, daemon=True).start()

    app.on_shutdown(on_shutdown)
    try:
        ui.run(title="kigit", port=args.port, show=not args.no_browser, reload=False, dark=True,
               timeout_graceful_shutdown=2,
               favicon="🦉", show_welcome_message=False)
    except KeyboardInterrupt:
        # Ctrl+C: the server has shut down already; no traceback.
        logs.log.info("stopped (Ctrl+C)")


if __name__ in {"__main__", "__mp_main__"}:
    main()
