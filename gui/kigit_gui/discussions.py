"""The GUI for discussions (threads.py): the list behind the header's
Discussions button, one discussion as a chat with its status buttons, and
the "Request" composer that opens one from a review.

Messages are written to the discussion's file as soon as they're sent (no
Write step): the file is the conversation, shared through git.
"""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Callable

from nicegui import ui

from . import logs, review, threads
from .review import Anchor
from .review_panel import chip_text

STATUS_LOOK = {"open": ("priority_high", "red-4"), "done": ("task_alt", "amber-5"), "accepted": ("verified", "green-5")}


def status_chip(status: str) -> None:
    icon, color = STATUS_LOOK[status]
    ui.chip(threads.LABELS[status], icon=icon, color=color).props("dense outline").classes("text-xs").mark(
        f"status-{status}")


class Discussions:
    """project: the project folder; me: your name (git user.name); head: HEAD's
    hash; focus(anchor): show it in the viewer; changed(): the list changed."""

    def __init__(self, focus: Callable[[Anchor], None], changed: Callable[[], None]) -> None:
        self.focus, self.changed = focus, changed
        self.project: Path | None = None
        self.me = ""
        self.head = ""
        self.filter = "active"  # active (needs attention + done), open, done, accepted, all

    def set_project(self, project: Path | None, me: str = "", head: str = "") -> None:
        self.project, self.head = project, head
        self.me = me or getpass.getuser() or "someone"

    def all(self) -> list[threads.Thread]:
        return threads.all_threads(self.project) if self.project else []

    # ------------------------------------------------------------- the list
    def show_list(self) -> None:
        if not self.project:
            ui.notify("Open a project first", type="warning")
            return
        with ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2").style("width: 92vw; max-width: 52rem"):
            self._list_dialog = dialog
            self.list_view()
        dialog.open()

    @ui.refreshable_method
    def list_view(self) -> None:
        items = self.all()
        n = threads.counts(items)
        with ui.row().classes("w-full items-center gap-2"):
            ui.icon("forum").classes("text-amber-500")
            ui.label("Discussions").classes("text-base font-semibold")
            ui.space()
            ui.toggle({"active": f"Active {n['open'] + n['done']}", "open": f"Needs attention {n['open']}",
                       "done": f"Done {n['done']}", "accepted": f"Accepted {n['accepted']}", "all": "All"},
                      value=self.filter, on_change=lambda e: (setattr(self, "filter", e.value),
                                                                self.list_view.refresh())).props(
                "dense no-caps size=sm toggle-color=amber-8 text-color=grey-5").mark("discussions-filter")
        shown = [t for t in items if self.filter == "all" or t.status == self.filter
                 or (self.filter == "active" and t.status != "accepted")]
        with ui.scroll_area().classes("w-full").style("height: min(30rem, 60vh)"):
            if not shown:
                ui.label("Nothing here. In a commit's review, pin something and press Request to ask for "
                         "attention on it.").classes("text-sm text-gray-500 italic").mark("discussions-empty")
            for t in shown:
                last = t.messages[-1] if t.messages else None
                with ui.card().classes("w-full bg-[#1c2128] p-3 gap-1 cursor-pointer").props("flat bordered").on(
                        "click", lambda t=t: self.show_thread(t.id)).mark("discussion-row"):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        status_chip(t.status)
                        ui.label(t.title).classes("text-sm font-semibold truncate")
                        ui.space()
                        ui.label(f"{len(t.messages)} message{'s' if len(t.messages) != 1 else ''}").classes(
                            "text-xs text-gray-500 whitespace-nowrap")
                    with ui.row().classes("w-full items-center gap-2 no-wrap text-xs text-gray-400"):
                        if t.anchor:
                            ui.label(chip_text(t.anchor)).classes("text-amber-300 whitespace-nowrap")
                        ui.label(f"opened by {t.by} on {t.commit[:7]} · {t.opened}").classes("truncate")
                    if last and last.text:
                        ui.label(f"{last.author}: {review.one_line(last.text)}").classes(
                            "text-xs text-gray-500 truncate w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=self._list_dialog.close).props("flat")

    # ------------------------------------------------------- one discussion
    def show_thread(self, thread_id: str) -> None:
        self.thread_id = thread_id
        with ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2").style("width: 92vw; max-width: 46rem"):
            self._thread_dialog = dialog
            self.thread_view()
        dialog.open()

    def _thread(self) -> threads.Thread | None:
        return next((t for t in self.all() if t.id == self.thread_id), None)

    @ui.refreshable_method
    def thread_view(self) -> None:
        t = self._thread()
        if t is None:
            ui.label("This discussion is gone (deleted, or not pulled yet).").classes("text-gray-400")
            return
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            status_chip(t.status)
            ui.label(t.title).classes("text-base font-semibold").mark("discussion-title")
            ui.space()
            ui.button(icon="close", on_click=self._thread_dialog.close).props("flat dense round size=sm")
        with ui.row().classes("w-full items-center gap-2 text-xs text-gray-400"):
            if t.anchor:
                ui.chip(chip_text(t.anchor), icon="my_location", on_click=lambda: self._focus(t)).props(
                    "dense outline color=amber-5 clickable").classes("text-xs").tooltip("Show it in the viewer")
            ui.label(f"Opened by {t.by} on commit {t.commit[:7]} · {t.opened}")
        with ui.scroll_area().classes("w-full").style("height: min(26rem, 50vh)") as area:
            for m in t.messages:
                self._message(m)
        area.scroll_to(percent=1.0)
        box = ui.textarea(placeholder="Reply: what you changed, or a question. Markdown.").props(
            "dark outlined autogrow dense").classes("w-full text-sm").mark("discussion-reply")
        with ui.row().classes("w-full items-center gap-2"):
            ui.label(f"as {self.me}").classes("text-xs text-gray-500")
            ui.space()
            if t.status == "open":
                ui.button("Mark as done", icon="task_alt", on_click=lambda: self._send(box, "done")).props(
                    "flat color=amber-5").tooltip("You've dealt with it: the reviewer can accept it").mark(
                    "discussion-done")
            if t.status == "done":
                ui.button("Reopen", icon="replay", on_click=lambda: self._send(box, "reopened")).props(
                    "flat color=red-4").tooltip("Not quite: it needs attention again").mark("discussion-reopen")
                ui.button("Accept", icon="verified", on_click=lambda: self._send(box, "accepted")).props(
                    "flat color=green-5").tooltip("Happy with it: closes the discussion").mark("discussion-accept")
            if t.status == "accepted":
                ui.button("Reopen", icon="replay", on_click=lambda: self._send(box, "reopened")).props(
                    "flat color=red-4").mark("discussion-reopen")
            ui.button("Send", icon="send", on_click=lambda: self._send(box, "comment")).props(
                "unelevated color=amber-8").mark("discussion-send")

    def _message(self, m: threads.Message) -> None:
        mine = m.author == self.me
        verb = threads.VERB.get(m.kind, "")
        with ui.row().classes("w-full " + ("justify-end" if mine else "justify-start")):
            with ui.column().classes("gap-0 max-w-[85%] rounded-lg px-3 py-2 " +
                                     ("bg-[#2a2416]" if mine else "bg-[#1c2128]")).mark("discussion-message"):
                with ui.row().classes("items-baseline gap-2"):
                    ui.label(m.author).classes("text-xs font-semibold")
                    ui.label(m.time).classes("text-[11px] text-gray-500")
                    if m.head:
                        ui.label(f"at {m.head[:7]}").classes("text-[11px] text-gray-500 font-mono")
                if verb:
                    icon, color = STATUS_LOOK[threads.STATUS[m.kind]]
                    with ui.row().classes("items-center gap-1"):
                        ui.icon(icon, color=color, size="xs")
                        ui.label(verb.capitalize()).classes("text-xs").classes(f"text-{color.split('-')[0]}-300")
                if m.text:
                    ui.html(review.to_html(m.text)).classes("kigit-md-view nicegui-markdown text-sm text-gray-200")

    def _focus(self, t: threads.Thread) -> None:
        self._thread_dialog.close()
        self.focus(t.anchor)

    def _send(self, box: ui.textarea, kind: str) -> None:
        text = (box.value or "").strip()
        if kind == "comment" and not text:
            return
        try:
            threads.add(self.project, self.thread_id, self.me, self.head, text, kind)
        except (OSError, ValueError) as e:
            ui.notify(f"Couldn't add to the discussion: {e}", type="warning")
            return
        logs.log.info("discussion %s: %s by %s", self.thread_id, kind, self.me)
        self.thread_view.refresh()
        self.changed()

    # ------------------------------------------------------------- composer
    async def request(self, commit: str, anchor: Anchor | None) -> threads.Thread | None:
        """Asks for attention on something in this commit: opens a discussion."""
        if not self.project:
            return None
        with ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2").style("width: 92vw; max-width: 36rem"):
            ui.label("Ask for attention").classes("text-base font-semibold")
            ui.label(f"About {chip_text(anchor)}" if anchor else "About the commit in general (pin something in "
                     "the viewer first to point at it)").classes("text-xs text-amber-300" if anchor else
                                                                "text-xs text-gray-400")
            title = ui.input("Title", placeholder="e.g. R704 is too close to the mounting hole").props(
                "dark dense outlined autofocus").classes("w-full").mark("request-title")
            body = ui.textarea(placeholder="What needs attention, and why. Markdown.").props(
                "dark outlined autogrow dense").classes("w-full text-sm").mark("request-body")
            ui.label("It stays open on every later commit until someone accepts it. Saved in reviews/threads/; "
                     "commit it to share it.").classes("text-xs text-gray-500")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
                go = ui.button("Ask for attention", icon="priority_high", on_click=lambda: dialog.submit(
                    ((title.value or "").strip(), (body.value or "").strip()))).props(
                    "unelevated color=red-5").mark("request-go")
                go.bind_enabled_from(title, "value", backward=lambda v: bool((v or "").strip()))
        dialog.open()
        got = await dialog
        dialog.delete()
        if not got:
            return None
        t = threads.start(self.project, got[0], got[1], commit, self.me, self.head, anchor)
        logs.log.info("discussion %s opened by %s on %s", t.id, self.me, commit[:7])
        ui.notify(f"Asked for attention: {t.title}", type="positive")
        self.changed()
        return t
