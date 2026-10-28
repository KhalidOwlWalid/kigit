// Source panel (--source): the old and new file text of changed items, side
// by side like a code diff. Shared by the PCB and schematic views: each makes
// a panel under its drawing and calls show() with the entries to list.
//
// An entry (from the backend, report/source.hpp):
//   { k: "track · GND", o: [file, firstLine, text] | null, n: [...] | null, cut?: 1 }
window.kigitSourcePanel = (() => {
  "use strict";
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const CONTEXT = 3;      // unchanged lines kept around a change
  const MAX_ENTRIES = 25; // more behind a "show more" button
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode etc. */ } },
  };

  // Line diff: longest common subsequence. Returns ops [type, oldIdx, newIdx]
  // with type "=" (both), "-" (old only), "+" (new only).
  function diffLines(a, b) {
    const n = a.length, m = b.length;
    // Same start and end lines are common anyway; diff only the middle.
    let pre = 0;
    while (pre < n && pre < m && a[pre] === b[pre]) pre++;
    let suf = 0;
    while (suf < n - pre && suf < m - pre && a[n - 1 - suf] === b[m - 1 - suf]) suf++;
    const A = a.slice(pre, n - suf), B = b.slice(pre, m - suf);
    const ops = [];
    for (let i = 0; i < pre; i++) ops.push(["=", i, i]);
    if (A.length * B.length > 4e6) {
      // Too big to compare line by line: show it all as replaced.
      A.forEach((_, i) => ops.push(["-", pre + i, -1]));
      B.forEach((_, j) => ops.push(["+", -1, pre + j]));
    } else {
      const w = B.length + 1;
      const L = new Uint32Array((A.length + 1) * w);
      for (let i = A.length - 1; i >= 0; i--)
        for (let j = B.length - 1; j >= 0; j--)
          L[i * w + j] = A[i] === B[j] ? L[(i + 1) * w + j + 1] + 1 : Math.max(L[(i + 1) * w + j], L[i * w + j + 1]);
      let i = 0, j = 0;
      while (i < A.length || j < B.length) {
        if (i < A.length && j < B.length && A[i] === B[j]) { ops.push(["=", pre + i, pre + j]); i++; j++; }
        else if (j < B.length && (i === A.length || L[i * w + j + 1] >= L[(i + 1) * w + j])) { ops.push(["+", -1, pre + j]); j++; }
        else { ops.push(["-", pre + i, -1]); i++; }
      }
    }
    for (let k = 0; k < suf; k++) ops.push(["=", n - suf + k, m - suf + k]);
    return ops;
  }

  // Side-by-side rows: a run of removed lines next to the added lines that
  // replace them, like VS Code. Row: {o, n} line indexes (-1 = blank), eq.
  function sideBySide(ops) {
    const rows = [];
    for (let k = 0; k < ops.length;) {
      if (ops[k][0] === "=") { rows.push({ o: ops[k][1], n: ops[k][2], eq: true }); k++; continue; }
      const dels = [], adds = [];
      while (k < ops.length && ops[k][0] !== "=") {
        if (ops[k][0] === "-") dels.push(ops[k][1]); else adds.push(ops[k][2]);
        k++;
      }
      for (let r = 0; r < Math.max(dels.length, adds.length); r++)
        rows.push({ o: r < dels.length ? dels[r] : -1, n: r < adds.length ? adds[r] : -1, eq: false });
    }
    return rows;
  }

  // The part of a changed line that differs from its counterpart, marked.
  function markChange(text, other) {
    if (other === null) return esc(text);
    let p = 0;
    while (p < text.length && p < other.length && text[p] === other[p]) p++;
    let s = 0;
    while (s < text.length - p && s < other.length - p && text[text.length - 1 - s] === other[other.length - 1 - s]) s++;
    if (p + s >= text.length) return esc(text);
    return esc(text.slice(0, p)) + `<span class="ch">${esc(text.slice(p, text.length - s))}</span>` + esc(text.slice(text.length - s));
  }

  function renderEntry(e, focused) {
    const oLines = e.o ? e.o[2].split("\n") : [], nLines = e.n ? e.n[2].split("\n") : [];
    const ops = e.o && e.n ? diffLines(oLines, nLines)
      : e.o ? oLines.map((_, i) => ["-", i, -1]) : nLines.map((_, j) => ["+", -1, j]);
    const rows = sideBySide(ops);
    const o0 = e.o ? e.o[1] : 0, n0 = e.n ? e.n[1] : 0;
    const changed = rows.some((r) => !r.eq);

    const cell = (side, idx, row) => {
      const lines = side === "o" ? oLines : nLines, first = side === "o" ? o0 : n0;
      if (idx < 0) return `<td class="ln"></td><td class="tx fill"></td>`;
      const cls = row.eq ? "" : side === "o" ? "del" : "ins";
      const otherIdx = side === "o" ? row.n : row.o, otherLines = side === "o" ? nLines : oLines;
      const text = row.eq ? esc(lines[idx]) : markChange(lines[idx], otherIdx >= 0 ? otherLines[otherIdx] : null);
      return `<td class="ln ${cls}">${first + idx}</td><td class="tx ${cls}">${text || " "}</td>`;
    };
    const rowHtml = (r, fold = -1) =>
      `<tr${fold >= 0 ? ` data-f="${fold}" hidden` : ""}>${cell("o", r.o, r)}${cell("n", r.n, r)}</tr>`;
    let folds = 0;

    // Fold long unchanged stretches, keeping CONTEXT lines next to changes.
    let body = "";
    for (let i = 0; i < rows.length;) {
      if (!rows[i].eq || !changed) { body += rowHtml(rows[i]); i++; continue; }
      let j = i;
      while (j < rows.length && rows[j].eq) j++;
      const keepHead = i === 0 ? 0 : CONTEXT, keepTail = j === rows.length ? 0 : CONTEXT;
      if (j - i > keepHead + keepTail + 1) {
        for (let k = i; k < i + keepHead; k++) body += rowHtml(rows[k]);
        const f = folds++;
        body += `<tr class="folded" data-f="${f}"><td colspan="4">⋯ ${j - i - keepHead - keepTail} unchanged lines (click to show)</td></tr>` +
          rows.slice(i + keepHead, j - keepTail).map((r) => rowHtml(r, f)).join("");
        for (let k = j - keepTail; k < j; k++) body += rowHtml(rows[k]);
      } else {
        for (let k = i; k < j; k++) body += rowHtml(rows[k]);
      }
      i = j;
    }

    const where = (s) => s ? `${esc(s[0])}:${s[1]}` : "—";
    const status = !e.o ? `<span class="badge st1">ADDED</span>` : !e.n ? `<span class="badge st2">REMOVED</span>`
      : changed ? `<span class="badge st3">CHANGED</span>` : `<span class="badge st0">TEXT UNCHANGED</span>`;
    let note = "";
    if (e.o && e.n && !changed) note = `<div class="src-note">Same text in both files: it moved because something it belongs to moved (e.g. its footprint).</div>`;
    if (e.cut) note += `<div class="src-note">Shown up to the copper fill: the filled polygons KiCad computes are left out.</div>`;
    return `<div class="src-entry${focused ? " focus" : ""}">` +
      `<div class="src-head"><span class="k">${esc(e.k)}</span>${status}` +
      `<span class="where"><span class="o">${where(e.o)}</span> → <span class="n">${where(e.n)}</span></span></div>` + note +
      `<table class="sd"><colgroup><col class="c-ln"><col><col class="c-ln"><col></colgroup><tbody>${body}</tbody></table></div>`;
  }

  // A panel at the bottom of `view` (the .view element); `entries` is the
  // view's whole list, shown items are given by index.
  function create(view, entries, key) {
    const dock = document.createElement("div");
    dock.className = "srcdock";
    dock.innerHTML =
      `<div class="src-grip" title="Drag to resize"></div>` +
      `<div class="src-bar"><button class="src-toggle" title="Show or hide the source panel">Source</button>` +
      `<span class="src-title"></span><span class="src-files"></span></div>` +
      `<div class="src-body"></div>`;
    view.appendChild(dock);
    const body = dock.querySelector(".src-body"), title = dock.querySelector(".src-title");

    // Size and open/closed, remembered per view.
    const sizeKey = `kigit.src.${key}.h`, openKey = `kigit.src.${key}.open`;
    // Room is left for the drawing; a hidden view (the other tab) has no height yet, so no limit then.
    const setHeight = (h) => {
      const max = view.clientHeight ? view.clientHeight - 120 : h;
      dock.style.height = Math.round(Math.max(90, Math.min(h, max))) + "px";
    };
    setHeight(+(store.get(sizeKey) || 260));
    const setOpen = (open) => { dock.classList.toggle("closed", !open); store.set(openKey, open ? "1" : "0"); };
    setOpen(store.get(openKey) !== "0");
    dock.querySelector(".src-toggle").onclick = () => setOpen(dock.classList.contains("closed"));
    const grip = dock.querySelector(".src-grip");
    grip.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      grip.setPointerCapture(e.pointerId);
      const y0 = e.clientY, h0 = dock.offsetHeight;
      const move = (ev) => setHeight(h0 + (y0 - ev.clientY));
      const up = () => { grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); store.set(sizeKey, dock.offsetHeight); };
      grip.addEventListener("pointermove", move);
      grip.addEventListener("pointerup", up);
    });
    body.addEventListener("click", (e) => {
      const f = e.target.closest(".folded");
      if (f) {
        f.closest("table").querySelectorAll(`tr[data-f="${f.dataset.f}"]`).forEach((r) => { r.hidden = false; });
        f.remove();
        return;
      }
      const more = e.target.closest(".src-more");
      if (more) { more.remove(); body.insertAdjacentHTML("beforeend", pending.map((i) => entryHtml(i, false)).join("")); pending = []; }
    });

    let shownKey = null, pending = [];
    const cache = new Map(); // entry index -> html
    const entryHtml = (i, focused) => {
      if (focused) return renderEntry(entries[i], true);
      if (!cache.has(i)) cache.set(i, renderEntry(entries[i], false));
      return cache.get(i);
    };
    function placeholder(text) {
      body.innerHTML = `<div class="src-empty">${text}</div>`;
    }
    placeholder("Hover a changed item to see its text in the old and new file.");

    return {
      // Shows these entries (indexes into `entries`) under `heading`. `focus`:
      // the one under the cursor, listed first and outlined. Same key: no redraw.
      show(list, heading, focus = -1, showKey = null) {
        const k = showKey ?? heading + "|" + focus + "|" + list.join(",");
        if (k === shownKey) return;
        shownKey = k;
        title.innerHTML = heading;
        const ids = [...new Set(focus >= 0 ? [focus, ...list] : list)].filter((i) => i >= 0 && entries[i]);
        if (!ids.length) { placeholder("No changes in the files for this."); return; }
        const first = ids.slice(0, MAX_ENTRIES);
        pending = ids.slice(MAX_ENTRIES);
        body.innerHTML = first.map((i) => entryHtml(i, i === focus)).join("") +
          (pending.length ? `<button class="src-more">Show ${pending.length} more</button>` : "");
        body.scrollTop = 0;
        const files = new Set(ids.flatMap((i) => [entries[i].o?.[0], entries[i].n?.[0]]).filter(Boolean));
        dock.querySelector(".src-files").textContent = `${ids.length} change${ids.length === 1 ? "" : "s"} · ${[...files].join(", ")}`;
      },
    };
  }

  return { create };
})();
