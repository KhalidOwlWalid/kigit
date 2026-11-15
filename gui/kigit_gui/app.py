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
  4. Or pick one commit and press Review: it's diffed against its parent and
     the review panel opens on the right, for notes on why it changed
     (review_panel.py, saved in <project>/reviews/).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

from nicegui import app, background_tasks, ui

from . import kigit, logs, review, rewritten
from .folder_picker import FolderPicker
from .resize import Resizer
from . import board3d, review_doc  # noqa: F401  (register the /board3d and /reviews-doc pages)
from .review_panel import BRIDGE_JS, ReviewPanel, focus_script, project_key

LOCAL = "LOCAL"
SEARCH_DEPTH = 2

# Generated pages are served from here. Commit-to-commit diffs never change,
# so they're kept for the session; anything involving LOCAL is regenerated.
CACHE = Path(tempfile.mkdtemp(prefix="kigit-gui-"))
app.add_static_files("/diffs", str(CACHE))

# Message column: one line (or wrapped, with "Wrap messages"), the whole
# message on hover. It takes what the commit list's width leaves (the drawer
# is a size container, see resize.py).
MESSAGE_CELL = r"""
<q-td :props="props" class="kigit-msg-td">
  <div class="kigit-msg ellipsis" style="max-width: max(6rem, calc(100cqw - 19rem))">{{ props.row.subject }}</div>
  <q-tooltip anchor="center right" self="center left" max-width="34rem"
             class="bg-grey-10 text-body2" style="white-space: pre-wrap">{{ props.row.tip }}</q-tooltip>
</q-td>
"""

# Commit column: the working tree row stands out. With "Wrap messages" the
# date column is hidden and the date shows here, under the hash.
COMMIT_CELL = r"""
<q-td :props="props">
  <span :class="props.row.hash === 'LOCAL' ? 'text-amber-5 text-weight-bold' : 'text-mono'">{{ props.row.short }}</span>
  <div class="kigit-date text-grey-6" style="font-size: 11px">{{ props.row.date }}</div>
</q-td>
"""

TAGS_CELL = r"""
<q-td :props="props">
  <q-badge v-if="props.row.pcb" outline color="blue-4" label="PCB" class="q-mr-xs" />
  <q-badge v-if="props.row.sch" outline color="green-4" label="SCH" class="q-mr-xs" />
  <q-icon v-if="props.row.reviewed" name="rate_review" color="amber-5" size="xs"><q-tooltip>Reviewed</q-tooltip></q-icon>
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


MAX_3D = 4  # boards side by side in the 3D view


def board3d_name(board: str, rev: str) -> str:
    """The cached 3D model's file name. A commit never changes; the working
    tree is named by the board file's time and size, so an edit makes a new
    one. Other names (HEAD~1, a branch) can move, so they're never reused."""
    if rev != LOCAL and not is_hash(rev):
        rev = f"{rev}|{time.time_ns()}"
    if rev == LOCAL:
        try:
            st = Path(board).stat()
            rev = f"{LOCAL}|{st.st_mtime_ns}|{st.st_size}"
        except OSError:
            rev = f"{LOCAL}|{time.time()}"
    return hashlib.sha1(f"{board}|{rev}".encode()).hexdigest()[:12] + ".glb"


