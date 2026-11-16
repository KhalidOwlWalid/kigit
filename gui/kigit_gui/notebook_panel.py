"""The Notebook panel (notebook.py's notes): a window on the right that
doesn't block the viewer, so you can pin parts while you write.

Top to bottom: what's pinned in the viewer and the notes about it; a search
box; your folders and notes (as deep as they go); the open note, saved as
you type (no Write). N anywhere (outside a text box) jots a new note about
what's pinned.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Awaitable, Callable

from nicegui import background_tasks, ui

from . import activity, logs, notebook
from .md_editor import Editors
from .review import Anchor
from .review_panel import chip_text, project_key

SAVE_AFTER = 0.8  # seconds of no typing before it's written


class NotebookPanel:
    """project(): the project folder (or None); pinned(): what's pinned in the
    viewer; head(): the commit you're on; focus(anchor) shows a pin in the
    open comparison and says if it found it; compare(old, new, anchor)
    opens the comparison a pin came from; counted(n): notes about what's
    pinned (the header badge)."""

    def __init__(self, project: Callable[[], Path | None], editors: Editors,
                 pinned: Callable[[], Anchor | None], head: Callable[[], str],
                 focus: Callable[[Anchor], bool], compare: Callable[[str, str, Anchor], Awaitable[None]],
                 counted: Callable[[int], None]) -> None:
        self.project_cb, self.editors, self.pinned_cb, self.head = project, editors, pinned, head
        self.focus_cb, self.compare_cb, self.counted = focus, compare, counted
        self.folder: Path | None = None   # where new notes and the log go
        self.note: notebook.Note | None = None
        self.query = ""
        self.dirty_at = 0.0               # when the open note was last changed, unwritten
        self.saved = ""
        self.status = None                # the open note's "Saved 12:03"
        self.dialog = None
        ui.timer(0.4, self._autosave)
        # N (outside a text box): a new note about what's pinned.
        ui.add_body_html("""<script>
