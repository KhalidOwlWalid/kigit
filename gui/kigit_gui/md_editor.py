"""A Markdown editor like GitHub's comment box: Write and Preview tabs, a
formatting toolbar (heading, bold, italic, quote, code, link, lists, task
list), and files added by paste, drop or click ("Paste, drop, or click to
add files"). Used for review summaries and notes, and discussion messages.

Files go to reviews/assets/ (review.save_file) through /review-upload/{key};
images are inserted as pictures, anything else as a link named after the
file. Paths are relative to reviews/ (where the review files are).

Formatting runs in the page (so Ctrl+Z undoes it); the link button and
Ctrl+K ask for the address in a dialog, from Python.
"""

from __future__ import annotations

import re
from typing import Callable

from nicegui import ui

from . import logs, review

# (action, icon, tooltip). "|" is a separator. The page script (_JS) does
# the formatting; "link" is done from Python (add_link).
TOOLBAR = [
    ("heading", "title", "Heading"),
    ("bold", "format_bold", "Bold (Ctrl+B)"),
    ("italic", "format_italic", "Italic (Ctrl+I)"),
    ("quote", "format_quote", "Quote"),
    ("code", "code", "Code"),
    ("link", "link", "Link (Ctrl+K)"),
    ("|", "", ""),
    ("bullets", "format_list_bulleted", "Bulleted list"),
    ("numbers", "format_list_numbered", "Numbered list"),
    ("tasks", "checklist", "Task list"),
]

