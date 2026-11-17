"""Every keyboard and mouse shortcut in kigit, for the header's keyboard
button (and "?"). Each one names where it's handled (`where`: a file from
the repository root and a piece of its code), so a test can tell when the
list and the code drift apart.
"""

from __future__ import annotations

import html
from dataclasses import dataclass


@dataclass(frozen=True)
class Shortcut:
    keys: tuple[str, ...]  # alternatives, e.g. ("Ctrl+S", "⌘S")
    does: str
    where: tuple[str, str] = ("", "")  # (file, a piece of the code that handles it)


GROUPS: list[tuple[str, str, list[Shortcut]]] = [
    ("kigit", "keyboard", [
        Shortcut(("?",), "Show this list", ("gui/kigit_gui/app.py", 'emitEvent("kigit_shortcuts")')),
        Shortcut(("N",), "A new note about what's pinned in the viewer (the Notebook)",
                 ("gui/kigit_gui/notebook_panel.py", 'emitEvent("kigit_quick_note")')),
        Shortcut(("Enter",), "In the folder box: open that folder",
                 ("gui/kigit_gui/app.py", 'folder_input.on("keydown.enter"')),
        Shortcut(("Right-click a commit",), "Copy its review's link or file path, or its hash",
                 ("gui/kigit_gui/app.py", '"rowContextmenu"')),
        Shortcut(("Drag a panel's edge",), "Resize the commit list, the review panel or the 3D dock",
                 ("gui/kigit_gui/resize.py", "kigit_panel_width")),
        Shortcut(("Double-click a panel's edge",), "Back to its normal size",
                 ("gui/kigit_gui/app.py", 'removeProperty("--kigit-dock-w")')),
    ]),
    ("Review and discussion editor", "rate_review", [
        Shortcut(("Ctrl+S", "⌘S"), "Write the review", ("gui/kigit_gui/review_panel.py", 'e.key.toLowerCase() === "s"')),
        Shortcut(("Ctrl+B", "⌘B"), "Bold", ("gui/kigit_gui/md_editor.py", 'k === "b"')),
        Shortcut(("Ctrl+I", "⌘I"), "Italic", ("gui/kigit_gui/md_editor.py", 'format(ta, k === "b" ? "bold" : "italic")')),
        Shortcut(("Ctrl+K", "⌘K"), "Add a link (around the selected text)",
                 ("gui/kigit_gui/md_editor.py", 'k === "k"')),
        Shortcut(("Paste", "Drop"), "Add files (pictures show inline; other files become links)",
                 ("gui/kigit_gui/md_editor.py", '"paste"')),
    ]),
    ("Comparison: PCB", "developer_board", [
        Shortcut(("/",), "Filter the nets", ("resources/pcb.js", 'e.key === "/"')),
        Shortcut(("Esc",), "Unpin; in the filter box, clear it", ("resources/pcb.js", 'e.key === "Escape"')),
        Shortcut(("F",), "Fit the board in view", ("resources/pcb.js", "fitAll();")),
        Shortcut(("Scroll",), "Zoom", ("resources/pcb.js", 'svg.addEventListener("wheel"')),
        Shortcut(("Drag",), "Pan", ("resources/pcb.js", 'svg.addEventListener("pointerdown"')),
        Shortcut(("Click",), "Pin a net or footprint (its details stay up)", ("resources/pcb.js", "pin(")),
        Shortcut(("Double-click a net in the list",), "Zoom to it", ("resources/pcb.js", 'list.addEventListener("dblclick"')),
        Shortcut(("Double-click a layer",), "Show only that layer", ("resources/pcb.js", '$("#layers").addEventListener("dblclick"')),
    ]),
    ("Comparison: schematic", "schema", [
        Shortcut(("F",), "Fit the sheet in view", ("resources/sch.js", "fitSheet();")),
        Shortcut(("Esc",), "Unpin", ("resources/sch.js", 'e.key === "Escape"')),
        Shortcut(("Backspace",), "Up to the parent sheet", ("resources/sch.js", 'e.key === "Backspace"')),
        Shortcut(("Double-click a sheet",), "Open it", ("resources/sch.js", 'svg.addEventListener("dblclick"')),
        Shortcut(("Scroll",), "Zoom", ("resources/sch.js", 'svg.addEventListener("wheel"')),
        Shortcut(("Drag",), "Pan", ("resources/sch.js", 'svg.addEventListener("pointerdown"')),
        Shortcut(("Click",), "Pin a net, part or bus", ("resources/sch.js", "pin(")),
    ]),
    ("3D view", "view_in_ar", [
        Shortcut(("Drag",), "Rotate", ("gui/kigit_gui/board3d.py", "OrbitControls")),
        Shortcut(("Right-drag", "Shift-drag"), "Pan", ("gui/kigit_gui/board3d.py", "screenSpacePanning")),
        Shortcut(("Scroll",), "Zoom", ("gui/kigit_gui/board3d.py", "controls.minDistance")),
        Shortcut(("T",), "Top view", ("gui/kigit_gui/board3d.py", 'k === "t"')),
        Shortcut(("B",), "Bottom view", ("gui/kigit_gui/board3d.py", 'k === "b"')),
        Shortcut(("3",), "Angled view", ("gui/kigit_gui/board3d.py", 'k === "3"')),
        Shortcut(("F",), "Fit the board in view", ("gui/kigit_gui/board3d.py", 'k === "f"')),
        Shortcut(("P",), "Parts on or off", ("gui/kigit_gui/board3d.py", 'k === "p"')),
        Shortcut(("M",), "Solder mask on or off (traces show when it's off)", ("gui/kigit_gui/board3d.py", 'k === "m"')),
        Shortcut(("K",), "Silkscreen on or off", ("gui/kigit_gui/board3d.py", 'k === "k"')),
        Shortcut(("S",), "Render stats", ("gui/kigit_gui/board3d.py", 'k === "s"')),
        Shortcut(("L",), "Side by side: link or unlink the views", ("gui/kigit_gui/board3d.py", 'e.key.toLowerCase() === "l"')),
    ]),
    ("3D diff (beta)", "difference", [
        Shortcut(("C",), "Changes on or off", ("gui/kigit_gui/board3d_diff.py", 'k === "c"')),
        Shortcut(("U",), "Fade the parts that didn't change", ("gui/kigit_gui/board3d_diff.py", 'k === "u"')),
        Shortcut(("T", "B", "3", "F"), "Top, bottom, angled, fit", ("gui/kigit_gui/board3d_diff.py", 'k === "t"')),
        Shortcut(("M", "K", "P"), "Mask, silkscreen, parts", ("gui/kigit_gui/board3d_diff.py", 'k === "m"')),
    ]),
    ("Reviews page", "menu_book", [
        Shortcut(("/",), "Search", ("gui/kigit_gui/review_doc.py", 'e.key === "/"')),
        Shortcut(("Esc",), "Clear the search", ("gui/kigit_gui/review_doc.py", 'e.key === "Escape"')),
    ]),
]


_MOUSE = ("Click", "Double-click", "Drag", "Right-drag", "Shift-drag", "Scroll", "Paste", "Drop")


def keys_html(s: Shortcut) -> str:
    """The keys as <kbd>s ("or" between alternatives); mouse actions as plain text."""
    def one(k: str) -> str:
        if k.startswith(_MOUSE):
            return f'<span class="mouse">{html.escape(k)}</span>'
        return f"<kbd>{html.escape(k)}</kbd>"
    return ' <span class="or">or</span> '.join(one(k) for k in s.keys)


def group_html(items: list[Shortcut]) -> str:
    """One area's shortcuts as a two-column table: keys, what they do."""
    rows = "".join(f'<tr><td class="k">{keys_html(s)}</td><td class="d">{html.escape(s.does)}</td></tr>'
                   for s in items)
    return f'<table class="kigit-keys">{rows}</table>'
