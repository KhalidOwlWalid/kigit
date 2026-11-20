"""The Notebook panel (notebook.py's notes): a window on the right that
doesn't block the viewer, so you can pin parts while you write.

Top to bottom: what's pinned in the viewer and the notes about it; a search
box; your folders and notes (as deep as they go); the open note, saved as
you type (no Write). N anywhere (outside a text box) jots a new note about
what's pinned.

On the BOM page (bom=<job key>): the line picked there (+ Notes, or a row
clicked) and the notes about its parts come first, with New note about
this line, Pin this line and + Commit. It talks to the BOM page through a
BroadcastChannel("kigit-bom"), whether it's the page's Notes pane (an
iframe, compact) or a tab of its own.
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
    current: "NotebookPanel | None" = None

    """project(): the project folder (or None); pinned(): what's pinned in the
    viewer; head(): the commit you're on; focus(anchor) shows a pin in the
    open comparison and says if it found it; compare(old, new, anchor)
    opens the comparison a pin came from; counted(n): notes about what's
    pinned (the header badge)."""

    def __init__(self, project: Callable[[], Path | None], editors: Editors,
                 pinned: Callable[[], Anchor | None], head: Callable[[], str],
                 focus: Callable[[Anchor], bool], compare: Callable[[str, str, Anchor], Awaitable[None]],
                 counted: Callable[[int], None], standalone: bool = False, bom: str = "", compact: bool = False,
                 subject: Callable[[str], str] | None = None) -> None:
        self.project_cb, self.editors, self.pinned_cb, self.head = project, editors, pinned, head
        self.standalone = standalone  # in a tab of its own (/notebook/{key}), not beside the viewer
        self.bom = bom                # the BOM page's job key: notes about its lines
        self.compact = compact        # narrow (the BOM page's Notes pane): one column
        self.subject = subject or (lambda h: "")
        self.bom_line: dict | None = None  # the BOM line picked: {key, refs, value, mpn, manufacturer, footprint}
        self.focus_cb, self.compare_cb, self.counted = focus, compare, counted
        self.folder: Path | None = None   # where new notes and the log go
        self.note: notebook.Note | None = None
        self.query = ""
        self.dirty_at = 0.0               # when the open note was last changed, unwritten
        self.saved = ""
        self.status = None                # the open note's "Saved 12:03"
        self.dialog = None
        # Its own dialogs live here, not inside the row whose menu opened
        # them (the list is redrawn, and would take them with it).
        self.host = ui.element("div")
        NotebookPanel.current = self  # the page's (for tests)
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
        # Between kigit's tab and a Notebook in a tab of its own (same browser):
        # kigit's tab says what's pinned; the Notebook's asks it to show a pin.
        ui.add_body_html("""<script>
window.kigitNotebook = new BroadcastChannel("kigit-notebook");
window.kigitNotebook.onmessage = (e) => emitEvent("kigit_nb_message", e.data);
</script>""")
        ui.on("kigit_nb_message", self._message)
        # A commit hash clicked in a rendered note (#commit= links): show that commit.
        ui.on("kigit_open_commit", lambda e: self.open_commit(str(e.args or "")))
        self.remote_pinned: Anchor | None = None  # in a tab of its own: what kigit's tab has pinned
        self.client = ui.context.client  # its page (messages go out from here, whatever's open)
        if bom:
            ui.add_body_html("""<script>
