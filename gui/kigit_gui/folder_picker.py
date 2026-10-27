"""A folder browser dialog.

The GUI runs in a browser, which can't hand us a local folder path, but the
app itself runs on this machine, so it can list folders directly. Folders
that hold KiCad files are marked so they're easy to spot.
"""

from __future__ import annotations

import os
from pathlib import Path

from nicegui import ui

KICAD_EXTS = (".kicad_pro", ".kicad_pcb")


def _has_kicad(path: Path) -> bool:
    try:
        with os.scandir(path) as it:
            return any(e.is_file() and e.name.endswith(KICAD_EXTS) for e in it)
    except OSError:
        return False


class FolderPicker(ui.dialog):
    """`path = await FolderPicker(start)` -> chosen folder, or None if cancelled."""

    def __init__(self, start: str) -> None:
        super().__init__()
        p = Path(start).expanduser()
        self.path = p if p.is_dir() else Path.home()
        self.show_hidden = False
        with self, ui.card().classes("w-[40rem] max-w-full p-4 gap-2 bg-[#161a20]"):
            ui.label("Choose a KiCad project folder").classes("text-base font-semibold")
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                ui.button(icon="arrow_upward", on_click=self._up).props("flat dense round").tooltip("Parent folder")
                ui.button(icon="home", on_click=lambda: self._go(Path.home())).props("flat dense round").tooltip(
                    "Home")
                self.path_input = ui.input().props("dense dark outlined").classes("flex-grow")
                self.path_input.on("keydown.enter", lambda: self._go(Path(self.path_input.value).expanduser()))
            with ui.row().classes("w-full items-center"):
                ui.label("Folders with KiCad files are marked").classes("text-xs text-gray-400")
                ui.space()
                ui.checkbox("Hidden folders", on_change=self._toggle_hidden).props("dense dark")
            self.listing = ui.column().classes("w-full h-[22rem] overflow-y-auto gap-0 border border-[#29303a] rounded")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: self.submit(None)).props("flat")
                ui.button("Open this folder", on_click=lambda: self.submit(str(self.path))).props(
                    "unelevated color=amber-8")
        self._render()

    def _go(self, path: Path) -> None:
        if path.is_dir():
            self.path = path.resolve()
        else:
            ui.notify(f"{path} isn't a folder", type="warning")
        self._render()

    def _up(self) -> None:
        self._go(self.path.parent)

    def _toggle_hidden(self, e) -> None:
        self.show_hidden = e.value
        self._render()

    def _render(self) -> None:
        self.path_input.value = str(self.path)
        self.listing.clear()
        try:
            dirs = sorted((d for d in self.path.iterdir() if d.is_dir()), key=lambda d: d.name.lower())
        except OSError as e:
            with self.listing:
                ui.label(f"Can't read this folder: {e.strerror}").classes("p-3 text-red-400")
            return
        if not self.show_hidden:
            dirs = [d for d in dirs if not d.name.startswith(".")]
        with self.listing:
            if _has_kicad(self.path):
                ui.label("This folder has KiCad files.").classes("px-3 py-2 text-amber-400 text-sm")
            if not dirs:
                ui.label("No sub-folders").classes("p-3 text-gray-500")
            for d in dirs:
                with ui.row().classes(
                        "w-full items-center gap-2 px-3 py-1 cursor-pointer hover:bg-[#1c2128] no-wrap").on(
                        "click", lambda d=d: self._go(d)):
                    ui.icon("folder").classes("text-gray-400")
                    ui.label(d.name).classes("flex-grow truncate")
                    if _has_kicad(d):
                        ui.badge("KiCad", color="amber-8").props("outline")
