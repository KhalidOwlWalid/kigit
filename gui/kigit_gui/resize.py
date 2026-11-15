"""Resizable side panels: drag a drawer's inner edge to change its width.

The width changes in the browser while dragging, is sent to the server when
the drag ends, and is remembered in the browser (localStorage) for next time.
"""

from __future__ import annotations

from nicegui import ui

_PAGE_JS = """
<style>
.kigit-grip { position: absolute; top: 0; bottom: 0; width: 6px; cursor: ew-resize; z-index: 10;
              background: transparent; transition: background .15s; touch-action: none; }
.kigit-grip:hover, .kigit-grip.dragging { background: #e8b84d55; }
.kigit-grip[data-side=left] { right: 0; }
.kigit-grip[data-side=right] { left: 0; }
.q-drawer { container-type: inline-size; } /* contents can size to the drawer (cqw) */
</style>
<script>
(() => {
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode etc. */ } },
  };
  // At least VIEWER px stay for the middle, counting the other open drawers
  // (a closed drawer is moved off screen).
  const VIEWER = 400;
  const others = (g) => [...document.querySelectorAll(".kigit-grip")].filter((o) => o !== g).reduce((sum, o) => {
    const r = o.closest(".q-drawer")?.getBoundingClientRect();
    return sum + (r && r.right > 1 && r.left < innerWidth - 1 ? r.width : 0);
  }, 0);
  const clamp = (g, w) => Math.round(Math.max(+g.dataset.min, Math.min(+g.dataset.max, w, innerWidth - others(g) - VIEWER)));
  // Sets a drawer's width in the page now (NiceGUI's element store).
  const apply = (g, w) => {
    const el = typeof mounted_app !== "undefined" && mounted_app && mounted_app.elements[g.dataset.drawer];
    if (el) el.props.width = w;
  };
  const done = (g, w) => { store.set("kigit.panel." + g.dataset.key, w); emitEvent("kigit_panel_width", { id: +g.dataset.drawer, width: w }); };

  document.addEventListener("pointerdown", (e) => {
    const g = e.target.closest && e.target.closest(".kigit-grip");
    if (!g || e.button !== 0) return;
    e.preventDefault();
    g.setPointerCapture(e.pointerId); // keeps the drag even over the viewer's iframe
    g.classList.add("dragging");
    let w = null;
    const move = (ev) => {
      w = clamp(g, g.dataset.side === "left" ? ev.clientX : innerWidth - ev.clientX);
      apply(g, w);
    };
    const up = () => {
      g.classList.remove("dragging");
      g.removeEventListener("pointermove", move);
      g.removeEventListener("pointerup", up);
      g.removeEventListener("pointercancel", up);
      if (w !== null) done(g, w);
    };
    g.addEventListener("pointermove", move);
    g.addEventListener("pointerup", up);
    g.addEventListener("pointercancel", up);
  });
  // Double-click: back to the default width.
  document.addEventListener("dblclick", (e) => {
    const g = e.target.closest && e.target.closest(".kigit-grip");
    if (!g) return;
    apply(g, +g.dataset.default);
    done(g, +g.dataset.default);
  });

  // Restore the remembered widths once the page is up.
  let tries = 0;
  const restore = setInterval(() => {
    const grips = document.querySelectorAll(".kigit-grip");
    if ((grips.length && typeof mounted_app !== "undefined" && mounted_app) || ++tries > 100) {
      clearInterval(restore);
      grips.forEach((g) => {
        const saved = +store.get("kigit.panel." + g.dataset.key);
        if (saved) { const w = clamp(g, saved); apply(g, w); emitEvent("kigit_panel_width", { id: +g.dataset.drawer, width: w }); }
      });
    }
  }, 100);
})();
</script>
"""


class Resizer:
    """Makes drawers on this page resizable. One per page."""

    def __init__(self) -> None:
        self.drawers: dict[int, ui.drawer] = {}
        ui.add_body_html(_PAGE_JS)
        ui.on("kigit_panel_width", self._on_width)

    def add(self, drawer, side: str, key: str, width: int, min_width: int = 260, max_width: int = 1100) -> None:
        """drawer: a left (side="left") or right drawer of `width` px. key:
        what its width is remembered as."""
        self._set(drawer, width)
        self.drawers[drawer.id] = drawer
        with drawer:
            ui.element("div").classes("kigit-grip q-mini-drawer-hide").props(
                f'data-drawer="{drawer.id}" data-side="{side}" data-key="{key}" data-default="{width}" '
                f'data-min="{min_width}" data-max="{max_width}" title="Drag to resize, double-click to reset"'
            ).mark(f"grip-{key}")

    def _on_width(self, e) -> None:
        args = e.args if isinstance(e.args, dict) else {}
        drawer = self.drawers.get(args.get("id"))
        width = args.get("width")
        if drawer is not None and isinstance(width, (int, float)) and width > 0:
            self._set(drawer, int(width))

    @staticmethod
    def _set(drawer, width: int) -> None:
        drawer._props["width"] = width  # a number, as Quasar expects (props("width=N") gives a string)
        drawer.update()
