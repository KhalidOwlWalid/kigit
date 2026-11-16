"""The GUI for discussions (threads.py): the list behind the header's
Discussions button, one discussion as a chat with its status buttons, and
the "Request" composer that opens one from a review.

Messages are written to the discussion's file as soon as they're sent (no
Write step): the file is the conversation, shared through git.
"""

from __future__ import annotations

import getpass
from pathlib import Path
from typing import Awaitable, Callable

from nicegui import background_tasks, ui

from . import activity, logs, mentions, notices, review, threads
from .review import Anchor
from .md_editor import Editors, rewrite_assets
from .review_panel import chip_text, project_key

STATUS_LOOK = {"open": ("priority_high", "red-4"), "done": ("task_alt", "amber-5"), "accepted": ("verified", "green-5")}


def status_chip(status: str) -> None:
    icon, color = STATUS_LOOK[status]
    ui.chip(threads.LABELS[status], icon=icon, color=color).props("dense outline").classes("text-xs").mark(
        f"status-{status}")


HASH_LINK = "font-mono cursor-pointer underline decoration-dotted underline-offset-2 hover:text-amber-300"


class Discussions:
    """project: the project folder; me: your name (git user.name); head: HEAD's
    hash; focus(anchor): show it in the viewer; changed(): the list changed;
    compare(old, new, anchor): compare two commits and show the anchor."""

    def __init__(self, focus: Callable[[Anchor], None], changed: Callable[[], None],
                 compare: Callable[[str, str, Anchor | None], Awaitable[None]] | None = None,
                 editors: Editors | None = None, pinned: Callable[[], Anchor | None] | None = None,
                 open_review: Callable[[str], Awaitable[None]] | None = None) -> None:
        self.focus, self.changed, self.compare_cb = focus, changed, compare
        self.pinned = pinned or (lambda: None)  # what's pinned in the viewer now
        self.open_review = open_review  # open_review(review id): show that review
        self.editors = editors
        # The dialogs live here, not where they're opened from: a Request or a
        # row in the review panel is redrawn when a message is sent, and a
        # dialog inside it would go with it.
        self.host = ui.element("div")  # empty, so it takes no room
        self._thread_dialog = None
        self.warned: set[tuple[str, str]] = set()  # (where, discussion) already warned about
        ui.on("kigit_open_thread", lambda e: self.open_link(str(e.args)))
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
        if getattr(self, "_list_dialog", None) is not None:
            self._list_dialog.delete()  # the last one shown
        with self.host, ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2").style(
                "width: 92vw; max-width: 52rem"):
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
                        "click", lambda t=t: self.show_thread(t.id)).mark("discussion-row", f"discussion-{t.id}"):
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        status_chip(t.status)
                        ui.label(t.title).classes("text-sm font-semibold truncate")
                        ui.space()
                        ui.label(f"{len(t.messages)} message{'s' if len(t.messages) != 1 else ''}").classes(
                            "text-xs text-gray-500 whitespace-nowrap")
                        ui.button(icon="link").props("flat dense round size=xs color=grey-6").on(
                            "click.stop", lambda t=t: self.copy_link(t)).tooltip(
                            "Copy a link to this discussion").mark("discussion-row-link")
                    with ui.row().classes("w-full items-center gap-2 no-wrap text-xs text-gray-400"):
                        if t.anchor:
                            more = f" +{len(t.more)}" if t.more else ""
                            ui.label(chip_text(t.anchor) + more).classes("text-amber-300 whitespace-nowrap")
                        ui.label(f"opened by {t.by} on {t.commit[:7]} · {t.opened}").classes("truncate")
                    if last and last.text:
                        ui.label(f"{last.author}: {review.one_line(last.text)}").classes(
                            "text-xs text-gray-500 truncate w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=self._list_dialog.close).props("flat")

    # ------------------------------------------------------- one discussion
    def show_thread(self, thread_id: str) -> None:
        self.thread_id = thread_id
        self.editing: int | None = None  # the message (index) being edited
        self.renaming = False  # the title being edited
        self.reply = ""  # the reply being typed, kept while the chat redraws
        if self._thread_dialog is not None:
            self._thread_dialog.delete()  # the last one shown
        with self.host, ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2").style(
                "width: 92vw; max-width: 46rem"):
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
            if getattr(self, "renaming", False) and t.by == self.me:
                name = ui.input(value=t.title).props("dark dense outlined autofocus").classes(
                    "flex-grow text-base").mark("discussion-title-input")
                name.on("keydown.enter", lambda: self._rename(t, name.value))
                name.on("keydown.escape", lambda: self._renaming(False))
                ui.button(icon="check", on_click=lambda: self._rename(t, name.value)).props(
                    "flat dense round size=sm color=amber-5").mark("discussion-title-save")
                ui.button(icon="undo", on_click=lambda: self._renaming(False)).props(
                    "flat dense round size=sm").tooltip("Keep the title")
            else:
                ui.label(t.title).classes("text-base font-semibold").mark("discussion-title")
                if t.by == self.me:  # whoever opened it can rename it
                    ui.button(icon="edit", on_click=lambda: self._renaming(True)).props(
                        "flat dense round size=xs color=grey-6").tooltip("Rename this discussion").mark(
                        "discussion-rename")
            ui.space()
            ui.button(icon="link", on_click=lambda: self.copy_link(t)).props("flat dense round size=sm").tooltip(
                "Copy a link to this discussion: paste it into a review or another discussion").mark(
                "discussion-copy-link")
            ui.button(icon="close", on_click=self._thread_dialog.close).props("flat dense round size=sm")
        with ui.row().classes("w-full items-center gap-2 text-xs text-gray-400"):
            mine = t.by == self.me  # whoever opened it can change what it's about
            for i, a in enumerate(t.anchors):
                chip = ui.chip(chip_text(a), icon="my_location", removable=mine,
                               on_click=lambda a=a: self._focus(t, a)).props(
                    "dense outline color=amber-5 clickable").classes("text-xs").mark("discussion-anchor")
                chip.tooltip("Show it in the viewer")
                if mine:
                    chip.on("remove", lambda i=i: self._repoint(t, [x for j, x in enumerate(t.anchors) if j != i]))
            if mine:
                pinned = self.pinned()
                with ui.button(icon="edit_location_alt").props("flat dense round size=sm color=grey-5").mark(
                        "discussion-repoint"):
                    ui.tooltip("Change what this discussion is about")
                    with ui.menu():
                        what = chip_text(pinned) if pinned else "what's pinned (click something in the viewer first)"
                        add = ui.menu_item(f"Add {what}", on_click=lambda: self._repoint(t, t.anchors + [pinned])).mark(
                            "discussion-repoint-add")
                        item = ui.menu_item(f"Point it at {what} instead",
                                            on_click=lambda: self._repoint(t, [pinned])).mark("discussion-repoint-pinned")
                        add.set_enabled(pinned is not None and not any(review.same_thing(pinned, x) for x in t.anchors))
                        item.set_enabled(pinned is not None)
                        if t.anchors:
                            ui.menu_item("Make it about the commit in general",
                                         on_click=lambda: self._repoint(t, [])).mark("discussion-repoint-general")
            with ui.row().classes("items-baseline gap-1"):
                ui.label(f"Opened by {t.by} on commit")
                self._hash_link(t, t.commit)
                ui.label(f"· {t.opened}")
        self.check_links(" ".join(m.text for m in t.messages), f'The discussion "{t.title}"')
        with ui.scroll_area().classes("w-full").style("height: min(26rem, 50vh)") as area:
            # The chat, with where it was mentioned (links to it from other
            # discussions and reviews) in among the messages, by time.
            said = mentions.all_mentions(self.project).get(f"thread:{t.id}", [])
            timeline = sorted([(m.time, 0, i, m) for i, m in enumerate(t.messages)]
                              + [(x.time, 1, j, x) for j, x in enumerate(said)], key=lambda e: (e[0], e[1], e[2]))
            for _, is_mention, i, item in timeline:
                if is_mention:
                    self._mention(item)
                else:
                    self._message(t, i, item)
        if self.editing is None:
            area.scroll_to(percent=1.0)
        box = self._editor("Reply: what you changed, or a question. Markdown; paste, drop or click to add files.",
                           "discussion-reply", self.reply, lambda v: setattr(self, "reply", v))
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

    def _message(self, t: threads.Thread, index: int, m: threads.Message) -> None:
        mine = m.author == self.me
        verb = threads.VERB.get(m.kind, "")
        editing = mine and self.editing == index
        with ui.row().classes("w-full " + ("justify-end" if mine else "justify-start")):
            with ui.column().classes(("gap-1 w-full" if editing else "gap-0 max-w-[85%]") + " rounded-lg px-3 py-2 " +
                                     ("bg-[#2a2416]" if mine else "bg-[#1c2128]")).mark("discussion-message"):
                with ui.row().classes("items-baseline gap-2 w-full no-wrap"):
                    ui.label(m.author).classes("text-xs font-semibold")
                    ui.label(m.time).classes("text-[11px] text-gray-500")
                    if m.head:
                        ui.label("at").classes("text-[11px] text-gray-500 font-mono")
                        self._hash_link(t, m.head, "text-[11px] text-gray-500")
                    if m.edited:
                        ui.label("edited").classes("text-[11px] text-gray-500 italic").tooltip(
                            f"Edited {m.edited}").mark("discussion-edited")
                    if mine and not editing:
                        ui.space()
                        ui.button(icon="edit", on_click=lambda: self._start_edit(index)).props(
                            "flat dense round size=xs color=grey-6").tooltip("Edit your message").mark(
                            "discussion-edit")
                        if m.kind == "comment":
                            ui.button(icon="delete", on_click=lambda: self._delete(t, index, m)).props(
                                "flat dense round size=xs color=grey-6").tooltip("Delete your comment").mark(
                                "discussion-delete")
                if verb:
                    icon, color = STATUS_LOOK.get(threads.STATUS.get(m.kind, ""), ("my_location", "grey-5"))
                    with ui.row().classes("items-center gap-1"):
                        ui.icon(icon, color=color, size="xs")
                        ui.label(verb.capitalize()).classes("text-xs").classes(f"text-{color.split('-')[0]}-300")
                if editing:
                    box = self._editor("Your message. Markdown.", "discussion-edit-box", m.text)
                    with ui.row().classes("w-full justify-end gap-2"):
                        ui.button("Cancel", on_click=lambda: self._start_edit(None)).props("flat dense no-caps")
                        ui.button("Save", icon="check", on_click=lambda: self._save_edit(t, index, m, box)).props(
                            "unelevated dense no-caps color=amber-8").mark("discussion-edit-save")
                elif m.text:
                    ui.html(review.to_html(rewrite_assets(m.text, project_key(self.project)))).classes(
                        "kigit-md-view nicegui-markdown text-sm text-gray-200")

    # ------------------------------------------------------------- links
    def copy_link(self, t: threads.Thread) -> None:
        ui.clipboard.write(threads.link_markdown(t))
        logs.log.info("copied a link to discussion %s", t.id)
        ui.notify("Link copied: paste it into a review or another discussion", type="positive")

    def open_link(self, thread_id: str) -> None:
        """A discussion link was clicked: open it, or say it's gone."""
        if self.project and threads.exists(self.project, thread_id):
            self.show_thread(thread_id)
            return
        notices.warn(f"That discussion ({thread_id}) is gone: deleted, or not pulled yet",
                     f"reviews/threads/{thread_id}.md isn't there")

    def check_links(self, text: str, where: str) -> list[str]:
        """Warns (pop-up, log, bell) about links in `text` to discussions or
        reviews that are gone, once per place and link this session."""
        if not self.project:
            return []
        gone = [("discussion", i, f"reviews/threads/{i}.md") for i in threads.missing(self.project, text)]
        folder = review.folder(self.project)
        gone += [("review", i, f"reviews/{i}.md") for i in dict.fromkeys(review.REVIEW_LINK.findall(text or ""))
                 if not (folder / f"{i}.md").is_file()]
        for kind, i, file in gone:
            if (where, i) in self.warned:
                continue
            self.warned.add((where, i))
            notices.warn(f"{where} links to a {kind} that's gone ({i}): deleted, or not pulled yet",
                         f"{file} isn't there")
        return [i for _, i, _ in gone]

    def _renaming(self, on: bool) -> None:
        self.renaming = on
        self.thread_view.refresh()

    def _rename(self, t: threads.Thread, title: str) -> None:
        try:
            threads.rename(self.project, t.id, self.me, self.head, title or "")
        except (OSError, ValueError) as e:
            ui.notify(f"Couldn't rename it: {e}", type="warning")
            return
        logs.log.info("discussion %s renamed to %s", t.id, title)
        self.renaming = False
        self.thread_view.refresh()
        self.changed()

    def _repoint(self, t: threads.Thread, anchors: list) -> None:
        try:
            threads.repoint(self.project, t.id, self.me, self.head, [a for a in anchors if a])
        except (OSError, ValueError) as e:
            ui.notify(f"Couldn't change what it's about: {e}", type="warning")
            return
        logs.log.info("discussion %s now about %s", t.id, ", ".join(a.label for a in anchors if a) or "the commit")
        self.thread_view.refresh()
        self.changed()

    async def _delete(self, t: threads.Thread, index: int, m: threads.Message) -> None:
        with self.host, ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2 w-[26rem] max-w-full"):
            ui.label("Delete your comment?").classes("text-base font-semibold")
            ui.label(review.one_line(m.text)[:160] or "(no text)").classes("text-sm text-gray-400")
            ui.label("It's removed from the discussion's file. Anyone who already pulled it keeps it until they "
                     "pull again.").classes("text-xs text-gray-500")
            with ui.row().classes("w-full justify-end gap-2"):
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
                ui.button("Delete", icon="delete", on_click=lambda: dialog.submit(True)).props(
                    "unelevated color=red-8").mark("discussion-delete-confirm")
        dialog.open()
        sure = await dialog
        dialog.delete()
        if not sure:
            return
        try:
            threads.delete(self.project, t.id, index, self.me, m.time)
        except (OSError, ValueError) as e:
            ui.notify(f"Couldn't delete the comment: {e}", type="warning")
            return
        logs.log.info("discussion %s: message %d deleted by %s", t.id, index, self.me)
        self.editing = None
        self.thread_view.refresh()
        self.changed()

    def _mention(self, m: mentions.Mention) -> None:
        """'Author mentioned this in X': click to go there."""
        where = f'the discussion "{m.title}"' if m.kind == "discussion" else f'the review of "{m.title}"'
        with ui.row().classes("w-full justify-center items-center gap-1 text-xs text-gray-400 py-1 cursor-pointer "
                              "hover:text-purple-300").on("click", lambda: self._go_to(m)).mark("discussion-mention"):
            ui.icon("alternate_email", size="xs").classes("text-purple-300")
            ui.label(f"{m.author or 'Someone'} mentioned this in {where}").classes("underline decoration-dotted")
            ui.label(f"· {m.time}").classes("text-gray-500")

    def _go_to(self, m: mentions.Mention) -> None:
        if m.kind == "discussion":
            self.open_link(m.source)
        elif self.open_review is not None:
            self._thread_dialog.close()
            background_tasks.create(self.open_review(m.source))

    def _start_edit(self, index: int | None) -> None:
        self.editing = index
        self.thread_view.refresh()

    def _save_edit(self, t: threads.Thread, index: int, m: threads.Message, box: ui.textarea) -> None:
        self.check_links(box.value or "", "Your message")
        try:
            threads.edit(self.project, t.id, index, self.me, m.time, box.value or "")
        except (OSError, ValueError) as e:
            ui.notify(f"Couldn't change the message: {e}", type="warning")
            return
        logs.log.info("discussion %s: message %d edited by %s", t.id, index, self.me)
        self.editing = None
        self.thread_view.refresh()
        self.changed()

    def jump_pair(self, t: threads.Thread, at: str) -> tuple[str, str]:
        """What clicking commit `at` in discussion t compares: the commit it was
        opened on with `at`, so you see what happened to it since. `at` being
        that commit itself compares it with HEAD (where it stands now), and if
        that's HEAD too, the comparison it was pinned in."""
        if at != t.commit:
            return t.commit, at
        if self.head and self.head != t.commit:
            return t.commit, self.head
        seen = t.anchor.seen if t.anchor else None
        if seen and seen.old and seen.new:
            return seen.old, seen.new
        return t.commit + "~1", t.commit

    def _hash_link(self, t: threads.Thread | None, at: str, classes: str = "") -> None:
        if t is None:
            return
        old, new = self.jump_pair(t, at)
        what = chip_text(t.anchor) if t.anchor else "the change"
        link = ui.label(at[:7]).classes(f"{HASH_LINK} {classes}").on("click", lambda: self._jump(t, old, new))
        link.tooltip(f"Compare {old[:7]} with {new[:7]} and show {what}").mark("discussion-commit")

    async def _jump(self, t: threads.Thread, old: str, new: str) -> None:
        if not self.compare_cb:
            return
        self._thread_dialog.close()
        if getattr(self, "_list_dialog", None) is not None:
            self._list_dialog.close()  # the viewer is what you want to see now
        await self.compare_cb(old, new, t.anchor)

    def _editor(self, placeholder: str, mark: str, value: str = "",
                on_change: Callable[[str], None] | None = None) -> ui.textarea:
        """A Markdown editor (md_editor.py), or a plain box without one."""
        on_change = on_change or (lambda v: None)
        if self.editors is None:
            return ui.textarea(value=value, placeholder=placeholder, on_change=lambda e: on_change(e.value or "")).props(
                "dark outlined autogrow dense").classes("w-full text-sm").mark(mark)
        return self.editors.editor(value, on_change, placeholder, mark, project_key(self.project))

    def _focus(self, t: threads.Thread, anchor: Anchor | None = None) -> None:
        self._thread_dialog.close()
        self.focus(anchor or t.anchor)

    def _send(self, box: ui.textarea, kind: str) -> None:
        text = (box.value or "").strip()
        if kind == "comment" and not text:
            return
        self.check_links(text, "Your message")
        try:
            threads.add(self.project, self.thread_id, self.me, self.head, text, kind)
        except (OSError, ValueError) as e:
            ui.notify(f"Couldn't add to the discussion: {e}", type="warning")
            return
        logs.log.info("discussion %s: %s by %s", self.thread_id, kind, self.me)
        activity.record("reply")
        self.reply = ""
        self.thread_view.refresh()
        self.changed()

    # ------------------------------------------------------------- composer
    async def request(self, commit: str, anchor: Anchor | None) -> threads.Thread | None:
        """Asks for attention on something in this commit: opens a discussion."""
        if not self.project:
            return None
        with self.host, ui.dialog() as dialog, ui.card().classes("bg-[#161a20] gap-2").style(
                "width: 92vw; max-width: 36rem"):
            ui.label("Ask for attention").classes("text-base font-semibold")
            ui.label(f"About {chip_text(anchor)}" if anchor else "About the commit in general (pin something in "
                     "the viewer first to point at it)").classes("text-xs text-amber-300" if anchor else
                                                                "text-xs text-gray-400")
            title = ui.input("Title", placeholder="e.g. R704 is too close to the mounting hole").props(
                "dark dense outlined autofocus").classes("w-full").mark("request-title")
            body = self._editor("What needs attention, and why. Markdown; paste, drop or click to add files.",
                                "request-body")
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
        self.check_links(got[1], "Your request")
        t = threads.start(self.project, got[0], got[1], commit, self.me, self.head, anchor)
        logs.log.info("discussion %s opened by %s on %s", t.id, self.me, commit[:7])
        activity.record("discussion")
        ui.notify(f"Asked for attention: {t.title}", type="positive")
        self.changed()
        return t
