"""Hiding the side panels (the commit list, the review panel).

A hidden panel folds to a narrow rail on its edge (Quasar's "mini" drawer)
with the panel's name and a chevron, so it's always clear where it went and
one click brings it back. The panel's own header has the chevron that hides
it. Hidden or not is remembered in the browser (localStorage
`kigit.hidden.<key>`), per port like the other display settings.
"""

from __future__ import annotations

from typing import Callable

from nicegui import ui

RAIL_WIDTH = 34  # px, a hidden panel's rail

_PAGE_JS = """
<style>
.kigit-rail { height: 100%; width: 100%; display: flex; flex-direction: column; align-items: center; gap: 10px;
  padding-top: 8px; cursor: pointer; color: #9aa4b2; user-select: none; }
.kigit-rail:hover { background: #1c2128; color: #e8b84d; }
.kigit-rail .kigit-rail-name { writing-mode: vertical-rl; font-size: 12px; letter-spacing: .06em; }
.kigit-rail-left .kigit-rail-name { transform: rotate(180deg); }
</style>
<script>
(() => {
  let tries = 0;
  const restore = setInterval(() => {
    if (typeof mounted_app !== "undefined" && mounted_app) {
      clearInterval(restore);
      for (const key of %%KEYS%%) {
        let v = null;
        try { v = localStorage.getItem("kigit.hidden." + key); } catch { /* private mode */ }
        if (v === "1") emitEvent("kigit_panel_hidden", { key, hidden: true });
      }
    } else if (++tries > 100) clearInterval(restore);
  }, 100);
})();
</script>
"""


class Panels:
    """The page's hideable side panels. One per page."""

    def __init__(self) -> None:
        self.setters: dict[str, Callable[[bool], None]] = {}
        self.hidden: dict[str, bool] = {}
        ui.on("kigit_panel_hidden", self._restored)

    def finish(self) -> None:
        """After every add(): restores what was hidden last time."""
        keys = "[" + ",".join(f'"{k}"' for k in self.setters) + "]"
        ui.add_body_html(_PAGE_JS.replace("%%KEYS%%", keys))

    def add(self, drawer, key: str, name: str, side: str, on_change: Callable[[bool], None] | None = None) -> None:
        """drawer: a left or right drawer. Adds its rail (shown while hidden).
        Put `.classes("q-mini-drawer-hide")` on the drawer's normal contents."""
        drawer.props(f"mini-width={RAIL_WIDTH}")
        with drawer:
            with ui.element("div").classes(f"kigit-rail kigit-rail-{side} q-mini-drawer-only").props(
                    f'title="Show the {name.lower()}"').on("click", lambda: self.set(key, False)) as rail:
                ui.icon("chevron_right" if side == "left" else "chevron_left", size="sm")
                ui.label(name).classes("kigit-rail-name")
            rail.mark(f"{key}-rail")

        def setter(hidden: bool) -> None:
            drawer.props("mini") if hidden else drawer.props(remove="mini")
            if on_change:
                on_change(hidden)
        self.setters[key] = setter
        self.hidden[key] = False

    def set(self, key: str, hidden: bool, remember: bool = True) -> None:
        self.hidden[key] = hidden
        self.setters[key](hidden)
        if remember:
            ui.run_javascript(f'try {{ localStorage.setItem("kigit.hidden.{key}", "{1 if hidden else 0}") }} catch {{}}')

    def toggle(self, key: str) -> None:
        self.set(key, not self.hidden[key])

    def _restored(self, e) -> None:
        args = e.args if isinstance(e.args, dict) else {}
        if args.get("key") in self.setters:
            self.set(args["key"], bool(args.get("hidden")), remember=False)
