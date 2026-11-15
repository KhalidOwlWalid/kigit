"""The review panel: notes on why a commit changed what it changed.

Opens on the right when a single commit is reviewed (diffed against its
parent). Each note can point at what's pinned in the viewer (a net,
footprint, part or bus); clicking the note's anchor shows it again. Text is
Markdown; pasting or dropping an image stores it in reviews/assets/.

Press Write (or Ctrl+S) to save it to `<project>/reviews/<id>.md` and update
`reviews/index.md` (see review.py). Until then edits are only in the GUI: switching to another commit
or closing the panel keeps them as a draft for this session, and the browser
asks before the page is closed with anything unwritten.
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


def note_times(n: Note) -> str:
    if not n.created:
        return "Not written yet"
    return f"Written {n.created}" + (f" · edited {n.edited}" if n.edited else "")


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
  // Ctrl+K / Cmd+K in a note's text box: add a link (the GUI asks for it).
  document.addEventListener("keydown", (e) => {
    const ta = box(e);
    if (ta && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      emitEvent("kigit_link", +ta.closest(".kigit-md").dataset.box);
    }
  });
  // A text box by NiceGUI element id (the id is on the <textarea> itself).
  const textarea = (id) => { const el = getHtmlElement(id); return el?.tagName === "TEXTAREA" ? el : el?.querySelector("textarea"); };
  // The selection in a text box: [start, end].
  window.kigitSelection = (id) => {
    const t = textarea(id);
    return t ? [t.selectionStart, t.selectionEnd] : null;
  };
  // Puts the cursor at `pos` in a text box.
  window.kigitCursor = (id, pos) => {
    const t = textarea(id);
    if (t) { t.focus(); t.setSelectionRange(pos, pos); }
  };
  // Ctrl+S / Cmd+S writes the open review.
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s" && document.querySelector(".kigit-write")) {
      e.preventDefault();
      emitEvent("kigit_write");
    }
  });
  // Unwritten edits: ask before leaving the page.
  window.addEventListener("beforeunload", (e) => {
    if (document.querySelector(".kigit-unsaved")) { e.preventDefault(); e.returnValue = ""; }
  });
})();
</script>
<style>
.kigit-md-view img { max-width: 100%; border-radius: 4px; }
.kigit-md-view p { margin: 0.3em 0; }
.kigit-md-view a { color: #7fb3ff; }
.kigit-md-view math { font-size: 1.1em; }
.kigit-md-view math[display=block] { margin: .6em 0; overflow-x: auto; overflow-y: hidden; }
.kigit-md-view .math-error { color: #f07178; border-bottom: 1px dotted #f07178; cursor: help; }
</style>
"""


def rewrite_images(text: str, key: str) -> str:
    """Markdown with assets/ links pointing at the GUI's image route, for preview."""
    return re.sub(r"\]\(\s*assets/", f"](/review-files/{key}/", text)