window.kigitBomNotes = new BroadcastChannel("kigit-bom");
window.kigitBomNotes.onmessage = (e) => emitEvent("kigit_bom_message", e.data);
</script>""")
            ui.on("kigit_bom_message", self._bom_message)

    @property
    def project(self) -> Path | None:
        return self.project_cb()

    @property
    def key(self) -> str:
        return project_key(self.project) if self.project else ""

    def _post(self, message: dict) -> None:
        import json
        self.client.run_javascript(f"window.kigitNotebook && window.kigitNotebook.postMessage({json.dumps(message)})")

    def _message(self, e) -> None:
        m = e.args if isinstance(e.args, dict) else {}
        if not self.project or m.get("key") != self.key:
            return  # another project's
        kind = m.get("type")
        if self.standalone and kind == "pinned":
            self.remote_pinned = Anchor.from_dict(m.get("anchor"))
            self.set_pinned()
        elif not self.standalone and kind == "go":
            a = Anchor.from_dict(m.get("anchor"))
            if a:
                self.go_to(a)
        elif not self.standalone and kind == "hello":
            self.tell_pinned()
        elif not self.standalone and kind == "commit":
            self.open_commit(str(m.get("hash", "")))

    # ------------------------------------------------------------- BOM lines
    def _bom_post(self, message: dict) -> None:
        import json
        message = {**message, "job": self.bom}
        self.client.run_javascript(f"window.kigitBomNotes && window.kigitBomNotes.postMessage({json.dumps(message)})")

    def _bom_message(self, e) -> None:
        m = e.args if isinstance(e.args, dict) else {}
        if m.get("job") != self.bom or m.get("type") != "line":
            return
        line = m.get("line") if isinstance(m.get("line"), dict) else None
        self.bom_line = line
        if line and m.get("open"):  # + Notes: its newest note, if it has one
            found = notebook.notes_for_parts(self.project, line.get("refs", [])) if self.project else []
            if found and (self.note is None or self.note.path not in [n.path for n in found]):
                self.open(found[0].path)
        self.bom_view.refresh()

    def hello_bom(self) -> None:
        """Ask the BOM page which line is picked (on load)."""
        self._bom_post({"type": "hello"})

    def _line_refs(self) -> list[str]:
        return [r for r in (self.bom_line or {}).get("refs", []) if isinstance(r, str)]

    @ui.refreshable_method
    def bom_view(self) -> None:
        if not self.bom or not self.project:
            return
        line = self.bom_line
        with ui.column().classes("w-full gap-1 rounded bg-[#1d2620] px-2 py-1").mark("bom-notes-line"):
            if not line:
                with ui.row().classes("w-full items-center gap-1 no-wrap"):
                    ui.icon("receipt_long", size="xs").classes("text-emerald-400")
                    ui.label("Press + Notes on a BOM line (or click a line) to see its notes here.").classes(
                        "text-xs text-gray-400 flex-grow")
                    self._commit_button()
                return
            refs = self._line_refs()
            found = notebook.notes_for_parts(self.project, refs)
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                ui.icon("receipt_long", size="xs").classes("text-emerald-400")
                ui.label(f"{line.get('value', '')} · {', '.join(refs)}").classes(
                    "text-xs font-semibold truncate").tooltip(", ".join(refs)).mark("bom-notes-refs")
                ui.label(f"{len(found)} note{'s' if len(found) != 1 else ''}" if found else "no notes yet").classes(
                    "text-xs text-gray-400 whitespace-nowrap")
                ui.space()
                if self.note is not None:
                    ui.button("Pin this line", icon="add_location_alt", on_click=self.pin_line).props(
                        "flat dense no-caps size=sm color=green-4").tooltip(
                        "Pin this line's parts to the open note").mark("bom-notes-pin-line")
                self._commit_button()
                ui.button("New note", icon="note_add", on_click=self.new_bom_note).props(
                    "flat dense no-caps size=sm color=green-4").tooltip(
                    "A note about this line, in reviews/BOM/, pinned to its parts").mark("bom-notes-new")
            if mpn := line.get("mpn"):
                ui.label(f"{line.get('manufacturer', '')} {mpn}".strip()).classes("text-xs text-gray-400 font-mono")
            for n in found[:6]:
                current = self.note is not None and self.note.path == n.path
                with ui.row().classes("w-full items-center gap-2 no-wrap cursor-pointer hover:text-emerald-300 " +
                                      ("text-emerald-300" if current else "")).on(
                        "click", lambda n=n: self.open(n.path)).mark("bom-notes-note"):
                    ui.icon("description", size="xs").classes("text-gray-500")
                    ui.label(n.title).classes("text-sm truncate")
                    ui.label(self._rel(n.path.parent)).classes("text-xs text-gray-500 truncate")

    def _commit_button(self) -> None:
        if self.note is not None:
            ui.button("Commit", icon="commit", on_click=self.commit_dialog).props(
                "flat dense no-caps size=sm color=grey-5").tooltip(
                "Add a commit to the note (when it was chosen, changed...)").mark("bom-notes-commit")

    def new_bom_note(self) -> None:
        if not self.project or not self.bom_line:
            return
        self._save()
        head = self.head()
        n = notebook.bom_note(self.project, self.bom_line, head, self.subject(head) if head else "")
        activity.record("note")
        logs.log.info("notebook: new BOM note %s", n.path)
        self.open(n.path)
        self.set_pinned()

    def pin_line(self) -> None:
        if self.note is None or not self.bom_line:
            return
        added = [a for a in notebook.part_anchors(self._line_refs(), self.head())
                 if not any(notebook.same_component(a, b) for b in self.note.pins)]
        if not added:
            ui.notify("This line's parts are pinned already")
            return
        self.note.pins.extend(added)
        self.dirty_at = time.monotonic() - SAVE_AFTER
        self._save()
        self.view.refresh()
        self.set_pinned()

    async def commit_dialog(self) -> None:
        """Pick a commit; a line for it goes at the end of the note."""
        from . import kigit
        if self.note is None or not self.project:
            return
        try:
            hist = await kigit.history(str(self.project), max_count=60)
        except kigit.KigitError as e:
            ui.notify(f"Couldn't read the history: {e}", type="warning")
            return
        with self.host, ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-1 w-[34rem]").mark("bom-notes-commits"):
            ui.label("Add a commit to the note").classes("text-sm font-semibold")
            ui.label("A line with its short hash, date and subject goes at the end.").classes("text-xs text-gray-500")
            with ui.scroll_area().classes("w-full").style("height: 22rem"):
                for c in hist.commits:
                    with ui.row().classes("w-full items-center gap-2 no-wrap px-1 py-0.5 cursor-pointer rounded "
                                          "hover:bg-[#1c2128]").on("click", lambda c=c: dialog.submit(c)).mark(
                            "bom-notes-commit-row"):
                        ui.label(c.short).classes("font-mono text-xs text-amber-400")
                        ui.label(c.date[:10]).classes("text-xs text-gray-500")
                        ui.label(c.subject).classes("text-sm truncate")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
        dialog.open()
        c = await dialog
        dialog.delete()
        if c is None or self.note is None:
            return
        self.note.text = self.note.text.rstrip("\n") + "\n\n- Commit " + notebook.commit_ref(c.hash, c.subject, c.date) + "\n"
        self.dirty_at = time.monotonic() - SAVE_AFTER
        self._save()
        self.view.refresh()

    def open_commit(self, rev: str) -> None:
        """A commit from a note: its changes (its parent against it) in the
        viewer; the first commit against the working tree. In a tab of its
        own (or the BOM page's Notes pane), kigit's tab shows it."""
        if not self.project:
            return
        full = notebook.resolve_commit(self.project, rev)
        if not full:
            ui.notify(f"{rev[:12]} isn't a commit in this repository (not pulled yet?)", type="warning")
            return
        if self.standalone:
            self._post({"type": "commit", "key": self.key, "hash": full})
            ui.notify(f"Showing {full[:7]} in kigit's tab")
            return
        parent = notebook.commit_parent(self.project, full)
        logs.log.info("notebook: show commit %s", full[:7])
        self.close()  # the viewer is what you want to see now
        background_tasks.create(self.compare_cb(parent, full, None) if parent else self.compare_cb(full, "LOCAL", None))

    def tell_pinned(self) -> None:
        """kigit's tab: what's pinned, for a Notebook in its own tab."""
        if not self.standalone and self.project:
            a = self.pinned_cb()
            self._post({"type": "pinned", "key": self.key, "anchor": a.to_dict() if a else None})

    def open_in_tab(self) -> None:
        """The Notebook in a tab of its own; this panel closes (one copy of a note open at a time)."""
        if not self.project:
            return
        self._save()
        ui.navigate.to(f"/notebook/{self.key}", new_tab=True)
        self.close()

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
            ui.label("BOM notes" if self.bom else "Notebook").classes("text-base font-semibold")
            self.where_label = ui.label(self._where()).classes("text-xs text-gray-500 truncate")
            ui.space()
            ui.button(icon="today", on_click=self.log_dialog).props("flat dense round size=sm").tooltip(
                "Today's log: add a line to Logs.md, under today's date").mark("notebook-log")
            ui.button(icon="note_add", on_click=lambda: self.new_note()).props("flat dense round size=sm").tooltip(
                "New note (N anywhere: a note about what's pinned)").mark("notebook-new")
            ui.button(icon="create_new_folder", on_click=self.new_folder).props("flat dense round size=sm").tooltip(
                "New folder").mark("notebook-new-folder")
            if not self.standalone:
                ui.button(icon="open_in_new", on_click=self.open_in_tab).props("flat dense round size=sm").tooltip(
                    "Open the Notebook in a tab of its own (pins still come from here)").mark("notebook-tab")
                ui.button(icon="close", on_click=self.close).props("flat dense round size=sm")
        if self.standalone and not self.compact:
            # Wide: folders and notes on the left, the note on the right.
            with ui.row().classes("w-full flex-grow no-wrap gap-4 min-h-0"):
                with ui.column().classes("gap-2 min-h-0 h-full").style("width: 34%; min-width: 18rem"):
                    self.bom_view()
                    self.about_view()
                    self._search_box()
                    with ui.scroll_area().classes("w-full flex-grow rounded bg-[#11151a]"):
                        self.list_view()
                with ui.column().classes("flex-grow min-w-0 h-full gap-2"):
                    self.note_view()
            return
        self.bom_view()
        self.about_view()
        self._search_box()
        with ui.scroll_area().classes("w-full rounded bg-[#11151a]").style(
                "height: 15%; min-height: 4.5rem" if self.compact else "height: 30%; min-height: 8rem"):
            self.list_view()
        self.note_view()

    def _search_box(self) -> None:
        ui.input(placeholder="Search your notes", value=self.query,
                 on_change=lambda e: self._search(e.value or "")).props(
            "dark dense outlined clearable debounce=250").classes("w-full").mark("notebook-search")

    def _where(self) -> str:
        if not self.project:
            return ""
        root = notebook.root(self.project)
        f = self.folder or root
        rel = f.relative_to(root).as_posix() if f != root else ""
        return f"reviews/{rel}" if rel else "reviews/"

    # ------------------------------------------------- notes about the pinned
    def _pinned(self) -> Anchor | None:
        return self.remote_pinned if self.standalone else self.pinned_cb()

    @ui.refreshable_method
    def about_view(self) -> None:
        pinned = self._pinned()
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
        """The viewer's pin changed: the notes about it, the header's count,
        and a Notebook in its own tab."""
        pinned = self._pinned()
        n = len(notebook.about(self.project, pinned)) if pinned and self.project else 0
        self.counted(n)
        self.tell_pinned()
        if self.standalone or (self.dialog is not None and not self.dialog.is_deleted and self.dialog.value):
            self.about_view.refresh()
        if self.bom:
            self.bom_view.refresh()
            self._bom_post({"type": "notes"})  # the BOM page updates its + Notes counts

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
        here = self.folder if self.folder and self.folder.is_dir() and (self.folder == root or root in
                                                                        self.folder.parents) else root
        self.folder = here
        # Where you are: back up a level, and the path (each part goes there).
        with ui.row().classes("w-full items-center gap-1 no-wrap px-1 py-1 border-b border-[#29303a]"):
            ui.button(icon="arrow_upward", on_click=lambda: self.go(here.parent)).props(
                "flat dense round size=sm").tooltip("Back up a folder").mark("notebook-up").set_enabled(here != root)
            parts = [root, *reversed([p for p in here.parents if root in p.parents]), here] if here != root else [root]
            for i, p in enumerate(parts):
                if i:
                    ui.label("/").classes("text-xs text-gray-600")
                ui.label("reviews" if p == root else p.name).classes(
                    "text-xs cursor-pointer hover:text-amber-300 " + ("text-gray-200 font-semibold" if p == here
                                                                       else "text-gray-400")).on(
                    "click", lambda p=p: self.go(p)).mark("notebook-crumb")
        listing = notebook.listing(self.project, here)
        if not listing.folders and not listing.notes:
            ui.label("Nothing here yet: make a note or a folder with the buttons above, or press N.").classes(
                "text-xs text-gray-500 italic p-2")
        for sub in listing.folders:
            notes, _ = notebook.contents(sub.path)
            self._row(sub.path, "folder", sub.path.name, f"{notes} note{'s' if notes != 1 else ''}",
                      lambda p=sub.path: self.go(p))
        for p in listing.notes:
            current = self.note is not None and self.note.path == p
            self._row(p, "description", p.stem, "", lambda p=p: self.open(p), current)

    def _row(self, path: Path, icon: str, name: str, meta: str, on_click, current: bool = False) -> None:
        """A folder (click: go in) or a note (click: open), with ⋮ for rename and delete."""
        with ui.row().classes("w-full items-center gap-2 no-wrap px-2 py-0.5 cursor-pointer rounded " +
                              ("bg-[#2a2416]" if current else "hover:bg-[#1c2128]")).on("click", on_click).mark(
                "notebook-folder" if icon == "folder" else "notebook-note"):
            ui.icon(icon, size="xs").classes("text-amber-500" if icon == "folder" else "text-gray-400")
            ui.label(name).classes("text-sm truncate flex-grow")
            if meta:
                ui.label(meta).classes("text-xs text-gray-500 whitespace-nowrap")
            if icon == "folder":
                ui.icon("chevron_right", size="xs").classes("text-gray-600")
            with ui.button(icon="more_vert").props("flat dense round size=xs color=grey-6").on("click.stop", lambda: None):
                with ui.menu():
                    ui.menu_item("Rename", on_click=lambda: self.rename_dialog(path)).mark("notebook-rename")
                    ui.menu_item("Delete", on_click=lambda: self.delete_dialog(path)).mark("notebook-delete")

    def go(self, folder: Path) -> None:
        """Into a folder (or back up)."""
        self.folder = folder
        self.list_view.refresh()
        self.where_label.text = self._where()

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
        if self.standalone or not (self.dialog is None or self.dialog.is_deleted or not self.dialog.value):
            self.view.refresh()
        else:
            self.show()

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
        pinned = self._pinned()
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
        """Show a pin: in the comparison on screen, else the one it came from.
        In a tab of its own: kigit's tab shows it."""
        if self.standalone:
            self._post({"type": "go", "key": self.key, "anchor": a.to_dict()})
            ui.notify(f"Showing {chip_text(a)} in kigit's tab")
            return
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
        self.new_note(about=self._pinned())

    async def _ask_name(self, title: str, value: str) -> str | None:
        with self.host, ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2 w-[26rem]"):
            ui.label(title).classes("text-sm font-semibold")
            name = ui.input(value=value).props("dark dense outlined autofocus").classes("w-full").mark(
                "notebook-rename-input")
            name.on("keydown.enter", lambda: dialog.submit(name.value))
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
                ui.button("Rename", on_click=lambda: dialog.submit(name.value)).props(
                    "unelevated color=amber-8").mark("notebook-rename-go")
        dialog.open()
        got = await dialog
        dialog.delete()
        return (got or "").strip() or None

    async def rename_dialog(self, path: Path) -> None:
        self._save()
        if path.is_dir():
            name = await self._ask_name(f"Rename the folder {path.name}", path.name)
            if not name:
                return
            try:
                new = notebook.rename_folder(self.project, path, name)
            except (OSError, ValueError) as e:
                ui.notify(f"Couldn't rename it: {e}", type="warning")
                return
            # Anything open inside it moves with it.
            if self.note is not None and (self.note.path.parent == path or path in self.note.path.parents):
                self.note.path = new / self.note.path.relative_to(path)
            if self.folder is not None and (self.folder == path or path in self.folder.parents):
                self.folder = new / self.folder.relative_to(path)
        else:
            try:
                n = self.note if self.note is not None and self.note.path == path else notebook.read(path)
            except (OSError, UnicodeDecodeError) as e:
                ui.notify(f"Couldn't read {path.name}: {e}", type="warning")
                return
            name = await self._ask_name(f"Rename the note {n.title}", n.title)
            if not name:
                return
            try:
                notebook.rename(n, name)
            except OSError as e:
                ui.notify(f"Couldn't rename it: {e}", type="warning")
                return
        logs.log.info("notebook: renamed %s", path)
        self.view.refresh()

    async def delete_dialog(self, path: Path) -> None:
        """Asks first, saying what goes and whether git still has it."""
        self._save()
        folder = path.is_dir()
        notes, others = notebook.contents(path) if folder else (1, 0)
        loose = notebook.unsaved_in_git(self.project, path)
        with self.host, ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2 w-[30rem]"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("warning", color="red-4")
                ui.label(f"Delete {'the folder' if folder else 'the note'} {path.stem if not folder else path.name}?"
                         ).classes("text-base font-semibold")
            if folder:
                ui.label(f"Everything in it goes: {notes} note{'s' if notes != 1 else ''}"
                         + (f" and {others} other file{'s' if others != 1 else ''} (pictures, ...)" if others else "")
                         + ".").classes("text-sm text-gray-300")
            ui.label("It's deleted from disk, not moved to a bin.").classes("text-sm text-gray-300")
            if loose > 0:
                ui.label(f"{loose} file{'s have' if loose != 1 else ' has'} changes git doesn't have yet (never "
                         "committed, or edited since): those are gone for good.").classes(
                    "text-sm text-red-300").mark("notebook-delete-uncommitted")
            elif loose == 0:
                ui.label("Git has all of it, so a commit from before this can bring it back.").classes(
                    "text-xs text-gray-500")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Delete", icon="delete", on_click=lambda: dialog.submit(True)).props(
                    "unelevated color=red-8").mark("notebook-delete-go")
        dialog.open()
        sure = await dialog
        dialog.delete()
        if not sure:
            return
        try:
            notebook.delete(self.project, path)
        except (OSError, ValueError) as e:
            ui.notify(f"Couldn't delete it: {e}", type="warning")
            return
        logs.log.info("notebook: deleted %s", path)
        if self.note is not None and (self.note.path == path or path in self.note.path.parents):
            self.note, self.dirty_at = None, 0.0
        if self.folder is not None and (self.folder == path or path in self.folder.parents):
            self.folder = path.parent
        ui.notify(f"Deleted {path.name}", type="positive")
        self.view.refresh()
        self.set_pinned()

    async def new_folder(self) -> None:
        if not self.project:
            return
        parent = self.folder or notebook.root(self.project)
        with self.host, ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2 w-[24rem]"):
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
        pinned = self._pinned()
        with self.host, ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2 w-[30rem]"):
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