def is_hash(rev: str) -> bool:
    return len(rev) == 40 and all(c in "0123456789abcdef" for c in rev)


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
    state: dict = {"board": None, "history": None, "strays": []}
    resizer = Resizer()

    # ---------------------------------------------------------------- header
    with ui.header().classes("items-center gap-3 py-2 px-4 bg-[#161a20] border-b border-[#29303a] no-wrap"):
        ui.label("kigit").classes("text-lg font-bold text-[#e8b84d]")
        folder_input = ui.input(value=start_folder, placeholder="KiCad project folder").props(
            "dense dark outlined").classes("w-[30rem]")
        folder_input.on("keydown.enter", lambda: open_folder(folder_input.value))
        ui.button("Browse", icon="folder_open", on_click=lambda: browse()).props("flat dense")
        ui.button("Open", on_click=lambda: open_folder(folder_input.value)).props("flat dense")
        status = ui.label("").classes("text-sm text-gray-400 ml-auto truncate")
        dock_btn = ui.button("3D", icon="view_in_ar", on_click=lambda: dock_toggle()).props("flat dense").tooltip(
            "Show the board in 3D beside the comparison (New, Old or both)").mark("dock-button")
        dock_btn.set_visibility(False)
        ui.button("Reviews", icon="menu_book", on_click=lambda: open_reviews_doc()).props("flat dense").tooltip(
            "All of this project's written reviews as one page, in a new tab").mark("reviews-doc")
        ui.button("Compare folders", icon="difference", on_click=lambda: compare_folders()).props(
            "flat dense").tooltip("Compare two copies of a KiCad project, without git").mark("compare-folders")
        ui.button(icon="receipt_long", on_click=show_log).props("flat dense round").tooltip("Session log").mark("log-button")

    # ----------------------------------------------------------- commit list
    with ui.left_drawer(value=True, bordered=True).classes("bg-[#161a20] p-0") as commits_drawer:
        with ui.column().classes("w-full p-3 gap-2"):
            project_label = ui.label("").classes("text-sm font-semibold")
            hint = ui.label("Pick two commits and press Compare, or one and press Review.").classes(
                "text-xs text-gray-400")
            with ui.row().classes("w-full gap-2 items-center no-wrap"):
                compare_btn = ui.button("Compare", on_click=lambda: compare()).props("unelevated dense color=amber-8").mark("compare-button")
                review_btn = ui.button("Review", icon="rate_review", on_click=lambda: review_commit()).props(
                    "unelevated dense color=blue-grey-8").tooltip(
                    "Compare this commit with the one before it and write down why it changed").mark("review-button")
                view3d_btn = ui.button("3D", icon="view_in_ar", on_click=lambda: view_3d()).props(
                    "unelevated dense color=blue-grey-8").tooltip(
                    "See this commit's board in 3D, as KiCad draws it (made by kicad-cli)").mark("view3d-button")
                picked = ui.label("").classes("text-xs text-gray-300 truncate")
            # Off by default: silkscreen makes comparisons slower and pages bigger.
            silk = ui.checkbox("Include silkscreen", value=False).props("dense dark").classes("text-xs").tooltip(
                "Also compare and draw the silkscreen (labels, outlines, logos). Applies to every comparison."
            ).mark("include-silkscreen")
            # Off by default too: adds every changed item's file text to the page.
            src = ui.checkbox("Include source", value=False).props("dense dark").classes("text-xs").tooltip(
                "Add a source panel under the viewer: hover a trace, part or wire to see its text in the old and "
                "new .kicad_pcb / .kicad_sch, side by side like a code diff. Applies to every comparison."
            ).mark("include-source")
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
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                count = ui.label("").classes("text-xs text-gray-400 flex-grow")
                wrap = ui.switch("Wrap messages", on_change=lambda e: set_wrap(e.value)).props(
                    "dense dark size=xs").classes("text-xs text-gray-400").tooltip(
                    "Show long commit messages on several lines instead of cutting them off").mark("wrap-messages")
            # Reviews of commits a rebase, amend or squash replaced (rewritten.py).
            with ui.row().classes("w-full items-center gap-2 no-wrap bg-[#2a2416] rounded px-2 py-1") as stray_bar:
                ui.icon("warning", size="xs").classes("text-amber-500")
                stray_label = ui.label("").classes("text-xs text-amber-200 flex-grow").mark("stray-reviews")
                ui.button("Fix", icon="build", on_click=lambda: fix_strays()).props(
                    "flat dense no-caps size=sm color=amber-5").mark("fix-strays")
            stray_bar.mark("stray-bar")
            stray_bar.set_visibility(False)
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

    # Wrapped messages: a class on the table (CSS below), remembered in the browser.
    ui.add_head_html("""<style>
.kigit-date { display: none; }
.kigit-wrap .kigit-date { display: block; }
/* The message column takes what the others leave, and wraps within it. */
.kigit-wrap td.kigit-msg-td { width: 100%; white-space: normal; }
.kigit-wrap .kigit-msg { white-space: normal; overflow: visible; text-overflow: clip; overflow-wrap: anywhere;
  max-width: none !important; }
.kigit-wrap tbody td { vertical-align: top; }
</style>""")
    ui.add_body_html("""<script>
(() => {
  let tries = 0;
  const restore = setInterval(() => {
    if (typeof mounted_app !== "undefined" && mounted_app) {
      clearInterval(restore);
      let on = false;
      try { on = localStorage.getItem("kigit.wrapMessages") === "1"; } catch { /* private mode */ }
      if (on) emitEvent("kigit_wrap", true);
    } else if (++tries > 100) clearInterval(restore);
  }, 100);
})();
</script>""")
    ui.on("kigit_wrap", lambda e: setattr(wrap, "value", bool(e.args)))

    def set_wrap(on: bool) -> None:
        table.classes(add="kigit-wrap") if on else table.classes(remove="kigit-wrap")
        # The date moves under the hash, leaving the message more room.
        table.columns = [c for c in columns if not (on and c["name"] == "date")]
        table.update()
        ui.run_javascript(f'try {{ localStorage.setItem("kigit.wrapMessages", "{1 if on else 0}") }} catch {{}}')
    resizer.add(commits_drawer, "left", "commits", 480)

    # ---------------------------------------------------------------- viewer
    # The comparison, and the 3D dock beside it (its width: --kigit-dock-w,
    # dragged by the grip, remembered in the browser).
    with ui.element("div").classes("kigit-split w-full h-[calc(100vh-52px)] flex no-wrap") as split:
        with ui.element("div").classes("kigit-main h-full flex-1 min-w-0 min-h-0 relative"):
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
        dock_grip = ui.element("div").classes("kigit-dock-grip").props(
            'title="Drag to resize; double-click to reset"').mark("dock-grip")
        with ui.column().classes("kigit-dock h-full gap-0 no-wrap bg-[#0f1115]") as dock:
            with ui.row().classes("w-full items-center gap-2 px-2 py-1 no-wrap bg-[#161a20] border-b border-[#29303a]"):
                ui.icon("view_in_ar").classes("text-amber-500")
                ui.label("3D").classes("text-sm font-semibold")
                dock_away = ui.label("in another tab").classes("text-xs text-amber-300").mark("dock-away")
                dock_away.set_visibility(False)
                dock_side = ui.toggle({"new": "New", "old": "Old", "both": "Both"}, value="new",
                                      on_change=lambda: dock_load()).props(
                    "dense no-caps size=sm toggle-color=amber-8 text-color=grey-5").mark("dock-side")
                ui.space()
                # Opened in the click itself (window.open needs the user's
                # click, or the browser blocks it), then the server is told.
                dock_out = ui.button(icon="open_in_new").props("flat dense round size=sm").tooltip(
                    "Open it in a new browser tab; close that tab to bring it back here").mark("dock-popout")
                dock_back = ui.button("Bring back", icon="login", on_click=lambda: ui.run_javascript(
                    "window.kigitPopout && window.kigitPopout.close()")).props(
                    "flat dense no-caps size=sm color=amber-5").mark("dock-bring-back")
                dock_back.set_visibility(False)
                dock_place = ui.button(icon="horizontal_split", on_click=lambda: set_dock_below(
                    not state.get("dock_below"))).props("flat dense round size=sm").mark("dock-place")
                with dock_place:
                    dock_place_tip = ui.tooltip("Dock it below the comparison")
                ui.button(icon="close", on_click=lambda: dock_close()).props("flat dense round size=sm").tooltip(
                    "Close the 3D view")
            with ui.element("div").classes("kigit-dock-body w-full flex-1 relative min-h-0"):
                dock_frame = ui.element("iframe").classes("w-full h-full border-0 bg-[#0f1115]").mark("dock-viewer")
                with ui.column().classes("absolute inset-0 items-center justify-center gap-3 p-6") as dock_wait:
                    dock_spinner = ui.spinner(size="lg", color="amber-7")
                    dock_msg = ui.label("").classes("text-xs text-gray-400 text-center").mark("dock-message")
        dock.set_visibility(False)
        dock_grip.set_visibility(False)
    ui.add_head_html("""<style>
.kigit-dock { width: var(--kigit-dock-w, clamp(320px, 40%, 900px)); flex: none; }
.kigit-dock-grip { width: 5px; flex: none; cursor: col-resize; background: #29303a; }
/* Docked below: the comparison keeps the full width. */
.kigit-split.below { flex-direction: column; }
.kigit-split.below > .kigit-main { height: auto; }
.kigit-split.below > .kigit-dock { width: 100%; height: var(--kigit-dock-h, 45%); }
.kigit-split.below > .kigit-dock-grip { width: 100%; height: 5px; cursor: row-resize; }
/* In another tab: only the dock's header bar stays, under the comparison. */
.kigit-split.popped { flex-direction: column; }
.kigit-split.popped > .kigit-main { height: auto; }
.kigit-split.popped > .kigit-dock { width: 100%; height: auto; }
.kigit-split.popped > .kigit-dock-grip, .kigit-split.popped .kigit-dock-body { display: none; }
.kigit-dock-grip:hover, body.kigit-dragging .kigit-dock-grip { background: #e8b84d; }
body.kigit-dragging iframe { pointer-events: none; }  /* else the frames swallow the drag */
</style>""")
    ui.add_body_html("""<script>
(() => {
  const root = document.documentElement;
  try {
    const w = localStorage.getItem("kigit.dockWidth"), h = localStorage.getItem("kigit.dockHeight");
    if (w) root.style.setProperty("--kigit-dock-w", w + "px");
    if (h) root.style.setProperty("--kigit-dock-h", h + "px");
  } catch {}
  // Where the dock was last put (beside or below), once the page is up.
  let tries = 0;
  const restore = setInterval(() => {
    if (typeof mounted_app === "undefined" || !mounted_app) { if (++tries > 100) clearInterval(restore); return; }
    clearInterval(restore);
    let v = null;
    try { v = localStorage.getItem("kigit.dockBelow"); } catch {}
    if (v !== null) emitEvent("kigit_dock_below", v === "1");
  }, 100);
  document.addEventListener("pointerdown", (e) => {
    const grip = e.target.closest && e.target.closest(".kigit-dock-grip");
    if (!grip) return;
    e.preventDefault();
    const split = grip.parentElement, below = split.classList.contains("below");
    const box = split.getBoundingClientRect();
    document.body.classList.add("kigit-dragging");
    let size = null;
    // The comparison keeps at least 300 px (200 px tall when below).
    const move = (ev) => {
      if (below) {
        size = Math.round(Math.min(Math.max(box.bottom - ev.clientY, 180), Math.max(180, box.height - 200)));
        root.style.setProperty("--kigit-dock-h", size + "px");
      } else {
        size = Math.round(Math.min(Math.max(box.right - ev.clientX, 260), Math.max(260, box.width - 300)));
        root.style.setProperty("--kigit-dock-w", size + "px");
      }
    };
    const up = () => {
      document.body.classList.remove("kigit-dragging");
      removeEventListener("pointermove", move);
      removeEventListener("pointerup", up);
      if (size) try { localStorage.setItem(below ? "kigit.dockHeight" : "kigit.dockWidth", size); } catch {}
    };
    addEventListener("pointermove", move);
    addEventListener("pointerup", up);
  });
  // The 3D view in its own tab: opened here (in the click), watched until
  // it's closed, then the dock takes it back (unless kigit closed it).
  window.kigitPopOut = (src) => {
    const w = window.open(src && src !== "about:blank" ? src : "about:blank", "_blank");
    if (!w) return false;
    window.kigitPopout = w;
    window.kigitPopoutQuiet = false;
    clearInterval(window.kigitPopoutTimer);
    window.kigitPopoutTimer = setInterval(() => {
      if (!w.closed) return;
      clearInterval(window.kigitPopoutTimer);
      window.kigitPopout = null;
      if (!window.kigitPopoutQuiet) emitEvent("kigit_dock_back");
    }, 400);
    return true;
  };
  document.addEventListener("dblclick", (e) => {
    if (!(e.target.closest && e.target.closest(".kigit-dock-grip"))) return;
    root.style.removeProperty("--kigit-dock-w");
    root.style.removeProperty("--kigit-dock-h");
    try { localStorage.removeItem("kigit.dockWidth"); localStorage.removeItem("kigit.dockHeight"); } catch {}
  });
})();
</script>""")

    # ---------------------------------------------------------------- review
    def focus(anchor) -> None:
        if not frame.visible:
            notify("Open the comparison first", type="warning")
            return
        ui.run_javascript(focus_script(frame.id, anchor))

    def on_focused(e) -> None:
        if not e.args.get("found"):
            a = review.Anchor.from_dict(e.args.get("anchor"))
            notify(f"{a.label if a else 'That'} isn't in this comparison", type="warning")

    def on_review_saved(commit: str) -> None:
        for r in table.rows:
            if r["hash"] == commit:
                r["reviewed"] = True
        table.update()

    panel = ReviewPanel(focus=focus, on_saved=on_review_saved, resizer=resizer,
                        strays=lambda: state["strays"], on_moved=lambda: background_tasks.create(check_strays()))

    # ------------------------------------------------- rewritten commits
    async def check_strays() -> None:
        """Looks for reviews of commits that are on no branch any more."""
        h = state["history"]
        if not (h and state["board"]):
            return
        state["strays"] = await rewritten.find(Path(state["board"]).parent, {c.hash for c in h.commits})
        n = len(state["strays"])
        stray_bar.set_visibility(n > 0)
        stray_label.text = (f"{n} review{'s are' if n > 1 else ' is'} of commits on no branch any more "
                            "(rebased, amended or squashed)")
        if panel.review:
            panel.bring_in_view.refresh()

    async def fix_strays() -> None:
        """Moves reviews of rewritten commits to the commits they became."""
        strays = state["strays"]
        project = Path(state["board"]).parent
        busy = {c for c in panel.drafts} | ({panel.commit} if panel.dirty else set())
        with dialog_host, ui.dialog() as dialog, ui.card().classes("w-[44rem] max-w-full bg-[#161a20] gap-2"):
            ui.label("Reviews of rewritten commits").classes("text-base font-semibold")
            ui.label("These reviews are of commits no branch has any more. A rebase or amend keeps a commit's "
                     "author and date, so the commit it became is found by those. Moving a review points it "
                     "at that commit (and merges it into that commit's review if it has one).").classes(
                "text-xs text-gray-400")
            picks = []
            for st in strays:
                r = st.review
                with ui.column().classes("w-full gap-1 bg-[#1c2128] rounded p-2"):
                    ui.label(f"{r.commit[:7]}  {r.subject or '(no message)'}").classes("text-sm font-mono")
                    if any(st.review.commit == c or any(m.hash == c for m in st.matches) for c in busy):
                        ui.label("Has unwritten edits: Write or leave them first.").classes("text-xs text-amber-300")
                    elif st.matches:
                        options = {i: f"{m.short}  {m.subject} · {m.date[:16]}" for i, m in enumerate(st.matches)}
                        with ui.row().classes("w-full items-center gap-2 no-wrap"):
                            box = ui.checkbox("Move to", value=len(st.matches) == 1).props("dense dark").classes(
                                "text-xs").mark("stray-move")
                            sel = ui.select(options, value=0 if len(st.matches) == 1 else None).props(
                                "dense dark outlined options-dense").classes("flex-grow text-xs").mark("stray-target")
                            sel.on_value_change(lambda e, b=box: b.set_value(True) if e.value is not None else None)
                        picks.append((st, box, sel))
                    else:
                        ui.label("No commit with the same author and date: probably squashed. Pick the commit "
                                 "it went into, press Review, then Bring in reviews.").classes(
                            "text-xs text-gray-400")

            def chosen() -> list:
                return [(st, st.matches[sel.value]) for st, box, sel in picks if box.value and sel.value is not None]

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Close", on_click=lambda: dialog.submit(None)).props("flat")
                ok = ui.button("Move", icon="drive_file_move", on_click=lambda: dialog.submit(chosen())).props(
                    "unelevated color=amber-8").mark("stray-ok")
                ok.set_enabled(bool(picks))
        dialog.open()
        moves = await dialog
        dialog.delete()
        if not moves:
            return
        if panel.commit and any(panel.commit in (st.review.commit, m.hash) for st, m in moves):
            panel.close()  # it shows a review that's about to change on disk
        try:
            rewritten.move_all(project, moves)
        except (OSError, ValueError, UnicodeDecodeError) as e:
            notify(f"Couldn't move the reviews: {e}", type="warning", multi_line=True, close_button=True)
        else:
            notify(f"Moved {len(moves)} review{'s' if len(moves) > 1 else ''}", type="positive")
        fill()
        await check_strays()

    def open_reviews_doc() -> None:
        if not state["board"]:
            notify("Open a project first", type="warning")
            return
        if panel.dirty or panel.drafts:
            notify("Unwritten review edits aren't in the page: press Write first", type="warning")
        logs.log.info("open reviews page for %s", Path(state["board"]).parent)
        ui.navigate.to(f"/reviews-doc/{project_key(Path(state['board']).parent)}", new_tab=True)
    ui.add_body_html(BRIDGE_JS)
    ui.on("kigit_pinned", lambda e: panel.set_pinned(review.Anchor.from_dict(e.args)))
    ui.on("kigit_focused", on_focused)

    def show_message(icon: str, text: str, more: str = "", tone: str = "text-gray-400") -> None:
        panel.close()
        no_comparison()
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
        await check_strays()
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
        await check_strays()

    # ------------------------------------------------------------ commit rows
    def fill() -> None:
        h = state["history"]
        if not h:
            table.rows = []
            table.update()
            return
        rows = []
        local = h.local
        reviewed = set(review.all_reviews(Path(state["board"]).parent))
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
                     "sch": local.sch, "date": "now", "subject": subject, "tip": tip, "parent": "",
                     "reviewed": False})
        for c in h.commits:
            message = c.subject + (f"\n\n{c.body}" if c.body else "")
            tip = f"{message}\n\n{c.author} · {c.date}\n{c.hash}"
            rows.append({"hash": c.hash, "short": c.short, "pcb": c.pcb, "sch": c.sch, "date": c.date[:16],
                         "subject": c.subject, "tip": tip, "parent": c.parent, "author": c.author, "body": c.body,
                         "reviewed": c.hash in reviewed})
        table.rows = rows
        keep = {r["hash"] for r in rows}
        table.selected = [r for r in table.selected if r["hash"] in keep]
        table.update()
        on_select()

    def on_select() -> None:
        # At most MAX_3D (several boards side by side in 3D), keeping the most
        # recently picked. Compare takes two, Review one.
        if len(table.selected) > MAX_3D:
            table.selected = table.selected[-MAX_3D:]
            table.update()
        n = len(table.selected)
        compare_btn.set_enabled(n == 2)
        review_btn.set_enabled(n == 1 and table.selected[0]["hash"] != LOCAL)
        view3d_btn.set_enabled(1 <= n <= MAX_3D and not state.get("busy3d"))
        names = [r["short"] for r in table.selected]
        picked.text = (" ↔ ".join(names) if n == 2 else f"{names[0]}: review it, or pick one more" if n == 1
                       else f"{', '.join(names)}: 3D side by side" if n > 2 else "Nothing picked")
        hint.set_visibility(state["history"] is not None)

    # ---------------------------------------------------------------- compare
    # The viewer options (checkboxes): part of a cached page's name, and the log line.
    def options_key() -> str:
        return ("|silk" if silk.value else "") + ("|src" if src.value else "")

    def options_note() -> str:
        on = [n for n, v in (("silkscreen", silk.value), ("source", src.value)) if v]
        return f" (with {', '.join(on)})" if on else ""

    async def compare() -> None:
        if len(table.selected) != 2:
            return
        a, b = table.selected
        # A commit and its parent: that's the commit's own change, so its review opens too.
        child = a if a.get("parent") == b["hash"] else b if b.get("parent") == a["hash"] else None
        await run_diff(a["hash"], b["hash"], compare_btn, review_of=child)

    async def review_commit() -> None:
        if len(table.selected) != 1 or table.selected[0]["hash"] == LOCAL:
            return
        row = table.selected[0]
        if not row.get("parent"):
            notify("This is the first commit: there's nothing before it to compare with", type="warning")
            return
        await run_diff(row["parent"], row["hash"], review_btn, review_of=row)

    # ------------------------------------------------------------------- 3D
    async def build_models(names: dict[str, str]) -> list[tuple[str, BaseException]]:
        """Makes the missing 3D models (rev -> file name in CACHE) with kigit
        --3d, all at once. Returns the ones that failed."""
        board = state["board"]
        todo = [r for r, n in names.items() if not (CACHE / n).exists()]
        if not todo:
            return []
        started = time.monotonic()
        logs.log.info("3d %s", " ".join(todo))
        results = await asyncio.gather(*(kigit.board3d(board, r, CACHE / names[r]) for r in todo),
                                       return_exceptions=True)
        failed = []
        for r, result in zip(todo, results):
            if isinstance(result, BaseException):
                failed.append((r, result))
                continue
            for w in result:
                notify(w, type="warning", multi_line=True, close_button=True)
        logs.log.info("3d done in %.1f s", time.monotonic() - started)
        return failed

    def board3d_src(items: list[tuple[str, str, str]]) -> str:
        """The 3D page for (file name, commit label, subject) items: one board,
        or several side by side."""
        name = state.get("name") or Path(state["board"]).stem
        if len(items) == 1:
            n, label, subject = items[0]
            return f"/board3d/{n}?" + urllib.parse.urlencode({"title": f"{name} · {label}", "subtitle": subject})
        return "/board3d-grid?" + urllib.parse.urlencode(
            [p for n, label, subject in items for p in (("b", n), ("t", f"{name} · {label}"), ("s", subject))])

    def subject_of(rev: str) -> str:
        return next((r.get("subject", "") for r in table.rows if r["hash"] == rev), "")

    async def view_3d() -> None:
        """Shows the picked commits' boards in 3D: one, or up to MAX_3D side by
        side (oldest first, views linked). KiCad makes each model, all at once;
        a big board takes a while, and each commit's is kept for the session."""
        n = len(table.selected)
        if not 1 <= n <= MAX_3D or not state["board"]:
            return
        board = state["board"]
        order = {r["hash"]: i for i, r in enumerate(table.rows)}
        rows = sorted(table.selected, key=lambda r: -order.get(r["hash"], 0))  # oldest first: lowest in the list
        names = {r["hash"]: board3d_name(board, r["hash"]) for r in rows}
        todo = [r for r in rows if not (CACHE / names[r["hash"]]).exists()]
        if todo:
            state["busy3d"] = True
            on_select()
            view3d_btn.props("loading")
            which = ", ".join(r["short"] for r in todo)
            show_message("view_in_ar", f"Building the 3D board{'s' if len(todo) > 1 else ''} of {which} with KiCad...",
                         "kicad-cli exports the board with its parts' 3D models. A big board takes a while "
                         "(half a minute or so; several are made at the same time); after that a commit opens "
                         "straight away.")
            status.text = "Building 3D board..."
            started = time.monotonic()
            failed = await build_models(names)
            state["busy3d"] = False
            view3d_btn.props(remove="loading")
            on_select()
            if failed:
                status.text = ""
                short = {r["hash"]: r["short"] for r in rows}
                show_message("error_outline", "Couldn't make the 3D board.",
                             "\n".join(f"{short[r]}: {e}" for r, e in failed), tone="text-red-400")
                return
            status.text = f"3D {which} · {time.monotonic() - started:.1f} s"
        panel.close()
        panel.set_pinned(None)
        no_comparison()
        frame.props(f'src="{board3d_src([(names[r["hash"]], r["short"], r.get("subject", "")) for r in rows])}"')
        placeholder.set_visibility(False)
        no_git_button.set_visibility(False)
        frame.set_visibility(True)

    # The 3D dock: the comparison's boards in 3D beside it (state["pair"]: old, new).
    def no_comparison() -> None:
        """No comparison on screen any more: no dock."""
        state["pair"] = None
        dock_btn.set_visibility(False)
        dock_close()

    def set_popped(on: bool) -> None:
        """The 3D view in another tab (on), or back in the dock."""
        state["popped"] = on
        split.classes(add="popped") if on else split.classes(remove="popped")
        dock_away.set_visibility(on)
        dock_back.set_visibility(on)
        dock_out.set_visibility(not on)
        dock_place.set_visibility(not on)
        if on:
            dock_frame.props('src="about:blank"')  # one copy is enough: frees its WebGL memory

    def popped_out(e) -> None:
        if not e.args:
            notify("The browser blocked the new tab: allow pop-ups for this page, then try again", type="warning")
            return
        logs.log.info("3d dock opened in a new tab")
        set_popped(True)
        if not state.get("dock_src"):  # still being made: the tab gets it when it's ready
            dock_away.text = "in another tab (being made...)"

    async def dock_came_back(_=None) -> None:
        if not state.get("popped"):
            return
        logs.log.info("3d tab closed: back in the dock")
        set_popped(False)
        await dock_load()

    dock_out.on("click", popped_out, js_handler=f"""() => {{
        const f = getHtmlElement({dock_frame.id});
        emit(window.kigitPopOut(f ? f.getAttribute("src") : ""));
    }}""")
    ui.on("kigit_dock_back", dock_came_back)

    def dock_close() -> None:
        if state.get("popped"):  # closed by kigit: not a "bring it back"
            ui.run_javascript("window.kigitPopoutQuiet = true; window.kigitPopout && window.kigitPopout.close()")
            set_popped(False)
        state["dock_src"] = ""
        state["dock_token"] = state.get("dock_token", 0) + 1  # a model still being made isn't shown
        dock.set_visibility(False)
        dock_grip.set_visibility(False)
        dock_frame.props('src="about:blank"')  # frees its WebGL memory

    def set_dock_below(on: bool, remember: bool = True) -> None:
        """Docks the 3D view below the comparison, or beside it."""
        state["dock_below"] = on
        split.classes(add="below") if on else split.classes(remove="below")
        dock_place.props(f"icon={'vertical_split' if on else 'horizontal_split'}")
        dock_place_tip.text = "Dock it beside the comparison" if on else "Dock it below the comparison"
        if remember:
            state["dock_placed"] = True
            ui.run_javascript(f'try {{ localStorage.setItem("kigit.dockBelow", "{1 if on else 0}") }} catch {{}}')

    def restored_dock(e) -> None:
        state["dock_placed"] = True
        set_dock_below(bool(e.args), remember=False)
    ui.on("kigit_dock_below", restored_dock)

    async def dock_toggle() -> None:
        if dock.visible:
            dock_close()
            return
        if not state.get("dock_placed"):
            # Not placed yet: below when the comparison would be squeezed beside it.
            try:
                width = await ui.run_javascript("document.querySelector('.kigit-split')?.clientWidth || 0", timeout=2)
            except TimeoutError:
                width = 0
            set_dock_below(bool(width) and width < 1100, remember=False)
        dock.set_visibility(True)
        dock_grip.set_visibility(True)
        await dock_load()

    async def dock_load() -> None:
        """Shows the comparison's New, Old or both boards in the dock, making
        their models first if needed."""
        pair = state.get("pair")
        if not pair or not dock.visible:
            return
        side = dock_side.value
        revs = list(pair) if side == "both" else [pair[0] if side == "old" else pair[1]]
        token = state["dock_token"] = state.get("dock_token", 0) + 1
        board = state["board"]
        names = {r: board3d_name(board, r) for r in revs}
        state["dock_src"] = ""
        if any(not (CACHE / n).exists() for n in names.values()):
            dock_frame.set_visibility(False)
            dock_wait.set_visibility(True)
            dock_spinner.set_visibility(True)
            dock_msg.text = (f"Building the 3D board of {' and '.join(short_rev(r) for r in revs)} with KiCad... "
                             "A big board takes about half a minute; the comparison stays usable.")
            failed = await build_models(names)
            if token != state.get("dock_token"):
                return  # closed, or another side picked meanwhile
            if failed:
                dock_spinner.set_visibility(False)
                dock_msg.text = "Couldn't make the 3D board. " + " ".join(f"{short_rev(r)}: {e}" for r, e in failed)
                return
        if token != state.get("dock_token"):
            return
        src = state["dock_src"] = board3d_src([(names[r], short_rev(r), subject_of(r)) for r in revs])
        dock_wait.set_visibility(False)
        if state.get("popped"):  # the other tab shows it
            dock_away.text = "in another tab"
            ui.run_javascript(f"window.kigitPopout && !window.kigitPopout.closed && "
                              f"(window.kigitPopout.location.href = {json.dumps(src)})")
            return
        dock_frame.props(f'src="{src}"')
        dock_frame.set_visibility(True)

    async def compare_manually() -> None:
        a, b = (old_rev.value or "").strip(), (new_rev.value or "").strip()
        if not a or not b:
            notify("Enter both an old and a new commit", type="warning")
            return
        await run_diff(a, b, manual_btn)

    async def run_diff(a: str, b: str, button: ui.button, review_of: dict | None = None) -> None:
        """Diffs two revisions and shows the viewer. kigit orders them by
        history (older first); LOCAL is always the newest. review_of: the
        commit row whose review opens alongside (a single commit's change)."""
        board = state["board"]
        if not board:
            notify("Open a project first", type="warning")
            return
        name = page_name(board + options_key(), a, b)
        out = CACHE / name
        # Only full hashes always mean the same commit; names like HEAD~1 or
        # a branch can move, and LOCAL changes as you edit, so re-diff those.
        cacheable = all(len(r) == 40 and all(c in "0123456789abcdef" for c in r) for r in (a, b))
        button.props("loading")
        logs.log.info("compare %s .. %s%s", a, b, options_note())
        status.text = "Comparing..."
        started = time.monotonic()
        try:
            if not (cacheable and out.exists()):
                for w in await kigit.diff_html(board, a, b, out, silkscreen=silk.value, source=src.value):
                    notify(w, type="warning", multi_line=True, close_button=True)
        except kigit.KigitError as e:
            status.text = ""
            notify(str(e), type="negative", multi_line=True, close_button=True)
            return
        finally:
            button.props(remove="loading")
        status.text = f"{short_rev(a)} ↔ {short_rev(b)} · {time.monotonic() - started:.1f} s"
        logs.log.info("compared %s .. %s in %.2f s", a, b, time.monotonic() - started)
        show_page(name)
        # Older first: lower in the list (LOCAL, at the top, is the newest).
        order = {r["hash"]: i for i, r in enumerate(table.rows)}
        if a in order and b in order and order[a] < order[b]:
            a, b = b, a
        state["pair"] = (a, b)
        dock_btn.set_visibility(True)
        if dock.visible:
            background_tasks.create(dock_load())
        if review_of:
            panel.open(Path(board).parent, review_of["hash"], review_of.get("parent", ""), review_of["subject"],
                       review_of.get("date", ""), review_of.get("author", ""), review_of.get("body", ""))
        else:
            panel.close()

    def show_page(name: str) -> None:
        # Open on the schematic; the cache-buster makes a regenerated page reload.
        panel.set_pinned(None)
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
        name = page_name("files" + options_key(), old_board, new_board)
        status.text = "Comparing..."
        logs.log.info("compare files %s .. %s", old_board, new_board)
        started = time.monotonic()
        try:
            for w in await kigit.diff_files_html(old_board, new_board, CACHE / name, silkscreen=silk.value,
                                                 source=src.value):
                notify(w, type="warning", multi_line=True, close_button=True)
        except kigit.KigitError as e:
            status.text = ""
            notify(str(e), type="negative", multi_line=True, close_button=True)
            return
        label = lambda b: Path(b).parent.name or Path(b).name
        status.text = f"{label(old_board)} ↔ {label(new_board)} (no git) · {time.monotonic() - started:.1f} s"
        logs.log.info("compared files in %.2f s", time.monotonic() - started)
        show_page(name)
        no_comparison()  # two folders: no git, so no 3D dock
        panel.close()

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


