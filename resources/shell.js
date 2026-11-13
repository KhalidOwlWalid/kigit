// Tabs: PCB / Schematic. The choice is kept in the URL (#sch) so a reload
// stays on the same view.
(() => {
  "use strict";
  const buttons = document.querySelectorAll(".tabs [data-tab]");
  function show(name) {
    const btn = document.querySelector(`.tabs [data-tab="${name}"]`);
    if (!btn || btn.disabled) name = "pcb";
    document.body.dataset.tab = name;
    buttons.forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    if (name === "sch" && window.kigitShowSchematic) window.kigitShowSchematic();
    if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  }
  buttons.forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));

  const changedNets = DATA.nets.filter((n) => n.add + n.rem + n.vAdd + n.vRem + n.pAdd + n.pRem > 0).length;
  document.querySelector("#pcbTabN").textContent = changedNets ? changedNets : "";

  show(location.hash === "#sch" ? "sch" : "pcb");

  // The sidebar's width: drag its right edge, double-click to reset.
  // Remembered in localStorage, like the source panel's height.
  (() => {
    const app = document.querySelector("#app"), aside = app && app.querySelector("aside");
    if (!aside) return;
    const KEY = "kigit.asideWidth";
    const get = () => { try { return +localStorage.getItem(KEY); } catch { return 0; } };
    const put = (w) => { try { w ? localStorage.setItem(KEY, w) : localStorage.removeItem(KEY); } catch { /* private mode */ } };
    const clamp = (w) => Math.round(Math.max(220, Math.min(w, innerWidth * 0.7)));
    const set = (w) => {
      if (w) app.style.setProperty("--aside-w", clamp(w) + "px"); else app.style.removeProperty("--aside-w");
      window.dispatchEvent(new Event("resize")); // the views refit
    };
    if (get()) set(get());
    const grip = document.createElement("div");
    grip.className = "aside-grip";
    grip.title = "Drag to resize, double-click to reset";
    aside.appendChild(grip);
    grip.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      grip.setPointerCapture(e.pointerId);
      grip.classList.add("dragging");
      const left = aside.getBoundingClientRect().left;
      let w = 0;
      const move = (ev) => { w = clamp(ev.clientX - left); set(w); };
      const up = () => {
        grip.classList.remove("dragging");
        grip.removeEventListener("pointermove", move);
        grip.removeEventListener("pointerup", up);
        grip.removeEventListener("pointercancel", up);
        if (w) put(w);
      };
      grip.addEventListener("pointermove", move);
      grip.addEventListener("pointerup", up);
      grip.addEventListener("pointercancel", up);
    });
    grip.addEventListener("dblclick", () => { put(0); set(0); });
  })();

  // Inside the GUI: show a review note's anchor when asked. pcb.js and
  // sch.js fill window.kigitFocus; they tell the GUI what's pinned.
  window.addEventListener("message", (e) => {
    const m = e.data;
    if (e.source !== window.parent || !m || m.kigit !== "focus" || !m.anchor) return;
    const focus = (window.kigitFocus || {})[m.anchor.tab];
    if (!focus) return;
    show(m.anchor.tab);
    const found = focus(m.anchor);
    window.parent.postMessage({ kigit: "focused", anchor: m.anchor, found }, "*");
  });
})();
