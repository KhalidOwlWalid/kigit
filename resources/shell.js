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
})();