# ------------------------------------------------------------- its own tab
# (The page, /notebook/{key}, is registered in app.py with kigit's others.)
def notebook_page(key: str, bom: str = "", compact: bool = False) -> None:
    """The Notebook in a browser tab of its own. Pins come from kigit's tab
    (the same project, in the same browser), through a BroadcastChannel.
    bom: a BOM page's job key (its Notes pane, compact, or its own tab)."""
    import subprocess

    from . import lightbox
    from .review_panel import _PAGE_JS, _projects

    ui.dark_mode(True)
    ui.query(".nicegui-content").classes("p-0 gap-0")
    project = _projects.get(key)
    if project is None:
        ui.label("This Notebook's project isn't open in kigit: open it there, then use the Notebook's "
                 "open-in-new-tab button.").classes("p-6 text-gray-400")
        return
    ui.page_title(f"{'BOM notes' if bom else 'Notebook'} · {project.name}")

    def head() -> str:
        try:
            r = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True,
                               timeout=5)
            return r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    async def no_compare(old: str, new: str, anchor: Anchor) -> None:
        return None

    def subject(h: str) -> str:
        try:
            r = subprocess.run(["git", "-C", str(project), "log", "-1", "--format=%s", h], capture_output=True,
                               text=True, timeout=5)
            return r.stdout.strip() if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    ui.add_body_html(_PAGE_JS)  # rendered Markdown's look, links opening outside
    ui.add_body_html(lightbox.html(".kigit-md-view"))
    pad = "p-2" if compact else "p-4"
    with ui.column().classes(f"w-full {pad} gap-2 bg-[#161a20]").style("height: 100vh"):
        panel = NotebookPanel(project=lambda: project, editors=Editors(), pinned=lambda: None, head=head,
                              focus=lambda a: False, compare=no_compare, counted=lambda n: None, standalone=True,
                              bom=bom, compact=compact, subject=subject)
        panel.view()
    panel._post({"type": "hello", "key": key})  # kigit's tab: say what's pinned
    if bom:
        panel.hello_bom()  # the BOM page: say which line is picked
