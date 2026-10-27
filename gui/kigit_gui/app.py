"""kigit GUI: list the project's commits, pick two, show kigit's diff viewer.

Started by `kigit gui [PROJECT_DIR]`. All the work is done by the kigit
command line (see kigit.py); this file is only the window around it.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
import time
from pathlib import Path

from nicegui import app, ui

from . import kigit

LOCAL = "LOCAL"

# Generated pages are served from here. Commit-to-commit diffs never change,
# so they're kept for the session; anything involving LOCAL is regenerated.
CACHE = Path(tempfile.mkdtemp(prefix="kigit-gui-"))
app.add_static_files("/diffs", str(CACHE))


def page_name(project: str, old: str, new: str) -> str:
    key = hashlib.sha1(f"{project}|{old}|{new}".encode()).hexdigest()[:12]
    return f"{key}.html"


def build(project: str):
    """Builds the page for one project. Returns the coroutine function that
    (re)loads the commit history, so the caller can run it once the page is up."""
    ui.dark_mode(True)
    ui.query(".nicegui-content").classes("p-0 gap-0")
    state = {"project": project, "history": None}

    with ui.header().classes("items-center gap-4 py-2 px-4 bg-[#161a20] border-b border-[#29303a]"):
        ui.label("kigit").classes("text-lg font-bold text-[#e8b84d]")
        project_input = ui.input(value=project).props("dense dark outlined").classes("w-[28rem]")
        ui.button("Open", on_click=lambda: load(project_input.value)).props("flat dense")
        status = ui.label("").classes("text-sm text-gray-400 ml-auto")

    with ui.left_drawer(value=True, bordered=True).props("width=460").classes("bg-[#161a20] p-0"):
        with ui.column().classes("w-full p-3 gap-2"):
            ui.label("Pick two commits to compare them, or one to see what it changed.").classes(
                "text-xs text-gray-400")
            with ui.row().classes("w-full gap-2 items-center"):
                compare_btn = ui.button("Compare", on_click=lambda: compare()).props("unelevated dense color=amber-8")
                ui.button("Refresh", on_click=lambda: load(state["project"])).props("flat dense")
                ui.space()
                only = ui.switch("PCB/schematic changes only", value=True, on_change=lambda: fill()).props("dense")
            columns = [
                {"name": "short", "label": "Commit", "field": "short", "align": "left"},
                {"name": "what", "label": "", "field": "what", "align": "left"},
                {"name": "date", "label": "Date", "field": "date", "align": "left"},
                {"name": "subject", "label": "Message", "field": "subject", "align": "left",
                 "style": "white-space: normal"},
            ]
            table = ui.table(columns=columns, rows=[], row_key="hash", selection="multiple",
                             on_select=lambda e: on_select()).props(
                "dense flat dark virtual-scroll hide-bottom :rows-per-page-options=[0]").classes(
                "w-full h-[calc(100vh-150px)]")

    with ui.element("div").classes("w-full h-[calc(100vh-52px)] relative"):
        frame = ui.element("iframe").classes("w-full h-full border-0 bg-[#0f1115]")
        placeholder = ui.label("Pick commits on the left and press Compare.").classes(
            "absolute inset-0 flex items-center justify-center text-gray-500")

    def fill() -> None:
        h = state["history"]
        if not h:
            table.rows = []
            return
        rows = []
        if h.local:
            what = " ".join(k.upper() for k in ("pcb", "sch") if h.local[k])
            rows.append({"hash": LOCAL, "short": "LOCAL", "what": what, "date": "now",
                         "subject": "Uncommitted changes"})
        for c in h.commits:
            if only.value and not (c.pcb or c.sch):
                continue
            what = " ".join(k for k, on in (("PCB", c.pcb), ("SCH", c.sch)) if on)
            rows.append({"hash": c.hash, "short": c.short, "what": what, "date": c.date[:16],
                         "subject": c.subject})
        table.rows = rows
        table.selected = [r for r in table.selected if any(r["hash"] == x["hash"] for x in rows)]
        table.update()
        on_select()

    def on_select() -> None:
        # Keep at most two, the most recently clicked.
        if len(table.selected) > 2:
            table.selected = table.selected[-2:]
            table.update()
        n = len(table.selected)
        compare_btn.set_enabled(n in (1, 2))
        compare_btn.text = "Compare" if n == 2 else "Show this commit" if n == 1 else "Compare"

    async def load(path: str) -> None:
        state["project"] = path
        status.text = "Reading history..."
        try:
            state["history"] = await kigit.history(path)
        except kigit.KigitError as e:
            state["history"] = None
            status.text = ""
            ui.notify(str(e), type="negative", multi_line=True, close_button=True)
            fill()
            return
        h = state["history"]
        status.text = f"{h.board} · {len(h.commits)} commits"
        fill()

    async def compare() -> None:
        sel = table.selected
        if len(sel) == 2:
            old, new = sel[0]["hash"], sel[1]["hash"]
        elif len(sel) == 1:
            # What this commit changed: its parent -> it (LOCAL: HEAD -> working tree).
            new = sel[0]["hash"]
            old = "HEAD" if new == LOCAL else f"{new}~1"
        else:
            return
        name = page_name(state["project"], old, new)
        out = CACHE / name
        compare_btn.props("loading")
        status.text = "Comparing..."
        started = time.monotonic()
        try:
            if LOCAL in (old, new) or not out.exists():
                warnings = await kigit.diff_html(state["project"], old, new, out)
                for w in warnings:
                    ui.notify(w, type="warning", multi_line=True, close_button=True)
        except kigit.KigitError as e:
            status.text = ""
            ui.notify(str(e), type="negative", multi_line=True, close_button=True)
            return
        finally:
            compare_btn.props(remove="loading")
        def label(rev: str) -> str:  # full hashes shortened, "LOCAL"/"HEAD" as is
            base, tilde, rest = rev.partition("~")
            return (base[:7] if len(base) == 40 else base) + tilde + rest

        status.text = f"{label(old)} → {label(new)} · {time.monotonic() - started:.1f} s"
        # Cache-buster so a regenerated LOCAL page actually reloads.
        frame.props(f'src="/diffs/{name}?t={int(time.time())}"')
        placeholder.set_visibility(False)

    return load


@ui.page("/")
async def index() -> None:
    # The project folder comes from `kigit gui [PROJECT_DIR]` (see main()).
    project = os.environ.get("KIGIT_PROJECT", os.getcwd())
    load = build(project)
    await load(project)


def main() -> None:
    parser = argparse.ArgumentParser(prog="kigit gui", description="kigit desktop GUI")
    parser.add_argument("project", nargs="?", default=".", help="KiCad project folder (default: current folder)")
    parser.add_argument("--port", type=int, default=8765, help="local port (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    args = parser.parse_args()
    os.environ["KIGIT_PROJECT"] = str(Path(args.project).expanduser().resolve())
    ui.run(title="kigit", port=args.port, show=not args.no_browser, reload=False, dark=True,
           favicon="🦉", show_welcome_message=False)


if __name__ in {"__main__", "__mp_main__"}:
    main()