_JS = """
<script>
(() => {
  const editorOf = (el) => el && el.closest && el.closest(".kigit-mde");
  const areaOf = (ed) => ed && ed.querySelector("textarea");
  // Replaces the text box's [a, b) with text and selects [s, e) of the
  // result; through execCommand so Ctrl+Z undoes it.
  function replace(ta, a, b, text, s, e) {
    ta.focus();
    ta.setSelectionRange(a, b);
    if (!document.execCommand("insertText", false, text)) {
      ta.setRangeText(text, a, b, "end");
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    }
    ta.setSelectionRange(s, e);
  }
  const WRAP = { bold: "**", italic: "_" };
  const PREFIX = { heading: "### ", quote: "> ", bullets: "- ", tasks: "- [ ] " };
  function format(ta, action) {
    const v = ta.value, a = ta.selectionStart, b = ta.selectionEnd, sel = v.slice(a, b);
    if (WRAP[action] || (action === "code" && !sel.includes("\\n"))) {
      const w = WRAP[action] || "`";
      // Already wrapped: unwrap.
      if (v.slice(a - w.length, a) === w && v.slice(b, b + w.length) === w)
        return replace(ta, a - w.length, b + w.length, sel, a - w.length, b - w.length);
      return replace(ta, a, b, w + sel + w, a + w.length, b + w.length);
    }
    if (action === "code") {  // several lines: a code block
      const text = "```\\n" + sel + (sel.endsWith("\\n") ? "" : "\\n") + "```";
      return replace(ta, a, b, text, a + 4, a + 4 + sel.length);
    }
    // Line prefixes: on every line the selection touches.
    const start = v.lastIndexOf("\\n", a - 1) + 1;
    let end = v.indexOf("\\n", b === a ? b : b - 1);
    if (end < 0) end = v.length;
    const lines = v.slice(start, end).split("\\n");
    const pre = (i) => action === "numbers" ? `${i + 1}. ` : PREFIX[action];
    const has = lines.every((l, i) => action === "numbers" ? /^\\d+\\. /.test(l) : l.startsWith(pre(i)));
    const out = lines.map((l, i) => has ? l.replace(action === "numbers" ? /^\\d+\\. / : pre(i), "") : pre(i) + l)
      .join("\\n");
    replace(ta, start, end, out, start === a && b === a ? start + out.length : start, start + out.length);
  }
  window.kigitFormat = (id, action) => { const ta = areaOf(editorOf(getHtmlElement(id))); if (ta) format(ta, action); };
  document.addEventListener("click", (e) => {
    const btn = e.target.closest && e.target.closest(".kigit-mde [data-md]");
    if (!btn) return;
    e.preventDefault();
    const ta = areaOf(editorOf(btn));
    if (ta) format(ta, btn.dataset.md);
  }, true);
  document.addEventListener("keydown", (e) => {
    const ta = e.target.closest && e.target.closest(".kigit-mde textarea");
    if (!ta || !(e.ctrlKey || e.metaKey) || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "b" || k === "i") { e.preventDefault(); format(ta, k === "b" ? "bold" : "italic"); }
    else if (k === "k") { e.preventDefault(); emitEvent("kigit_link", +editorOf(ta).dataset.box); }
  });

  // Files: paste, drop (anywhere on the editor) or the footer's file picker.
  async function upload(ed, files) {
    const ta = areaOf(ed);
    if (!ta || !files.length) return;
    ed.classList.add("busy");
    const parts = [];
    for (const f of files) {
      try {
        const r = await fetch(`/review-upload/${ed.dataset.key}`, { method: "POST", body: f, headers: {
          "Content-Type": f.type || "application/octet-stream", "X-Filename": encodeURIComponent(f.name || "") } });
        const j = await r.json();
        if (!r.ok) { emitEvent("kigit_upload_failed", `${f.name || "file"}: ${j.error || r.statusText}`); continue; }
        parts.push(j.markdown);
      } catch (err) { emitEvent("kigit_upload_failed", `${f.name || "file"}: ${err}`); }
    }
    ed.classList.remove("busy");
    if (!parts.length) return;
    const a = ta.selectionStart, b = ta.selectionEnd, v = ta.value;
    const before = a > 0 && v[a - 1] !== "\\n" ? "\\n" : "";  // on a line of its own
    const text = before + parts.join("\\n");
    replace(ta, a, b, text, a + text.length, a + text.length);
  }
  const files = (dt) => [...((dt && dt.files) || [])];
  document.addEventListener("paste", (e) => {
    const ed = editorOf(e.target), fs = files(e.clipboardData);
    if (ed && fs.length) { e.preventDefault(); upload(ed, fs); }
  }, true);
  document.addEventListener("dragover", (e) => {
    const ed = editorOf(e.target);
    if (ed && e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { e.preventDefault(); ed.classList.add("drop"); }
  }, true);
  document.addEventListener("dragleave", (e) => {
    const ed = editorOf(e.target);
    if (ed && !ed.contains(e.relatedTarget)) ed.classList.remove("drop");
  }, true);
  document.addEventListener("drop", (e) => {
    const ed = editorOf(e.target);
    if (!ed) return;
    ed.classList.remove("drop");
    const fs = files(e.dataTransfer);
    if (fs.length) { e.preventDefault(); upload(ed, fs); }
  }, true);
  document.addEventListener("click", (e) => {
    const pick = e.target.closest && e.target.closest(".kigit-mde .kigit-mde-attach");
    if (!pick) return;
    const ed = editorOf(pick), input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.onchange = () => upload(ed, [...input.files]);
    input.click();
  });
  // A text box by NiceGUI element id (the id is on the <textarea> itself).
  const textarea = (id) => { const el = getHtmlElement(id); return el?.tagName === "TEXTAREA" ? el : el?.querySelector("textarea"); };
  window.kigitSelection = (id) => { const t = textarea(id); return t ? [t.selectionStart, t.selectionEnd] : null; };
  window.kigitCursor = (id, pos) => { const t = textarea(id); if (t) { t.focus(); t.setSelectionRange(pos, pos); } };
})();
</script>
<style>
.kigit-mde { border: 1px solid #3a4250; border-radius: 6px; background: #0f1115; }
.kigit-mde:focus-within { border-color: #e8b84d88; }
.kigit-mde.drop { border-color: #e8b84d; box-shadow: 0 0 0 2px #e8b84d44; }
.kigit-mde-head { display: flex; align-items: center; gap: 2px; border-bottom: 1px solid #29303a; background: #161a20;
  border-radius: 6px 6px 0 0; padding: 0 4px; flex-wrap: wrap; }
.kigit-mde-tab { padding: 6px 12px; font-size: 13px; color: #9aa4b2; cursor: pointer; border: 1px solid transparent;
  border-bottom: 0; border-radius: 6px 6px 0 0; margin-bottom: -1px; user-select: none; }
.kigit-mde-tab.on { color: #e6e9ee; background: #0f1115; border-color: #29303a; }
.kigit-mde-tools { margin-left: auto; display: flex; align-items: center; gap: 0; }
.kigit-mde-tools .q-btn { color: #9aa4b2; }
.kigit-mde-tools .q-btn:hover { color: #e6e9ee; }
.kigit-mde-sep { width: 1px; height: 16px; background: #3a4250; margin: 0 4px; }
.kigit-mde-body { padding: 6px; }
.kigit-mde-body .q-field__control { min-height: 5.5em; }
.kigit-mde-preview { min-height: 5.5em; padding: 4px 6px; }
.kigit-mde-foot { display: flex; align-items: center; gap: 6px; padding: 4px 10px 6px; font-size: 12px; color: #7d8794;
  border-top: 1px dashed #29303a; cursor: pointer; user-select: none; }
.kigit-mde-foot:hover { color: #e8b84d; }
.kigit-mde.busy .kigit-mde-foot::after { content: "uploading..."; color: #e8b84d; margin-left: auto; }
</style>
"""