document.addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() !== "n" || e.ctrlKey || e.metaKey || e.altKey) return;
  const t = e.target;
  if (t && (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName))) return;
  e.preventDefault();
  emitEvent("kigit_quick_note");
});
</script>""")
        ui.on("kigit_quick_note", lambda: self.quick_note())

    @property
    def project(self) -> Path | None:
        return self.project_cb()

    # --------------------------------------------------------------- window
    def show(self) -> None:
        if not self.project:
            ui.notify("Open a project first", type="warning")
            return
        if self.dialog is None or self.dialog.is_deleted:
            # Seamless: the viewer behind it still takes clicks (pin a part, then pin it here).
            with ui.dialog().props("seamless position=right") as self.dialog, ui.card().classes(
                    "bg-[#161a20] gap-2 no-wrap p-3").style(
                    "width: min(36rem, 94vw); height: calc(100vh - 64px); max-height: calc(100vh - 64px); "
                    "margin-top: 56px").mark(
                    "notebook"):
                self.view()
        self.view.refresh()
        self.dialog.open()

    def close(self) -> None:
        self._save()
        if self.dialog is not None:
            self.dialog.close()

    @ui.refreshable_method
    def view(self) -> None:
        with ui.row().classes("w-full items-center gap-1 no-wrap"):
            ui.icon("menu_book").classes("text-amber-500")
            ui.label("Notebook").classes("text-base font-semibold")
            ui.label(self._where()).classes("text-xs text-gray-500 truncate")
            ui.space()
            ui.button(icon="today", on_click=self.log_dialog).props("flat dense round size=sm").tooltip(
                "Today's log: add a line to Logs.md, under today's date").mark("notebook-log")
            ui.button(icon="note_add", on_click=lambda: self.new_note()).props("flat dense round size=sm").tooltip(
                "New note (N anywhere: a note about what's pinned)").mark("notebook-new")
            ui.button(icon="create_new_folder", on_click=self.new_folder).props("flat dense round size=sm").tooltip(
                "New folder").mark("notebook-new-folder")
            ui.button(icon="close", on_click=self.close).props("flat dense round size=sm")
        self.about_view()
        ui.input(placeholder="Search your notes", value=self.query,
                 on_change=lambda e: self._search(e.value or "")).props(
            "dark dense outlined clearable debounce=250").classes("w-full").mark("notebook-search")
        with ui.scroll_area().classes("w-full rounded bg-[#11151a]").style("height: 30%; min-height: 8rem"):
            self.list_view()
        self.note_view()

    def _where(self) -> str:
        if not self.project:
            return ""
        root = notebook.root(self.project)
        f = self.folder or root
        rel = f.relative_to(root).as_posix() if f != root else ""
        return f"reviews/{rel}" if rel else "reviews/"

    # ------------------------------------------------- notes about the pinned
    @ui.refreshable_method
    def about_view(self) -> None:
        pinned = self.pinned_cb()
        if not pinned or not self.project:
            return
        found = notebook.about(self.project, pinned)
        with ui.column().classes("w-full gap-1 rounded bg-[#2a2416] px-2 py-1").mark("notebook-about"):
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                ui.icon("push_pin", size="xs").classes("text-amber-500")
                ui.label(f"{chip_text(pinned)}: " + (f"{len(found)} note{'s' if len(found) != 1 else ''}"
                                                     if found else "no notes yet")).classes("text-xs flex-grow")
                if self.note is not None:
                    ui.button("Pin it here", icon="add_location_alt", on_click=self.pin_selected).props(
                        "flat dense no-caps size=sm color=amber-5").mark("notebook-pin")
                ui.button("New note", icon="note_add", on_click=lambda: self.new_note(about=pinned)).props(
                    "flat dense no-caps size=sm color=amber-5").mark("notebook-new-about")
            for n, why in found[:6]:
                with ui.row().classes("w-full items-center gap-2 no-wrap cursor-pointer hover:text-amber-300").on(
                        "click", lambda n=n: self.open(n.path)).mark("notebook-about-note"):
                    ui.icon("push_pin" if why == "pinned" else "format_quote", size="xs").classes("text-gray-500")
                    ui.label(n.title).classes("text-sm truncate")
                    ui.label(self._rel(n.path.parent)).classes("text-xs text-gray-500 truncate")

    def set_pinned(self, _anchor: Anchor | None = None) -> None:
        """The viewer's pin changed: the notes about it, and the header's count."""
        pinned = self.pinned_cb()
        n = len(notebook.about(self.project, pinned)) if pinned and self.project else 0
        self.counted(n)
        if self.dialog is not None and not self.dialog.is_deleted and self.dialog.value:
            self.about_view.refresh()

    # ---------------------------------------------------------------- tree
    @ui.refreshable_method
    def list_view(self) -> None:
        if not self.project:
            return
        if self.query.strip():
            found = notebook.search(self.project, self.query)
            if not found:
                ui.label("Nothing matches.").classes("text-xs text-gray-500 italic p-2")
            for n in found:
                with ui.row().classes("w-full items-center gap-2 no-wrap px-2 py-1 cursor-pointer "
                                      "hover:bg-[#1c2128]").on("click", lambda n=n: self.open(n.path)).mark(
                        "notebook-result"):
                    ui.icon("description", size="xs").classes("text-gray-400")
                    ui.label(n.title).classes("text-sm truncate")
                    ui.label(self._rel(n.path.parent)).classes("text-xs text-gray-500 truncate")
            return
        root = notebook.root(self.project)
        tree = notebook.tree(self.project)

        def nodes(f: notebook.Folder) -> list[dict]:
            out = [{"id": str(sub.path), "label": sub.path.name, "icon": "folder", "children": nodes(sub)}
                   for sub in f.folders]
            out += [{"id": str(p), "label": p.stem, "icon": "description"} for p in f.notes]
            return out

        items = nodes(tree)
        if not items:
            ui.label("No notes yet. Make one with the note button, or press N.").classes(
                "text-xs text-gray-500 italic p-2")
            return
        t = ui.tree(items, label_key="label", on_select=lambda e: self._picked(e.value)).props(
            "dense dark no-transition selected-color=amber-5").classes("w-full text-sm").mark("notebook-tree")
        if self.note is not None:
            t._props["selected"] = str(self.note.path)  # noqa: SLF001  (a path could hold quotes)
            t.expand([str(p) for p in self.note.path.parents if root in p.parents or p == root])
        elif self.folder is not None:
            t.expand([str(p) for p in [self.folder, *self.folder.parents] if root in p.parents])
        else:
            t.expand()  # nothing open yet: show it all

    def _picked(self, value) -> None:
        if not value:
            return
        p = Path(value)
        if p.is_dir():
            self.folder = p
            self.view.refresh()
        elif p.is_file():
            self.open(p)

    def _search(self, q: str) -> None:
        self.query = q
        self.list_view.refresh()

    def _rel(self, p: Path) -> str:
        root = notebook.root(self.project)
        return p.relative_to(root).as_posix() if p != root and root in p.parents else ""

    # ---------------------------------------------------------------- note
    def open(self, path: Path) -> None:
        self._save()
        try:
            self.note = notebook.read(path)
        except (OSError, UnicodeDecodeError) as e:
            ui.notify(f"Couldn't read {path.name}: {e}", type="warning")
            return
        self.folder = path.parent
        self.saved = ""
        logs.log.info("notebook: opened %s", path)
        if self.dialog is None or self.dialog.is_deleted or not self.dialog.value:
            self.show()
        else:
            self.view.refresh()

    @ui.refreshable_method
    def note_view(self) -> None:
        n = self.note
        if n is None:
            with ui.column().classes("w-full items-center justify-center flex-grow gap-1 text-gray-500"):
                ui.icon("edit_note").classes("text-4xl")
                ui.label("Pick a note, or make one.").classes("text-sm")
                ui.label("Pin a part in the viewer to see the notes about it.").classes("text-xs")
            return
        with ui.column().classes("w-full flex-grow gap-1 min-h-0"):
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                title = ui.input(value=n.title).props("dark dense borderless").classes(
                    "flex-grow text-base font-semibold").mark("notebook-title")
                title.on("blur", lambda: self._rename(title.value))
                title.on("keydown.enter", lambda: self._rename(title.value))
                self.status = ui.label(self.saved).classes("text-xs text-gray-500 whitespace-nowrap").mark(
                    "notebook-status")
            ui.label(self._rel(n.path) or n.path.name).classes("text-xs text-gray-500 font-mono")
            with ui.row().classes("w-full items-center gap-1"):
                for i, a in enumerate(n.pins):
                    ui.chip(chip_text(a), icon="my_location", removable=True,
                            on_click=lambda a=a: self.go_to(a)).props(
                        "dense outline color=amber-5 clickable").classes("text-xs").on(
                        "remove", lambda i=i: self._unpin(i)).tooltip(
                        "Show it" + (f". {a.where}" if a.where else "")).mark("notebook-pin-chip")
                if not n.pins:
                    ui.label("Not pinned to anything: pin a part in the viewer, then Pin it here.").classes(
                        "text-xs text-gray-500")
            with ui.scroll_area().classes("w-full flex-grow"):
                self.editors.editor(n.text, self._typed, "Write anything. Markdown; [[links]] and pictures work.",
                                    "notebook-text", project_key(self.project))

    def _typed(self, text: str) -> None:
        if self.note is not None and text != self.note.text:
            self.note.text = text
            self.dirty_at = time.monotonic()
            if self.status is not None and not self.status.is_deleted:
                self.status.text = "Not saved yet"

    def _autosave(self) -> None:
        if self.dirty_at and time.monotonic() - self.dirty_at > SAVE_AFTER:
            self._save()

    def _save(self) -> None:
        if not self.dirty_at or self.note is None:
            return
        self.dirty_at = 0.0
        try:
            notebook.write(self.note)
        except OSError as e:
            ui.notify(f"Couldn't save {self.note.path.name}: {e}", type="warning")
            return
        self.saved = f"Saved {time.strftime('%H:%M')}"
        if self.status is not None and not self.status.is_deleted:
            self.status.text = self.saved

    def _rename(self, title: str) -> None:
        if self.note is None or not (title or "").strip() or title.strip() == self.note.title:
            return
        self._save()
        try:
            notebook.rename(self.note, title)
        except OSError as e:
            ui.notify(f"Couldn't rename it: {e}", type="warning")
            return
        self.view.refresh()

    # ---------------------------------------------------------------- pins
    def pin_selected(self) -> None:
        pinned = self.pinned_cb()
        if self.note is None or pinned is None:
            ui.notify("Click a part, net or footprint in the viewer first")
            return
        if any(notebook.same_component(pinned, a) for a in self.note.pins):
            ui.notify(f"Already pinned: {chip_text(pinned)}")
            return
        self.note.pins.append(pinned)
        self.dirty_at = time.monotonic() - SAVE_AFTER  # now
        self._save()
        self.view.refresh()
        self.set_pinned()

    def _unpin(self, i: int) -> None:
        if self.note is not None and 0 <= i < len(self.note.pins):
            del self.note.pins[i]
            self.dirty_at = time.monotonic() - SAVE_AFTER
            self._save()
            self.view.refresh()
            self.set_pinned()

    def go_to(self, a: Anchor) -> None:
        """Show a pin: in the comparison on screen, else the one it came from."""
        if self.focus_cb(a):
            return
        if a.seen:
            background_tasks.create(self.compare_cb(a.seen.old or "LOCAL", a.seen.new or "LOCAL", a))
        else:
            ui.notify(f"Open a comparison with {a.label} in it to see it", type="info")

    # ------------------------------------------------------------ new things
    def new_note(self, about: Anchor | None = None) -> None:
        if not self.project:
            ui.notify("Open a project first", type="warning")
            return
        self._save()
        folder = self.folder or notebook.root(self.project)
        title = f"About {about.name}" if about else time.strftime("Note %Y-%m-%d %H%M")
        n = notebook.new_note(folder, title, [about] if about else [])
        activity.record("note")
        logs.log.info("notebook: new note %s", n.path)
        self.open(n.path)
        self.set_pinned()

    def quick_note(self) -> None:
        """N: a new note about what's pinned (or a plain one)."""
        self.new_note(about=self.pinned_cb())

    async def new_folder(self) -> None:
        if not self.project:
            return
        parent = self.folder or notebook.root(self.project)
        with ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2 w-[24rem]"):
            ui.label(f"New folder in {self._rel(parent) or 'reviews/'}").classes("text-sm font-semibold")
            name = ui.input(placeholder="Folder name").props("dark dense outlined autofocus").classes("w-full").mark(
                "notebook-folder-name")
            name.on("keydown.enter", lambda: dialog.submit(name.value))
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
                ui.button("Make it", on_click=lambda: dialog.submit(name.value)).props(
                    "unelevated color=amber-8").mark("notebook-folder-go")
        dialog.open()
        got = await dialog
        dialog.delete()
        if got and got.strip():
            self.folder = notebook.new_folder(parent, got.strip())
            self.view.refresh()

    async def log_dialog(self) -> None:
        if not self.project:
            return
        folder = self.folder or notebook.root(self.project)
        pinned = self.pinned_cb()
        with ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2 w-[30rem]"):
            ui.label("Today's log").classes("text-sm font-semibold")
            ui.label(f"Added to {self._rel(folder / notebook.LOG) or notebook.LOG}, under today's date"
                     + (f", about {chip_text(pinned)}" if pinned else "") + ".").classes("text-xs text-gray-400")
            line = ui.input(placeholder="What did you do or find?").props("dark dense outlined autofocus").classes(
                "w-full").mark("notebook-log-line")
            line.on("keydown.enter", lambda: dialog.submit(line.value))
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
                ui.button("Add", icon="add", on_click=lambda: dialog.submit(line.value)).props(
                    "unelevated color=amber-8").mark("notebook-log-add")
        dialog.open()
        got = await dialog
        dialog.delete()
        if not got or not got.strip():
            return
        path = notebook.log(folder, got, pinned=pinned, commit=self.head())
        activity.record("note")
        ui.notify(f"Added to {path.name}", type="positive")
        if self.note is not None and self.note.path == path:
            self.note = notebook.read(path)
        self.view.refresh()
