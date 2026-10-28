// PCB view: copper per layer, coloured by diff status, hover a net to highlight it.
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const { meta, layers, nets, items, zones, outline } = DATA;
  const svg = $("#board");
  // Status codes from the backend (diff.hpp): 3 = only moved, 4 = where it used
  // to be (ghost), 5 = the same item with different copper (changed in place).
  const STATUS = ["unchanged", "added", "removed", "moved", "old position", "changed"];
  const BADGE = [0, 1, 2, 5, 6, 3]; // badge colour classes shared with the schematic view
  const footprints = DATA.footprints || [], zoneChanges = DATA.zone_changes || [];
  const INNER_COLORS = ["#d9a03f", "#5cb86e", "#b673e0", "#48c2c6", "#e07ab8", "#9eab4c", "#7f8fe8", "#e0865a"];

  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const netName = (n) => (nets[n].name === "" ? "(no net)" : nets[n].name);
  const mm = (v) => (Math.round(v * 100) / 100).toFixed(2);
  const changeCount = (s) => s.add + s.rem + s.vAdd + s.vRem + s.pAdd + s.pRem + (s.changed || 0);

  let inner = 0;
  const layerColor = layers.map((l) =>
    l.name === "F.Cu" ? "#d65a4f" : l.name === "B.Cu" ? "#4d8fe0" : INNER_COLORS[inner++ % INNER_COLORS.length]);

  // ---------- header ----------
  document.title = `kigit · ${meta.board} · ${meta.old.short} → ${meta.new.short}`;
  $("#boardName").textContent = meta.board;
  $("#oldHash").textContent = meta.old.short;
  $("#newHash").textContent = meta.new.short;
  $("#oldSubj").textContent = meta.old.subject;
  $("#newSubj").textContent = meta.new.subject;
  $("#oldSubj").title = meta.old.subject + (meta.old.date ? "\n" + meta.old.date : "");
  $("#newSubj").title = meta.new.subject + (meta.new.date ? "\n" + meta.new.date : "");
  $("#oldHash").title = meta.old.path || "";
  $("#newHash").title = meta.new.path || "";
  if (meta.warnings && meta.warnings.length) {
    $("#warnings").innerHTML = `<div class="warn"><b>⚠ Board file location changed</b>` +
      meta.warnings.map((w) => `<p>${esc(w)}</p>`).join("") + `</div>`;
  }

  // ---------- draw ----------
  const perLayer = layers.map(() => ({ zones: "", pads: ["", "", "", "", "", ""], tracks: ["", "", "", "", "", ""], hits: "" }));
  let vias = "", holes = "";

  // Silkscreen (only present when compared with --silkscreen / "Include
  // silkscreen"): back side underneath, front on top; text in KiCad's place,
  // size and justification (a browser font, so not KiCad's exact strokes).
  function silkSvg() {
    const silk = DATA.silk;
    if (!silk) return "";
    const order = [0, 3, 2, 1]; // unchanged, moved, removed, added on top
    const side = (front) => {
      let out = "";
      for (const st of order)
        for (const it of silk) {
          if (it.f !== front || it.s !== st) continue;
          if (it.d !== undefined) {
            out += `<path class="silk st${it.s}${it.fl ? " fill" : ""}" d="${it.d}" stroke-width="${Math.max(it.w, 0.05)}"/>`;
          } else {
            const anchor = it.h < 0 ? "start" : it.h > 0 ? "end" : "middle";
            const base = it.v < 0 ? "hanging" : it.v > 0 ? "alphabetic" : "central";
            const mirror = it.m ? ` scale(-1 1)` : "";
            const lines = String(it.t).split("\n");
            const lh = it.sz * 1.6;
            const shift = it.v > 0 ? -(lines.length - 1) * lh : it.v < 0 ? 0 : -((lines.length - 1) * lh) / 2;
            out += `<text class="silk-text st${it.s}" transform="translate(${it.x} ${it.y}) rotate(${-it.a})${mirror}" ` +
              `font-size="${it.sz * 1.38}" text-anchor="${anchor}" dominant-baseline="${base}" ` +
              `style="font-weight:${it.th / it.sz > 0.17 ? 700 : 400}">` +
              lines.map((l, k) => `<tspan x="0" dy="${k === 0 ? shift : lh}">${esc(l)}</tspan>`).join("") + `</text>`;
          }
        }
      return out;
    };
    return `<g class="silklayer back" data-side="B">${side(0)}</g><g class="silklayer front" data-side="F">${side(1)}</g>`;
  }

  function padSvg(it, i) {
    const cls = `it pad st${it.s}`, at = `data-i="${i}"${it.fp !== undefined ? ` data-fp="${it.fp}"` : ""}`;
    const tf = `transform="translate(${it.x} ${it.y}) rotate(${-it.a})"`;
    if (it.shape === "circle") return `<circle class="${cls}" ${at} cx="${it.x}" cy="${it.y}" r="${it.sw / 2}"/>`;
    let r = 0;
    const m = Math.min(it.sw, it.sh);
    if (it.shape === "oval") r = m / 2;
    else if (it.shape === "roundrect") r = (it.rr || 0.25) * m;
    return `<rect class="${cls}" ${at} ${tf} x="${-it.sw / 2}" y="${-it.sh / 2}" width="${it.sw}" height="${it.sh}" rx="${r}"/>`;
  }

  items.forEach((it, i) => {
    if (it.k === "t" || it.k === "a") {
      for (const l of it.l) {
        perLayer[l].tracks[it.s] += `<path class="it trk st${it.s}" data-i="${i}" d="${it.d}" stroke-width="${it.w}"/>`;
        perLayer[l].hits += `<path class="hit st${it.s}" data-i="${i}" d="${it.d}"/>`;
      }
    } else if (it.k === "p") {
      for (const l of it.l) perLayer[l].pads[it.s] += padSvg(it, i);
      if (it.dr > 0) holes += `<circle class="hole ph st${it.s}" cx="${it.x}" cy="${it.y}" r="${it.dr / 2}"/>`;
    } else if (it.k === "v") {
      vias += `<circle class="it via st${it.s}" data-i="${i}" data-l="${it.l.join(",")}" cx="${it.x}" cy="${it.y}" r="${it.w / 2}"/>`;
      holes += `<circle class="hole vh st${it.s}" cx="${it.x}" cy="${it.y}" r="${it.dr / 2}"/>`;
    }
  });
  zones.forEach((z) => {
    for (const l of z.l) perLayer[l].zones += `<path class="zone" data-n="${z.n}" d="${z.d}"/>`;
  });

  // Unchanged first, then removed, then added on top.
  // Old positions underneath, then unchanged, moved, removed, and added on top.
  const ORDER = [4, 0, 3, 5, 2, 1];
  const layerOrder = layers.map((_, i) => i).reverse(); // bottom layer drawn first
  svg.innerHTML =
    `<g id="world">` +
    layerOrder.map((l) => {
      const p = perLayer[l];
      return `<g class="layer" data-l="${l}" style="--lc:${layerColor[l]}">` +
        `<g>${p.zones}</g><g>${ORDER.map((s) => p.pads[s]).join("")}</g>` +
        `<g>${ORDER.map((s) => p.tracks[s]).join("")}</g><g>${p.hits}</g></g>`;
    }).join("") +
    `<g id="vias">${vias}</g><g>${holes}</g>` + silkSvg() +
    `<g class="outline">${outline.map((d) => `<path d="${d}"/>`).join("")}</g></g>`;

  // Elements per net, for highlighting.
  const netEls = nets.map(() => []);
  svg.querySelectorAll(".it, .zone").forEach((el) => {
    const n = el.dataset.i !== undefined ? items[+el.dataset.i].n : +el.dataset.n;
    netEls[n].push(el);
  });

  // ---------- view box: zoom & pan ----------
  let vb = { x: 0, y: 0, w: 100, h: 100 };
  const applyVB = () => svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  function fitBox(b, pad = 0.06) {
    const r = svg.getBoundingClientRect();
    const aspect = r.width / Math.max(r.height, 1);
    let w = Math.max(b.width, 1) * (1 + 2 * pad), h = Math.max(b.height, 1) * (1 + 2 * pad);
    if (w / h < aspect) w = h * aspect; else h = w / aspect;
    vb = { x: b.x + b.width / 2 - w / 2, y: b.y + b.height / 2 - h / 2, w, h };
    applyVB();
  }
  const outlineEl = svg.querySelector(".outline");
  const boardBox = () => (outline.length ? outlineEl : svg.querySelector("#world")).getBBox();
  const fitAll = () => fitBox(boardBox());

  function toWorld(e) {
    const p = svg.createSVGPoint();
    p.x = e.clientX; p.y = e.clientY;
    return p.matrixTransform(svg.getScreenCTM().inverse());
  }
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const k = Math.exp(e.deltaY * (e.deltaMode ? 0.05 : 0.0015));
    const p = toWorld(e);
    vb = { x: p.x - (p.x - vb.x) * k, y: p.y - (p.y - vb.y) * k, w: vb.w * k, h: vb.h * k };
    applyVB();
  }, { passive: false });

  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 && e.button !== 1) return;
    drag = { x: e.clientX, y: e.clientY, vb: { ...vb }, moved: false, scale: 1 / svg.getScreenCTM().a };
  });
  svg.addEventListener("pointermove", (e) => {
    if (drag) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) > 3) {
        // Capture only once it's a real drag, so a plain click still hits the item under the cursor.
        drag.moved = true;
        svg.setPointerCapture(e.pointerId);
        svg.classList.add("panning");
        hideTip();
      }
      if (drag.moved) {
        vb = { ...drag.vb, x: drag.vb.x - dx * drag.scale, y: drag.vb.y - dy * drag.scale };
        applyVB();
        return;
      }
    }
    hover(e);
  });
  svg.addEventListener("pointerup", (e) => {
    const wasDrag = drag && drag.moved;
    drag = null;
    svg.classList.remove("panning");
    if (!wasDrag && e.button === 0) {
      const n = netAt(e);
      pin(n === null || n === pinned ? null : n);
    }
  });
  svg.addEventListener("pointerleave", () => { hideTip(); setHover(null); });

  // Pads per footprint (for the footprint list).
  const fpEls = new Map();
  svg.querySelectorAll("[data-fp]").forEach((el) => {
    const f = +el.dataset.fp;
    if (!fpEls.has(f)) fpEls.set(f, []);
    fpEls.get(f).push(el);
  });

  // ---------- highlight ----------
  let hovered = null, pinned = null, shown = null;
  // Highlights one footprint's pads instead of a net (null: back to nets).
  function setFootprint(f) {
    svg.querySelectorAll(".on").forEach((el) => el.classList.remove("on"));
    shown = null;
    svg.classList.remove("hl");
    if (f === null) { refreshHL(); return; }
    (fpEls.get(f) || []).forEach((el) => el.classList.add("on"));
    svg.classList.add("hl");
  }
  function refreshHL() {
    const target = hovered !== null ? hovered : pinned;
    if (target === shown) return;
    if (shown !== null) netEls[shown].forEach((el) => el.classList.remove("on"));
    if (target !== null) netEls[target].forEach((el) => el.classList.add("on"));
    svg.classList.toggle("hl", target !== null);
    shown = target;
    document.querySelectorAll(".net.cur").forEach((r) => r.classList.remove("cur"));
    if (target !== null) rowFor(target)?.classList.add("cur");
  }
  const setHover = (n) => { hovered = n; refreshHL(); };
  function pin(n) {
    pinned = n;
    document.querySelectorAll(".net.pin").forEach((r) => r.classList.remove("pin"));
    if (n !== null) {
      const row = rowFor(n);
      if (row) { row.classList.add("pin"); row.scrollIntoView({ block: "nearest" }); }
    }
    renderCard();
    refreshHL();
  }

  function netAt(e) {
    const el = e.target.closest && e.target.closest("[data-i]");
    return el ? items[+el.dataset.i].n : null;
  }

  // ---------- tooltip ----------
  const tip = $("#tip");
  const hideTip = () => { tip.style.display = "none"; };
  function layerName(i) { return layers[i] ? layers[i].display : "?"; }
  function describe(it) {
    const lay = it.l.map(layerName);
    if (it.k === "t" || it.k === "a")
      return `${it.k === "a" ? "Arc" : "Track"} · ${it.w} mm wide · ${lay[0]} · ${mm(it.len)} mm long`;
    if (it.k === "v") return `Via · ⌀${it.w} / ${it.dr} mm · ${lay[0]}–${lay[lay.length - 1]}`;
    if (it.k === "p") return `Pad ${it.ref || "?"}.${it.pin} · ${it.shape} ${it.sw}×${it.sh} mm · ${lay.length > 2 ? "all layers" : lay.join(", ")}`;
    return "";
  }
  function netSummary(s) {
    const parts = [];
    if (s.add || s.rem) parts.push(`tracks ${s.add ? "+" + s.add : ""}${s.add && s.rem ? " " : ""}${s.rem ? "−" + s.rem : ""}`);
    if (s.vAdd || s.vRem) parts.push(`vias ${s.vAdd ? "+" + s.vAdd : ""}${s.vAdd && s.vRem ? " " : ""}${s.vRem ? "−" + s.vRem : ""}`);
    if (s.pAdd || s.pRem) parts.push(`pads ${s.pAdd ? "+" + s.pAdd : ""}${s.pAdd && s.pRem ? " " : ""}${s.pRem ? "−" + s.pRem : ""}`);
    if (s.changed) parts.push(`${s.changed} changed in place`);
    if (s.moved) parts.push(`${s.moved} moved`);
    const d = s.lenNew - s.lenOld;
    const len = `length ${mm(s.lenOld)} → ${mm(s.lenNew)} mm` + (Math.abs(d) >= 0.005 ? ` (${d > 0 ? "+" : ""}${mm(d)})` : "");
    return (parts.length ? parts.join(" · ") : "no changes") + "<br>" + len;
  }
  function hover(e) {
    const el = e.target.closest && e.target.closest("[data-i]");
    if (!el) { hideTip(); setHover(null); return; }
    const it = items[+el.dataset.i];
    setHover(it.n);
    const s = nets[it.n];
    tip.innerHTML =
      `<div class="t">${esc(netName(it.n))}<span class="badge st${BADGE[it.s]}">${STATUS[it.s].toUpperCase()}</span></div>` +
      `<div class="m">${esc(describe(it))}</div><div class="m" style="margin-top:4px">${netSummary(s)}</div>`;
    tip.style.display = "block";
    const host = svg.getBoundingClientRect();
    let x = e.clientX - host.left + 14, y = e.clientY - host.top + 14;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    if (x + tw > host.width - 8) x = e.clientX - host.left - tw - 14;
    if (y + th > host.height - 8) y = e.clientY - host.top - th - 14;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }

  // ---------- pinned net card ----------
  const card = $("#card");
  function netBox(n) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const grow = (x, y) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); };
    netEls[n].forEach((el) => {
      if (el.classList.contains("zone")) return;
      const it = items[+el.dataset.i];
      if (it.k === "p") { const r = Math.max(it.sw, it.sh) / 2; grow(it.x - r, it.y - r); grow(it.x + r, it.y + r); return; }
      const b = el.getBBox();
      grow(b.x, b.y); grow(b.x + b.width, b.y + b.height);
    });
    return x0 === Infinity ? null : { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  }
  function renderCard() {
    if (pinned === null) { card.style.display = "none"; return; }
    const s = nets[pinned];
    const d = s.lenNew - s.lenOld;
    const pm = (a, r) => (a || r ? `<span style="color:var(--added)">+${a}</span>  <span style="color:var(--removed)">−${r}</span>` : "—");
    card.innerHTML =
      `<div class="t">${esc(netName(pinned))}</div>` +
      `<dl><dt>Tracks</dt><dd>${pm(s.add, s.rem)} <span style="color:var(--faint)">· ${s.same} unchanged</span></dd>` +
      `<dt>Vias</dt><dd>${pm(s.vAdd, s.vRem)}</dd><dt>Pads</dt><dd>${pm(s.pAdd, s.pRem)}</dd>` +
      (s.changed ? `<dt>Edited</dt><dd>${s.changed} <span style="color:var(--faint)">· same item, copper changed</span></dd>` : "") +
      (s.moved ? `<dt>Moved</dt><dd>${s.moved} <span style="color:var(--faint)">· same copper, new place</span></dd>` : "") +
      `<dt>Length</dt><dd>${mm(s.lenOld)} → ${mm(s.lenNew)} mm${Math.abs(d) >= 0.005 ? ` <span style="color:${d > 0 ? "var(--added)" : "var(--removed)"}">(${d > 0 ? "+" : ""}${mm(d)})</span>` : ""}</dd></dl>` +
      `<div class="row"><button id="zoomNet">Zoom to net</button><button id="clearNet">Clear</button></div>`;
    card.style.display = "block";
    $("#zoomNet").onclick = () => { const b = netBox(pinned); if (b) fitBox(b, 0.25); };
    $("#clearNet").onclick = () => pin(null);
  }

  // ---------- show toggles ----------
  document.querySelectorAll("input[data-hide]").forEach((cb) => {
    const sync = () => svg.classList.toggle(cb.dataset.hide, !cb.checked);
    cb.addEventListener("change", sync);
    sync();
  });
  $("#byLayer").addEventListener("change", (e) => svg.classList.toggle("by-layer", e.target.checked));

  let totalAdd = 0, totalRem = 0;
  nets.forEach((s) => { totalAdd += s.add + s.vAdd + s.pAdd; totalRem += s.rem + s.vRem + s.pRem; });
  $("#nAdded").textContent = totalAdd;
  $("#nMoved").textContent = nets.reduce((a, s) => a + (s.moved || 0), 0);
  $("#nChanged").textContent = nets.reduce((a, s) => a + (s.changed || 0), 0);

  // ---------- footprints & pours ----------
  // Footprint changes that aren't (only) copper: pads changed within the
  // footprint, graphics, fields; and pours that were refilled or redrawn.
  const fpList = $("#fpList");
  function fpDesc(f) {
    const what = [];
    if (f.st === 1) what.push("added");
    if (f.st === 2) what.push("removed");
    if (f.pads) what.push("pads changed");
    if (f.gAdd || f.gRem) what.push(`graphics +${f.gAdd} −${f.gRem}`);
    for (const [k, b, a] of f.fields) what.push(`${k}: ${b || "(none)"} → ${a || "(none)"}`);
    if (f.moved) what.push("moved");
    return what.join(" · ");
  }
  const fpRank = (f) => (f.st === 1 || f.st === 2 || f.pads ? 0 : f.fields.length ? 1 : f.gAdd || f.gRem ? 2 : 3);
  const fpOrder = footprints.map((_, i) => i).sort((a, b) => fpRank(footprints[a]) - fpRank(footprints[b]) ||
    footprints[a].ref.localeCompare(footprints[b].ref, undefined, { numeric: true }));
  const zoneCount = (k) => zoneChanges.filter((z) => z.kind === k).length;
  const zoneParts = [];
  if (zoneCount("outline")) zoneParts.push(`${zoneCount("outline")} outline changed`);
  if (zoneCount("added")) zoneParts.push(`${zoneCount("added")} added`);
  if (zoneCount("removed")) zoneParts.push(`${zoneCount("removed")} removed`);
  if (zoneCount("refilled")) zoneParts.push(`${zoneCount("refilled")} refilled only`);
  $("#fpCount").textContent = footprints.length ? `${footprints.length} footprint${footprints.length === 1 ? "" : "s"} changed` : "No footprint changes";
  $("#zoneNote").textContent = zoneParts.length ? `Pours: ${zoneParts.join(", ")}` : "";
  $("#zoneNote").title = zoneChanges.map((z) => `${z.net || "(no net)"} ${z.name ? "(" + z.name + ") " : ""}on ${z.layers.join(", ")}: ${z.kind}`).join("\n");
  fpList.innerHTML = fpOrder.map((i) => {
    const f = footprints[i];
    const mark = f.st === 1 ? "+" : f.st === 2 ? "−" : "~";
    return `<button class="chg" data-fp="${i}" title="${esc(f.lib)}"><span class="k st${f.st === 5 ? 3 : f.st}">${mark}</span>` +
      `<span><div class="nm">${esc(f.ref)}</div><div class="d">${esc(fpDesc(f))}</div></span></button>`;
  }).join("");
  let fpPinned = null;
  function zoomToFootprint(f) {
    const els = fpEls.get(f) || [];
    if (!els.length) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const el of els) {
      const it = items[+el.dataset.i], rr = Math.max(it.sw, it.sh);
      x0 = Math.min(x0, it.x - rr); y0 = Math.min(y0, it.y - rr); x1 = Math.max(x1, it.x + rr); y1 = Math.max(y1, it.y + rr);
    }
    fitBox({ x: x0, y: y0, width: x1 - x0, height: y1 - y0 }, 1.5);
  }
  function pinFootprint(f) {
    fpPinned = f;
    fpList.querySelectorAll(".pin").forEach((x) => x.classList.remove("pin"));
    if (f !== null) fpList.querySelector(`[data-fp="${f}"]`)?.classList.add("pin");
    setFootprint(f);
    if (f === null) { renderCard(); return; } // back to the pinned net's card, if any
    zoomToFootprint(f);
    renderFootprintCard(f);
  }
  // The footprint's card: what it is, and what changed, as Old -> New rows.
  function renderFootprintCard(f) {
    const fp = footprints[f];
    const val = (v) => (v ? esc(v) : `<span class="none">(none)</span>`);
    const label = fp.st === 1 ? "ADDED" : fp.st === 2 ? "REMOVED" : "CHANGED";
    const rows = [["Footprint", esc(fp.lib)]];
    if (fp.st === 5) {
      rows.push(["Pads", fp.pads ? "changed within the footprint (shape, size or place)" : "unchanged"]);
      if (fp.gAdd || fp.gRem)
        rows.push(["Graphics", `+${fp.gAdd} −${fp.gRem} <span class="none">silkscreen, fab, courtyard lines and texts</span>`]);
      if (fp.moved) rows.push(["Position", "moved or rotated"]);
    }
    let h = `<div class="t">${esc(fp.ref)}<span class="badge st${BADGE[fp.st]}">${label}</span></div>` +
      `<table class="kv">${rows.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join("")}</table>`;
    if (fp.fields.length)
      h += `<h4>Field changes</h4><table class="diff"><thead><tr><th>Field</th><th>Old</th><th></th><th>New</th></tr></thead><tbody>` +
        fp.fields.map(([k, b, a]) => `<tr><td class="field">${esc(k)}</td><td class="old">${val(b)}</td>` +
          `<td class="arrow">→</td><td class="new">${val(a)}</td></tr>`).join("") + `</tbody></table>`;
    h += `<div class="row" style="margin-top:10px"><button id="fpZoom">Zoom to</button><button id="fpClose">Close</button></div>`;
    card.innerHTML = h;
    card.style.display = "block";
    $("#fpZoom").onclick = () => zoomToFootprint(f);
    $("#fpClose").onclick = () => pinFootprint(null);
  }
  fpList.addEventListener("mouseover", (e) => { const r = e.target.closest("[data-fp]"); if (r) setFootprint(+r.dataset.fp); });
  fpList.addEventListener("mouseleave", () => setFootprint(fpPinned));
  fpList.addEventListener("click", (e) => {
    const r = e.target.closest("[data-fp]");
    if (!r) return;
    const f = +r.dataset.fp;
    pinFootprint(fpPinned === f ? null : f);
  });
  $("#nRemoved").textContent = totalRem;

  // ---------- layers ----------
  const layerOn = layers.map(() => true);
  const viaEls = [...svg.querySelectorAll(".via")];
  // Silkscreen toggles (front/back), next to the copper layers.
  if (DATA.silk) {
    $("#silkLayers").innerHTML =
      `<label><input type="checkbox" data-silk="F" checked><span class="sw" style="background:var(--silk-f)"></span>F.Silkscreen</label>` +
      `<label><input type="checkbox" data-silk="B" checked><span class="sw" style="background:var(--silk-b)"></span>B.Silkscreen</label>`;
    $("#silkLayers").addEventListener("change", (e) => {
      const side = e.target.dataset.silk;
      if (side) svg.querySelector(`.silklayer[data-side="${side}"]`)?.classList.toggle("off", !e.target.checked);
    });
  }

  function syncLayers() {
    svg.querySelectorAll(".layer").forEach((g) => g.classList.toggle("off", !layerOn[+g.dataset.l]));
    viaEls.forEach((v) => {
      const show = v.dataset.l.split(",").some((l) => l !== "" && layerOn[+l]);
      v.style.display = show ? "" : "none";
    });
  }
  $("#layers").innerHTML = layers.map((l, i) =>
    `<label><input type="checkbox" data-layer="${i}" checked><span class="sw" style="background:${layerColor[i]}"></span>` +
    `${esc(l.display)}${l.display !== l.name ? `<span class="canon">${esc(l.name)}</span>` : ""}</label>`).join("");
  $("#layers").addEventListener("change", (e) => {
    const i = e.target.dataset.layer;
    if (i === undefined) return;
    layerOn[+i] = e.target.checked;
    syncLayers();
  });

  // All / None, and double-click a layer to show only that one.
  function setLayers(on) {
    on.forEach((v, i) => (layerOn[i] = v));
    document.querySelectorAll("#layers input[data-layer]").forEach((cb) => (cb.checked = layerOn[+cb.dataset.layer]));
    syncLayers();
  }
  $("#layersAll").addEventListener("click", () => setLayers(layers.map(() => true)));
  $("#layersNone").addEventListener("click", () => setLayers(layers.map(() => false)));
  $("#layers").addEventListener("dblclick", (e) => {
    const label = e.target.closest("label");
    const cb = label && label.querySelector("input[data-layer]");
    if (!cb) return;
    e.preventDefault();
    setLayers(layers.map((_, i) => i === +cb.dataset.layer));
  });

  // ---------- net list ----------
  const order = nets.map((_, i) => i).sort((a, b) => {
    const ca = changeCount(nets[a]), cb = changeCount(nets[b]);
    if ((ca > 0) !== (cb > 0)) return cb > 0 ? 1 : -1;
    if (ca !== cb) return cb - ca;
    return netName(a).localeCompare(netName(b), undefined, { numeric: true });
  });
  const list = $("#netlist");
  const rowFor = (n) => list.querySelector(`.net[data-n="${n}"]`);
  function renderList() {
    const q = $("#search").value.trim().toLowerCase();
    const changedOnly = $("#changedOnly").checked;
    const rows = order.filter((n) => (!changedOnly || changeCount(nets[n]) > 0) && (!q || netName(n).toLowerCase().includes(q)));
    const changedTotal = nets.filter((s) => changeCount(s) > 0).length;
    $("#netCount").textContent = `${changedTotal} of ${nets.length} nets changed · showing ${rows.length}`;
    list.innerHTML = rows.length ? rows.map((n) => {
      const s = nets[n], d = s.lenNew - s.lenOld, a = s.add + s.vAdd + s.pAdd, r = s.rem + s.vRem + s.pRem, e = s.changed || 0;
      const len = Math.abs(d) >= 0.005 ? `${d > 0 ? "+" : ""}${mm(d)}` : "";
      return `<button class="net${a + r + e ? "" : " quiet"}${n === pinned ? " pin" : ""}" data-n="${n}" title="${esc(netName(n))}">` +
        `<span class="nm">${esc(netName(n))}</span><span class="a">${a ? "+" + a : ""}</span>` +
        `<span class="r">${r ? "−" + r : ""}</span><span class="e">${e ? "~" + e : ""}</span><span class="len">${len}</span></button>`;
    }).join("") : `<div class="empty">No nets match.</div>`;
  }
  list.addEventListener("mouseover", (e) => { const r = e.target.closest(".net"); if (r) setHover(+r.dataset.n); });
  list.addEventListener("mouseleave", () => setHover(null));
  list.addEventListener("click", (e) => {
    const r = e.target.closest(".net");
    if (!r) return;
    const n = +r.dataset.n;
    pin(n === pinned ? null : n);
  });
  list.addEventListener("dblclick", (e) => {
    const r = e.target.closest(".net");
    if (!r) return;
    const b = netBox(+r.dataset.n);
    if (b) fitBox(b, 0.25);
  });
  $("#search").addEventListener("input", renderList);
  $("#changedOnly").addEventListener("change", renderList);

  // ---------- keys ----------
  document.addEventListener("keydown", (e) => {
    if (document.body.dataset.tab !== "pcb") return;
    if (e.target.matches("input[type=search]")) {
      if (e.key === "Escape") { e.target.value = ""; renderList(); e.target.blur(); }
      return;
    }
    if (e.key === "Escape") pin(null);
    else if (e.key === "f" || e.key === "F") fitAll();
    else if (e.key === "/") { e.preventDefault(); $("#search").focus(); }
  });
  window.addEventListener("resize", () => applyVB());

  renderList();
  syncLayers();
  fitAll();
})();