class ReviewPanel:
    """The right-hand drawer. `focus(anchor)` asks the viewer to show an
    anchor; `on_saved(commit)` is called when a review file is first written.
    `strays()` gives the reviews of rewritten commits (rewritten.py) that can
    be brought into this one; `on_moved()` is called after writing a review
    that took some in."""

    def __init__(self, focus: Callable[[Anchor], None], on_saved: Callable[[str], None], resizer=None,
                 strays: Callable[[], list] | None = None, on_moved: Callable[[], None] | None = None) -> None:
        self.focus_cb, self.on_saved = focus, on_saved
        self.strays_cb, self.on_moved = strays or (lambda: []), on_moved or (lambda: None)
        self.message = ""  # the open commit's whole message
        self.known_tags: list[str] = list(review.TAGS)  # offered in the tags dropdown
        self.project: Path | None = None
        self.key = ""
        self.review: Review | None = None
        self.path: Path | None = None
        self.dirty = False  # edits not written yet
        # Unwritten edits of reviews that aren't open: commit -> (project, review, file).
        self.drafts: dict[str, tuple[Path, Review, Path | None]] = {}
        self.pinned: Anchor | None = None
        self.status_label = self.write_button = None
        self.note_times: dict[str, ui.label] = {}  # note id -> its "Written ... · edited ..." line
        self.editing: set[str] = set()  # notes (by id) shown as text boxes; "summary" for the summary

        ui.add_body_html(_PAGE_JS)
        ui.on("kigit_image_failed", lambda e: self._warn(f"Couldn't add the image: {e.args}"))
        ui.on("kigit_write", lambda: self.write() if self.review else None)
        self.boxes: dict[int, ui.textarea] = {}  # text boxes by element id, for Ctrl+K
        ui.on("kigit_link", lambda e: self.add_link(self.boxes.get(e.args) if isinstance(e.args, int) else None))
        # Present (with class kigit-unsaved) while anything is unwritten; the
        # page asks before closing then.
        self.unsaved_marker = ui.element("div").classes("hidden")
        with ui.right_drawer(value=False, bordered=True).classes(
                "bg-[#161a20] p-0") as self.drawer:
            self.body = ui.column().classes("w-full p-3 gap-2")
        self.drawer.mark("review-panel")
        if resizer is not None:
            resizer.add(self.drawer, "right", "review", 480)
        else:
            self.drawer.props("width=480")

    # ------------------------------------------------------------- open/close
    def open(self, project_dir: str | Path, commit: str, parent: str, subject: str, date: str = "",
             author: str = "", body: str = "") -> None:
        self._stash()
        self.message = subject + ("\n\n" + body if body else "")
        self.project = Path(project_dir)
        self.key = project_key(self.project)
        self.review = None
        draft = self.drafts.get(commit)
        if draft and draft[0] == self.project:
            # Back to a review left unwritten: carry on where it was.
            del self.drafts[commit]
            _, self.review, self.path = draft
            self.dirty = True
        else:
            self.path = review.all_reviews(self.project).get(commit)
        if self.review is None and self.path:
            try:
                self.review = review.load(self.path)
            except (OSError, ValueError, UnicodeDecodeError) as e:
                self._warn(f"Couldn't read {self.path.name}: {e}")
                self.path = None
        if self.review is None:
            self.review = Review(commit=commit, parent=parent, subject=subject, date=date, author=author)
        self.editing = set() if self.review.summary or self.review.notes else {"summary"}
        self.known_tags = review.known_tags(self.project)
        logs.log.info("review %s (%s%s)", commit[:7], self.path or "new", ", unwritten draft" if self.dirty else "")
        self.render()
        self.drawer.show()

    def close(self) -> None:
        self._stash()
        self.review = None
        self.drawer.hide()
        self._sync_status()

    def _stash(self) -> None:
        """Keeps the open review's unwritten edits as a draft."""
        if self.review and self.dirty:
            self.drafts[self.review.commit] = (self.project, self.review, self.path)
            logs.log.info("kept unwritten review %s as a draft", self.review.commit[:7])
        self.dirty = False

    @property
    def commit(self) -> str | None:
        return self.review.commit if self.review else None

    def set_pinned(self, anchor: Anchor | None) -> None:
        self.pinned = anchor
        if self.review:
            self.pinned_view.refresh()

    # ------------------------------------------------------------------- save
    def changed(self) -> None:
        if not self.dirty:
            self.dirty = True
            self._sync_status()

    def write(self) -> None:
        """Writes the open review to its file."""
        if not (self.review and self.project):
            return
        first = self.path is None
        took_in = bool(self.review.absorbed)
        try:
            self.path = review.save(self.project, self.review, self.path)
        except OSError as e:
            self._warn(f"Couldn't write the review: {e}")
            return
        self.dirty = False
        logs.log.info("wrote review %s", self.path)
        ui.notify(f"Written to {review.FOLDER}/{self.path.name}", type="positive")
        self.path_label.text = self._path_text()
        self.id_label.text = f"ID {self.review.id}"
        for n in self.review.notes:  # in place, so a text box being typed in keeps its cursor
            if n.id in self.note_times:
                self.note_times[n.id].text = note_times(n)
        self._sync_status()
        if first:
            self.on_saved(self.review.commit)
        if took_in:
            self.bring_in_view.refresh()
            self.on_moved()

    def _sync_status(self) -> None:
        """The Write button, the "unsaved" line, and the page's leave warning."""
        if self.dirty or self.drafts:
            self.unsaved_marker.classes(add="kigit-unsaved")
        else:
            self.unsaved_marker.classes(remove="kigit-unsaved")
        if self.status_label is None or self.review is None:
            return
        others = [c[:7] for c in self.drafts]
        if self.dirty:
            text, tone = "Unsaved changes", "text-amber-400"
        elif self.path:
            text, tone = f"Written {self.review.updated}", "text-gray-500"
        else:
            text, tone = "Nothing written yet", "text-gray-500"
        if others:
            text += f" · unwritten draft{'s' if len(others) > 1 else ''}: {', '.join(others)}"
        self.status_label.text = text
        self.status_label.classes(replace=f"text-xs {tone} flex-grow")
        self.write_button.set_enabled(self.dirty)

    def _warn(self, message: str) -> None:
        logs.log.warning("shown to user: %s", message)
        ui.notify(message, type="warning", multi_line=True, close_button=True)

    def _path_text(self) -> str:
        if self.path:
            return f"{review.FOLDER}/{self.path.name}"
        return f"{review.FOLDER}/ (not written yet; it gets an ID then)"

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
        self.boxes = {}
        with self.body:
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                ui.icon("rate_review").classes("text-amber-500")
                ui.label("Review").classes("text-base font-semibold")
                ui.label(r.commit[:7]).classes("text-mono text-xs text-gray-400")
                self.id_label = ui.label(f"ID {r.id}" if r.id else "").classes(
                    "text-mono text-xs text-amber-400").mark("review-id")
                self.id_label.tooltip("This review's ID: its file name, and its row in reviews/index.md")
                ui.space()
                ui.button(icon="close", on_click=self.close).props("flat dense round").tooltip("Close the review")
            ui.label(r.subject).classes("text-sm text-gray-300")
            self.bring_in_view()
            with ui.row().classes("w-full items-center gap-2 no-wrap"):
                self.status_label = ui.label("").classes("text-xs flex-grow").mark("review-status")
                self.write_button = ui.button("Write", icon="save", on_click=self.write).props(
                    "unelevated dense color=green-8").classes("kigit-write").tooltip(
                    "Write the review to its file (Ctrl+S)").mark("review-write")
            with ui.row().classes("w-full items-center gap-1 no-wrap"):
                self.path_label = ui.label(self._path_text()).classes("text-xs text-gray-500 truncate flex-grow")
                ui.button(icon="folder", on_click=self._open_folder).props("flat dense round size=sm").tooltip(
                    "Open the reviews folder")
            self.summary_view()
            ui.separator().classes("my-1")
            self.pinned_view()
            self.notes_view()
        self._sync_status()

    # ------------------------------------------------------ rewritten commits
    def available_strays(self) -> list:
        """Reviews of rewritten commits not yet taken into this review or a draft."""
        taken = {p for _, r, _ in self.drafts.values() for p in r.absorbed}
        if self.review:
            taken |= set(self.review.absorbed)
        return [s for s in self.strays_cb() if s.path not in taken and self.review and s.path != self.path]

    @ui.refreshable_method
    def bring_in_view(self) -> None:
        strays = self.available_strays()
        if not strays:
            return
        n = len(strays)
        ui.button(f"Bring in reviews ({n})", icon="call_merge", on_click=self.bring_in).props(
            "flat dense no-caps size=sm color=amber-5").tooltip(
            f"{n} review{'s are' if n > 1 else ' is'} of commits that are on no branch any more (squashed, "
            "rebased or dropped). Add their notes to this review, e.g. when they were squashed into this "
            "commit.").mark("review-bring-in")

    async def bring_in(self) -> None:
        from .rewritten import squashed_into
        strays = self.available_strays()
        with self.drawer, ui.dialog() as dialog, ui.card().classes("w-[36rem] max-w-full bg-[#161a20] gap-2"):
            ui.label("Bring in reviews").classes("text-base font-semibold")
            ui.label("These reviews are of commits that are on no branch any more. Tick the ones that went into "
                     f"{self.review.commit[:7]} (ticked: named in its message, as a squash does). Their summary "
                     "and notes are added to this review; their files are removed when you Write.").classes(
                "text-xs text-gray-400")
            boxes = []
            for st in strays:
                r = st.review
                text = f"{r.commit[:7]}  {r.subject or '(no message)'} · {len(r.notes)} note" + (
                    "s" if len(r.notes) != 1 else "")
                boxes.append((st, ui.checkbox(text, value=squashed_into(st, self.message)).props(
                    "dense dark").classes("text-sm").mark("bring-in-pick")))
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
                ui.button("Bring in", icon="call_merge", on_click=lambda: dialog.submit(
                    [st for st, box in boxes if box.value])).props("unelevated color=amber-8").mark("bring-in-ok")
        dialog.open()
        picked = await dialog
        dialog.delete()
        if not picked:
            return
        for st in picked:
            try:
                other = review.load(st.path)  # as it is now, not as listed
            except (OSError, ValueError, UnicodeDecodeError) as e:
                self._warn(f"Couldn't read {st.path.name}: {e}")
                continue
            review.absorb(self.review, other, st.path)
            logs.log.info("brought review %s (%s) into %s", st.path.name, other.commit[:7], self.review.commit[:7])
        self.changed()
        self.render()

    def _open_folder(self) -> None:
        from .app import open_folder_in_os
        d = review.folder(self.project)
        open_folder_in_os(d if d.is_dir() else self.project)

    def _markdown_box(self, value: str, on_change: Callable[[str], None], placeholder: str, mark: str):
        """A Markdown text box that takes pasted or dropped images, with a
        button (and Ctrl+K) to add a link."""
        with ui.element("div").classes("kigit-md w-full").props(f'data-key="{self.key}"') as wrap:
            box = ui.textarea(value=value, placeholder=placeholder,
                              on_change=lambda e: (on_change(e.value or ""), self.changed())).props(
                "dark outlined autogrow dense").classes("w-full text-sm").mark(mark)
            with box.add_slot("append"):
                ui.button(icon="link", on_click=lambda: self.add_link(box)).props(
                    "flat dense round size=sm tabindex=-1").tooltip("Add a link (Ctrl+K)").mark(f"{mark}-link")
        wrap.props(f'data-box="{box.id}"')
        self.boxes[box.id] = box
        return box

    async def add_link(self, box: ui.textarea | None) -> None:
        """Asks for an address and its text, and puts a Markdown link where
        the cursor is (around the selected text, which becomes its text)."""
        if box is None:
            return
        value = box.value or ""
        start = end = len(value)
        try:
            sel = await ui.run_javascript(f"window.kigitSelection({box.id})", timeout=2)
            if isinstance(sel, list) and len(sel) == 2 and all(isinstance(x, int) for x in sel):
                start, end = sorted(min(max(x, 0), len(value)) for x in sel)
        except TimeoutError:
            pass
        result = await self._link_dialog(value[start:end])
        if not result:
            return
        md = review.link_markdown(*result)
        box.value = value[:start] + md + value[end:]
        ui.run_javascript(f"window.kigitCursor({box.id}, {start + len(md)})")

    async def _link_dialog(self, selected: str) -> tuple[str, str] | None:
        """(text, address), or None if cancelled."""
        with self.drawer, ui.dialog() as dialog, ui.card().classes("w-[32rem] max-w-full bg-[#161a20] gap-2"):
            ui.label("Add a link").classes("text-base font-semibold")
            url = ui.input("Address", placeholder="https://..., or a file in reviews/ like decisions/buck.md").props(
                "dark dense outlined autofocus").classes("w-full").mark("link-url")
            text = ui.input("Text", value=selected, placeholder="What the link says (default: the address)").props(
                "dark dense outlined").classes("w-full").mark("link-text")
            ui.label("Tip: [[note name]] links to a note in reviews/, [[review ID]] to a review.").classes(
                "text-xs text-gray-500")

            def done() -> None:
                if (url.value or "").strip():
                    dialog.submit(((text.value or "").strip(), url.value.strip()))

            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
                add = ui.button("Add link", icon="link", on_click=done).props("unelevated color=amber-8").mark(
                    "link-add")
            add.bind_enabled_from(url, "value", backward=lambda v: bool((v or "").strip()))
            url.on("keydown.enter", done)
            text.on("keydown.enter", done)
        dialog.open()
        result = await dialog
        dialog.delete()
        return result

    def _markdown_view(self, text: str) -> None:
        # Same rendering as the reviews page: bare links, $math$, Markdown.
        ui.html(review.to_html(rewrite_images(text, self.key))).classes(
            "kigit-md-view nicegui-markdown w-full text-sm text-gray-200")

    def _tags_select(self, note: Note) -> ui.select:
        """The note's tags: tick them in a dropdown of the built-in tags and
        the project's own, or type to filter and Enter to add a new one."""
        options = list(dict.fromkeys(self.known_tags + [t for n in self.review.notes for t in n.tags]))

        def changed(e) -> None:
            tags = list(dict.fromkeys(t for t in (review.clean_tag(x) for x in e.value or []) if t))
            if tags != list(e.value or []):  # a typed tag, tidied: "Needs Review" -> "needs-review"
                opts = [o for o in sel.options if o in self.known_tags or o in tags or
                        any(o in n.tags for n in self.review.notes)]
                opts += [t for t in tags if t not in opts]
                sel.set_options(opts, value=tags)
                return  # set_options fires this again with the tidy value
            for t in tags:
                if t not in self.known_tags:
                    self.known_tags.append(t)  # offered in the other notes too
            if tags != note.tags:
                note.tags = tags
                self.changed()

        sel = ui.select(options, multiple=True, value=list(note.tags), new_value_mode="add-unique", label="Tags",
                        on_change=changed)
        sel.props('dark dense outlined use-chips options-dense input-debounce=0 '
                  'hint="Pick tags, or type a new one and press Enter" popup-content-class=kigit-tag-menu')
        sel.classes("w-full text-xs").mark("review-note-tags")
        sel.add_slot("option", _TAG_OPTION)
        sel.add_slot("selected-item", _TAG_CHIP)
        return sel

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
        self.note_times = {}
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
                        f"dense outline color={color} clickable").classes("text-xs max-w-[70%] truncate").tooltip(
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
                self._tags_select(note)
                self._markdown_box(note.body, lambda v, n=note: setattr(n, "body", v),
                                   "What changed and why. Markdown; paste or drop images.", "review-note-body")
            else:
                ui.label(note.title or "Note").classes("font-semibold text-sm")
                if note.tags:
                    with ui.row().classes("gap-1"):
                        for t in note.tags:
                            ui.badge(t, color=TAG_COLORS.get(t, "blue-grey-4")).props("outline")
                if note.body.strip():
                    self._markdown_view(note.body)
            self.note_times[note.id] = ui.label(note_times(note)).classes("text-[11px] text-gray-500").mark(
                "review-note-times")


# Tag colours, the same as on the reviews page; other tags are grey.
TAG_COLORS = {"reason": "blue-4", "todo": "amber-6", "question": "purple-4", "risk": "red-4"}
# Single quotes only: it goes inside a double-quoted attribute.
_TAG_COLOR_JS = ("({" + ", ".join(f"'{k}': '{v}'" for k, v in TAG_COLORS.items())
                 + "})[props.opt.label] || 'blue-grey-4'")

# The dropdown's rows: a tick box, a colour dot and the tag.
_TAG_OPTION = f"""
<q-item v-bind="props.itemProps" dense>
  <q-item-section side style="padding-right:8px">
    <q-checkbox :model-value="props.selected" dense size="xs" style="pointer-events:none" color="amber-7" />
  </q-item-section>
  <q-item-section>
    <q-item-label><q-icon name="circle" size="9px" :color="{_TAG_COLOR_JS}" class="q-mr-sm" />{{{{ props.opt.label }}}}</q-item-label>
  </q-item-section>
</q-item>
"""
# A chosen tag: a coloured chip with a cross.
_TAG_CHIP = f"""
<q-chip dense removable outline :color="{_TAG_COLOR_JS}" :tabindex="props.tabindex" class="q-my-none q-ml-none q-mr-xs"
  @remove="props.removeAtIndex(props.index)">{{{{ props.opt.label }}}}</q-chip>
"""


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