class Editors:
    """The page's Markdown editors. One per page: it adds the page script
    and the Ctrl+K and upload-failure handlers."""

    def __init__(self) -> None:
        self.boxes: dict[int, ui.textarea] = {}  # text boxes by element id, for Ctrl+K
        ui.add_body_html(_JS)
        ui.on("kigit_link", lambda e: self.add_link(self.boxes.get(e.args) if isinstance(e.args, int) else None))
        ui.on("kigit_upload_failed", self._failed)

    @staticmethod
    def _failed(e) -> None:
        logs.log.warning("couldn't add a file: %s", e.args)
        ui.notify(f"Couldn't add the file: {e.args}", type="warning", multi_line=True, close_button=True)

    def editor(self, value: str, on_change: Callable[[str], None], placeholder: str, mark: str, key: str,
               preview_key: str | None = None) -> ui.textarea:
        """An editor for `value`; on_change(text) on every edit. key: the
        project's upload key (review_panel.project_key). Returns the text box."""
        with ui.element("div").classes("kigit-mde w-full").props(f'data-key="{key}"').mark(f"{mark}-editor") as wrap:
            with ui.element("div").classes("kigit-mde-head"):
                write_tab = ui.element("div").classes("kigit-mde-tab on").mark(f"{mark}-write")
                with write_tab:
                    ui.label("Write")
                preview_tab = ui.element("div").classes("kigit-mde-tab").mark(f"{mark}-preview")
                with preview_tab:
                    ui.label("Preview")
                with ui.element("div").classes("kigit-mde-tools") as tools:
                    for action, icon, tip in TOOLBAR:
                        if action == "|":
                            ui.element("span").classes("kigit-mde-sep")
                            continue
                        b = ui.button(icon=icon).props("flat dense round size=sm tabindex=-1").tooltip(tip).mark(
                            f"{mark}-{action}")
                        if action == "link":
                            b.on("click", lambda: self.add_link(box))
                        else:
                            b.props(f'data-md="{action}"')
            with ui.element("div").classes("kigit-mde-body"):
                box = ui.textarea(value=value, placeholder=placeholder,
                                  on_change=lambda e: on_change(e.value or "")).props(
                    "dark borderless autogrow dense").classes("w-full text-sm").mark(mark)
                preview = ui.html("").classes("kigit-mde-preview kigit-md-view nicegui-markdown w-full text-sm "
                                              "text-gray-200").mark(f"{mark}-rendered")
                preview.set_visibility(False)
            with ui.element("div").classes("kigit-mde-foot kigit-mde-attach").mark(f"{mark}-attach"):
                ui.icon("attach_file", size="xs")
                ui.label("Paste, drop, or click to add files")

        def show(previewing: bool) -> None:
            if previewing:
                text = box.value or ""
                preview.content = (review.to_html(rewrite_assets(text, preview_key or key)) if text.strip()
                                   else '<p style="color:#7d8794">Nothing to preview.</p>')
            preview.set_visibility(previewing)
            box.set_visibility(not previewing)
            tools.set_visibility(not previewing)
            write_tab.classes(remove="on") if previewing else write_tab.classes(add="on")
            preview_tab.classes(add="on") if previewing else preview_tab.classes(remove="on")
        write_tab.on("click", lambda: show(False))
        preview_tab.on("click", lambda: show(True))
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
        with box.parent_slot.parent:  # the dialog needs a place in the page; it's removed after
            result = await self._link_dialog(value[start:end])
        if not result:
            return
        md = review.link_markdown(*result)
        box.value = value[:start] + md + value[end:]
        ui.run_javascript(f"window.kigitCursor({box.id}, {start + len(md)})")

    @staticmethod
    async def _link_dialog(selected: str) -> tuple[str, str] | None:
        """(text, address), or None if cancelled."""
        with ui.dialog() as dialog, ui.card().classes("w-[32rem] max-w-full bg-[#161a20] gap-2"):
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


def rewrite_assets(text: str, key: str) -> str:
    """Markdown with assets/ links pointing at the GUI's file route, for preview."""
    return re.sub(r"\]\(\s*assets/", f"](/review-files/{key}/", text)
