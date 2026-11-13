"""The review panel: notes on why a commit changed what it changed.

Opens on the right when a single commit is reviewed (diffed against its
parent). Each note can point at what's pinned in the viewer (a net,
footprint, part or bus); clicking the note's anchor shows it again. Text is
Markdown; pasting or dropping an image stores it in reviews/assets/.

Everything is saved to `<project>/reviews/<commit>.md` (see review.py) a
moment after each edit.
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Callable

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response
from nicegui import app, ui

from . import logs, review
from .review import Anchor, Note, Review


def chip_text(a: Anchor) -> str:
    return a.label + (" · removed" if a.removed else "")

MAX_IMAGE = 50 * 1024 * 1024

# Project folders the browser may store images in and read them from, by a
# random key handed to the page (so another local web page can't use these
# routes).
_projects: dict[str, Path] = {}


def project_key(project_dir: Path) -> str:
    for key, d in _projects.items():
        if d == project_dir:
            return key
    key = secrets.token_hex(12)
    _projects[key] = project_dir
    return key


@app.post("/review-image/{key}")
async def _upload_image(key: str, request: Request) -> Response:
    project = _projects.get(key)
    if project is None:
        return JSONResponse({"error": "unknown project"}, status_code=404)
    mime = request.headers.get("content-type", "").split(";")[0].strip()
    data = await request.body()
    if not data or len(data) > MAX_IMAGE:
        return JSONResponse({"error": "empty or too large (50 MB at most)"}, status_code=400)
    try:
        path = review.save_image(project, data, mime)
    except (ValueError, OSError) as e:
        logs.log.warning("couldn't store a pasted image: %s", e)
        return JSONResponse({"error": str(e)}, status_code=400)
    logs.log.info("stored image %s/%s", review.folder(project), path)
    return JSONResponse({"path": path})


@app.get("/review-files/{key}/{name}")
async def _image(key: str, name: str) -> Response:
    project = _projects.get(key)
    if project is None or not review.ASSET_NAME.match(name):
        return Response(status_code=404)
    path = review.folder(project) / review.ASSETS / name
    return FileResponse(path) if path.is_file() else Response(status_code=404)


# Page script: paste or drop an image into a note's text box to upload it and
# insert a link to it where the cursor is; links in rendered notes open
# outside the app.
_PAGE_JS = """
<script>
(() => {
  const box = (e) => e.target.closest && e.target.closest(".kigit-md textarea");
  const image = (files) => [...(files || [])].find((f) => f.type.startsWith("image/"));
  async function upload(ta, file) {
    const key = ta.closest(".kigit-md").dataset.key;
    const r = await fetch(`/review-image/${key}`, { method: "POST", headers: { "Content-Type": file.type }, body: file });
    const j = await r.json();
    if (!r.ok) { emitEvent("kigit_image_failed", j.error || r.statusText); return; }
    ta.focus();
    const text = `![](${j.path})`;
    if (!document.execCommand("insertText", false, text)) {
      ta.setRangeText(text, ta.selectionStart, ta.selectionEnd, "end");
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }
  document.addEventListener("paste", (e) => {
    const ta = box(e), f = ta && image(e.clipboardData && e.clipboardData.files);
    if (f) { e.preventDefault(); upload(ta, f); }
  }, true);
  document.addEventListener("dragover", (e) => { if (box(e)) e.preventDefault(); }, true);
  document.addEventListener("drop", (e) => {
    const ta = box(e), f = ta && image(e.dataTransfer && e.dataTransfer.files);
    if (f) { e.preventDefault(); upload(ta, f); }
  }, true);
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest(".kigit-md-view a[href]");
    if (a) { e.preventDefault(); window.open(a.href, "_blank", "noopener"); }
  }, true);
})();
</script>
<style>
.kigit-md-view img { max-width: 100%; border-radius: 4px; }
.kigit-md-view p { margin: 0.3em 0; }
.kigit-md-view a { color: #7fb3ff; }
</style>
"""


def rewrite_images(text: str, key: str) -> str:
    """Markdown with assets/ links pointing at the GUI's image route, for preview."""
    return re.sub(r"\]\(\s*assets/", f"](/review-files/{key}/", text)


class ReviewPanel:
    """The right-hand drawer. `focus(anchor)` asks the viewer to show an
    anchor; `on_saved(commit)` is called when a review file is first created."""

    def __init__(self, focus: Callable[[Anchor], None], on_saved: Callable[[str], None]) -> None:
        self.focus_cb, self.on_saved = focus, on_saved
        self.project: Path | None = None
        self.key = ""
        self.review: Review | None = None
        self.path: Path | None = None
        self.dirty = False
        self.pinned: Anchor | None = None
        self.editing: set[str] = set()  # notes (by id) shown as text boxes; "summary" for the summary

        ui.add_body_html(_PAGE_JS)
        ui.on("kigit_image_failed", lambda e: self._warn(f"Couldn't add the image: {e.args}"))
        with ui.right_drawer(value=False, bordered=True).props("width=480").classes(
                "bg-[#161a20] p-0") as self.drawer:
            self.body = ui.column().classes("w-full p-3 gap-2")
        self.drawer.mark("review-panel")
        # Edits are written a moment later, not on every keystroke.
        ui.timer(1.0, self.flush)

    # ------------------------------------------------------------- open/close
    def open(self, project_dir: str | Path, commit: str, parent: str, subject: str) -> None:
        self.flush()
        self.project = Path(project_dir)
        self.key = project_key(self.project)
        self.path = review.all_reviews(self.project).get(commit)
        self.review = None
        if self.path:
            try:
                self.review = review.load(self.path)
            except (OSError, ValueError, UnicodeDecodeError) as e:
                self._warn(f"Couldn't read {self.path.name}: {e}")
                self.path = None
        if self.review is None:
            self.review = Review(commit=commit, parent=parent, subject=subject)
        self.editing = set() if self.review.summary or self.review.notes else {"summary"}
        logs.log.info("review %s (%s)", commit[:7], self.path or "new")
        self.render()
        self.drawer.show()

    def close(self) -> None:
        self.flush()
        self.review = None
        self.drawer.hide()

    @property
    def commit(self) -> str | None:
        return self.review.commit if self.review else None

    def set_pinned(self, anchor: Anchor | None) -> None:
        self.pinned = anchor
        if self.review:
            self.pinned_view.refresh()

    # ------------------------------------------------------------------- save
    def changed(self) -> None:
        self.dirty = True

    def flush(self) -> None:
        if not (self.dirty and self.review and self.project):
            return
        self.dirty = False
        first = self.path is None
        try:
            self.path = review.save(self.project, self.review, self.path)
        except OSError as e:
            self._warn(f"Couldn't save the review: {e}")
            return
        if first:
            logs.log.info("created review %s", self.path)
            self.path_label.text = self._path_text()
            self.on_saved(self.review.commit)

    def _warn(self, message: str) -> None:
        logs.log.warning("shown to user: %s", message)
        ui.notify(message, type="warning", multi_line=True, close_button=True)

    def _path_text(self) -> str:
        if self.path:
            return f"{review.FOLDER}/{self.path.name}"
        return f"{review.FOLDER}/{review.file_name(self.review)} (saved once you write something)"

    # ------------------------------------------------------------------ notes
    def add_note(self) -> None:
        note = Note(anchor=self.pinned)
        self.review.notes.append(note)
        self.editing.add(note.id)
        self.changed()
        self.notes_view.refresh()

    def remove_note(self, note: Note) -> None:
        self.review.notes.remove(note)
        self.changed()
        self.notes_view.refresh()

    def toggle_edit(self, key: str) -> None:
        self.editing ^= {key}
        self.flush()
        self.summary_view.refresh() if key == "summary" else self.notes_view.refresh()

    def point_at_pinned(self, note: Note) -> None:
        note.anchor = self.pinned
        self.changed()
        self.notes_view.refresh()

    def unanchor(self, note: Note) -> None:
        note.anchor = None
        self.changed()
        self.notes_view.refresh()

    # ----------------------------------------------------------------- render
    def render(self) -> None:
        r = self.review
        self.body.clear()
        with self.body:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("rate_review").classes("text-amber-500")
                ui.label("Review").classes("text-base font-semibold")
                ui.label(r.commit[:7]).classes("text-mono text-xs text-gray-400")
                ui.space()
                ui.button(icon="close", on_click=self.close).props("flat dense round").tooltip("Close the review")
            ui.label(r.subject).classes("text-sm text-gray-300")
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                self.path_label = ui.label(self._path_text()).classes("text-xs text-gray-500 truncate flex-grow")
                ui.button(icon="folder", on_click=self._open_folder).props("flat dense round size=sm").tooltip(
                    "Open the reviews folder")
            self.summary_view()
            ui.separator().classes("my-1")
            self.pinned_view()
            self.notes_view()

    def _open_folder(self) -> None:
        from .app import open_folder_in_os
        d = review.folder(self.project)
        open_folder_in_os(d if d.is_dir() else self.project)

    def _markdown_box(self, value: str, on_change: Callable[[str], None], placeholder: str, mark: str):
        """A Markdown text box that takes pasted or dropped images."""
        with ui.element("div").classes("kigit-md w-full").props(f'data-key="{self.key}"'):
            box = ui.textarea(value=value, placeholder=placeholder,
                              on_change=lambda e: (on_change(e.value or ""), self.changed())).props(
                "dark outlined autogrow dense").classes("w-full text-sm").mark(mark)
        return box

    def _markdown_view(self, text: str) -> None:
        ui.markdown(rewrite_images(text, self.key)).classes("kigit-md-view w-full text-sm text-gray-200")

    @ui.refreshable_method
    def summary_view(self) -> None:
        r = self.review
        editing = "summary" in self.editing
        with ui.row().classes("w-full items-center gap-1"):
            ui.label("Summary").classes("text-xs font-semibold text-gray-400 uppercase")
            ui.space()
            ui.button(icon="visibility" if editing else "edit", on_click=lambda: self.toggle_edit("summary")).props(
                "flat dense round size=sm").tooltip("Preview" if editing else "Edit")
        if editing:
            self._markdown_box(r.summary, lambda v: setattr(r, "summary", v),
                               "Why this commit? Markdown; paste or drop images.", "review-summary")
        elif r.summary.strip():
            self._markdown_view(r.summary)
        else:
            ui.label("No summary yet.").classes("text-xs text-gray-500 italic")

    @ui.refreshable_method
    def pinned_view(self) -> None:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            if self.pinned:
                ui.icon("push_pin").classes("text-amber-500")
                ui.label(chip_text(self.pinned)).classes("text-xs truncate flex-grow").mark("review-pinned")
            else:
                ui.label("Click a net, part or footprint in the viewer to point a note at it.").classes(
                    "text-xs text-gray-500 flex-grow")
            ui.button("Note", icon="add", on_click=self.add_note).props(
                "unelevated dense color=amber-8").tooltip(
                f"Add a note about {self.pinned.label}" if self.pinned else "Add a note").mark("review-add-note")

    @ui.refreshable_method
    def notes_view(self) -> None:
        notes = self.review.notes
        if not notes:
            ui.label("No notes yet.").classes("text-xs text-gray-500 italic")
        for note in notes:
            self._note_card(note)

    def _note_card(self, note: Note) -> None:
        editing = note.id in self.editing
        with ui.card().classes("w-full bg-[#1c2128] gap-1 p-2").props("flat bordered"):
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                if note.anchor:
                    color = "red-4" if note.anchor.removed else "amber-5"
                    ui.chip(chip_text(note.anchor), icon="my_location",
                            on_click=lambda n=note: self.focus_cb(n.anchor)).props(
                        f"dense outline color={color} clickable").classes("text-xs max-w-[16rem] truncate").tooltip(
                        "Show it in the viewer" + (f". {note.anchor.where}" if note.anchor.where else ""))
                else:
                    ui.label("General note").classes("text-xs text-gray-500")
                ui.space()
                ui.button(icon="visibility" if editing else "edit",
                          on_click=lambda n=note: self.toggle_edit(n.id)).props("flat dense round size=sm").tooltip(
                    "Preview" if editing else "Edit")
                with ui.button(icon="more_vert").props("flat dense round size=sm"):
                    with ui.menu():
                        pin_item = ui.menu_item("Point at what's pinned", on_click=lambda n=note: self.point_at_pinned(n))
                        pin_item.set_enabled(self.pinned is not None)
                        if note.anchor:
                            ui.menu_item("Make it a general note", on_click=lambda n=note: self.unanchor(n))
                        ui.menu_item("Delete note", on_click=lambda n=note: self.remove_note(n))
            if editing:
                ui.input(value=note.title, placeholder="Title",
                         on_change=lambda e, n=note: (setattr(n, "title", e.value or ""), self.changed())).props(
                    "dark dense borderless").classes("w-full font-semibold").mark("review-note-title")
                tags = ui.select(review.TAGS, multiple=True, value=list(note.tags), new_value_mode="add-unique",
                                 label="Tags",
                                 on_change=lambda e, n=note: (setattr(n, "tags", list(e.value or [])), self.changed()))
                tags.props("dark dense outlined use-chips options-dense").classes("w-full text-xs")
                self._markdown_box(note.body, lambda v, n=note: setattr(n, "body", v),
                                   "What changed and why. Markdown; paste or drop images.", "review-note-body")
            else:
                ui.label(note.title or "Note").classes("font-semibold text-sm")
                if note.tags:
                    with ui.row().classes("gap-1"):
                        for t in note.tags:
                            ui.badge(t, color="blue-grey-7").props("outline")
                if note.body.strip():
                    self._markdown_view(note.body)


def focus_script(frame_id: int, anchor: Anchor) -> str:
    """JavaScript that asks the viewer in the iframe to show an anchor."""
    msg = json.dumps({"kigit": "focus", "anchor": anchor.to_dict()})
    return f"getHtmlElement({frame_id})?.contentWindow?.postMessage({msg}, '*');"


# Viewer messages (pcb.js / sch.js / shell.js) forwarded to the GUI.
BRIDGE_JS = """
<script>
window.addEventListener("message", (e) => {
  const m = e.data;
  if (!m || typeof m !== "object") return;
  if (m.kigit === "pinned") emitEvent("kigit_pinned", m.anchor || null);
  else if (m.kigit === "focused") emitEvent("kigit_focused", { anchor: m.anchor, found: !!m.found });
});
</script>
"""