# Probe for a native window, run in a separate Python: pywebview picks its
# backend (Edge WebView2 on Windows, GTK or Qt on Linux) and fails if there is
# none. Run here, a failure would take the GUI down with it.
_NATIVE_PROBE = """
import importlib, sys
g = importlib.import_module("webview.guilib")  # (webview.guilib the attribute is None until started)
lib = g.initialize() or getattr(g, "guilib", None)
if getattr(lib, "renderer", "") == "mshtml":
    sys.exit("Microsoft Edge WebView2 isn't installed (https://go.microsoft.com/fwlink/p/?LinkId=2124703)")
"""


def native_problem() -> str | None:
    """Why the GUI can't open in its own window here, or None if it can."""
    try:
        import webview  # noqa: F401
    except ImportError:
        return "pywebview isn't installed"
    try:
        r = subprocess.run([sys.executable, "-c", _NATIVE_PROBE], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"checking for a window system failed ({e})"
    if r.returncode != 0:
        lines = [line for line in r.stderr.strip().splitlines() if line.strip()]
        if not lines:
            return f"window system check exited with {r.returncode}"
        # "webview.errors.WebViewException: You must have ..." -> the message only
        return lines[-1].split(": ", 1)[-1] if "Error" in lines[-1] or "Exception" in lines[-1] else lines[-1]
    return None


def choose_window(mode: str, platform: str = sys.platform, problem=native_problem) -> tuple[bool, str | None]:
    """Native window or browser tab: (native, why not native if it was wanted).

    mode is "native", "browser" or "auto" (native on Windows, browser elsewhere).
    Native falls back to the browser when it can't work here.
    """
    if mode == "browser" or (mode == "auto" and platform != "win32"):
        return False, None
    why = problem()
    return (why is None), why


DEFAULT_PORT = 8765
PORT_TRIES = 50  # how far past the default to look for a free port


def port_free(port: int) -> bool:
    """True if nothing is listening on 127.0.0.1:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Elsewhere SO_REUSEADDR only skips ports left in TIME_WAIT (the
        # server sets it too); on Windows it would take over a port in use.
        if sys.platform != "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(wanted: int | None, free=port_free) -> int:
    """The port to serve on: `wanted` (--port) if it's free, else an error;
    without --port, the default or the next free one after it, so several
    kigit GUIs can run at once."""
    if wanted is not None:
        if not 1 <= wanted <= 65535:
            raise SystemExit(f"kigit gui: --port must be between 1 and 65535, not {wanted}")
        if not free(wanted):
            raise SystemExit(f"kigit gui: port {wanted} is in use (another kigit gui?). "
                             f"Pick another with --port, or leave --port out to use a free one.")
        return wanted
    for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_TRIES):
        if free(port):
            return port
    raise SystemExit(f"kigit gui: ports {DEFAULT_PORT}-{DEFAULT_PORT + PORT_TRIES - 1} are all in use; "
                     f"pick one with --port")


def main() -> None:
    import multiprocessing

    # The native window runs in a child process that re-imports this module;
    # only the main process runs the app.
    if multiprocessing.current_process().name != "MainProcess":
        return
    parser = argparse.ArgumentParser(prog="kigit gui", description="kigit desktop GUI")
    parser.add_argument("project", nargs="?", default=".", help="KiCad project folder (default: current folder)")
    parser.add_argument("--port", type=int, default=None,
                        help=f"local port (default {DEFAULT_PORT}, or the next free one if another kigit gui has it)")
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--native", dest="window", action="store_const", const="native",
                        help="open in its own window (default on Windows); falls back to the browser if it can't")
    window.add_argument("--browser", dest="window", action="store_const", const="browser",
                        help="open in the web browser (default on Linux)")
    parser.set_defaults(window="auto")
    parser.add_argument("--no-browser", action="store_true",
                        help="don't open anything; just serve at http://127.0.0.1:PORT")
    parser.add_argument("--log-dir", help="folder for the session log (default: $KIGIT_LOG_DIR, else the app data folder)")
    parser.add_argument("--no-log", action="store_true", help="don't write a session log file")
    parser.add_argument("-V", "--verbose", action="store_true", help="include debug lines in the log")
    args = parser.parse_args()
    port = pick_port(args.port)
    os.environ["KIGIT_PROJECT"] = str(Path(args.project).expanduser().resolve())
    log_file = logs.start(args.log_dir, enabled=not args.no_log, debug=args.verbose)
    logs.log.info("session start: kigit gui | project %s | log %s", os.environ["KIGIT_PROJECT"], log_file or "(none)")
    # Say where it is, especially when the default port was taken.
    taken = f" ({DEFAULT_PORT} is in use)" if args.port is None and port != DEFAULT_PORT else ""
    print(f"kigit gui: http://127.0.0.1:{port}{taken}", file=sys.stderr, flush=True)
    logs.log.info("port %d%s", port, taken)
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

    native = False
    if not args.no_browser:
        native, why = choose_window(args.window)
        if why:
            logs.log.warning("can't open kigit in its own window (%s); using the browser instead", why)
    logs.log.info("opening in %s", "its own window" if native else
                  f"the browser at http://127.0.0.1:{port}" if not args.no_browser else
                  f"nothing (serving at http://127.0.0.1:{port})")
    # Native: closing the window quits kigit.
    window_args = {"native": True, "window_size": (1400, 900)} if native else {"show": not args.no_browser}
    try:
        # 127.0.0.1: reachable from this computer only (the GUI can browse
        # folders and run kigit; it must not be open to the network).
        ui.run(title="kigit", host="127.0.0.1", port=port, reload=False, dark=True,
               timeout_graceful_shutdown=2,
               favicon="🦉", show_welcome_message=False, **window_args)
    except KeyboardInterrupt:
        # Ctrl+C: the server has shut down already; no traceback.
        logs.log.info("stopped (Ctrl+C)")


if __name__ in {"__main__", "__mp_main__"}:
    main()
