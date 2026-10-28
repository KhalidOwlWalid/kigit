// Schematic view: one sheet at a time, coloured by diff status.
// Hover a wire, label or pin to see its net's changes; hover a part for its own.
(() => {
  "use strict";
  const S = DATA.sch;
  const tab = document.querySelector('[data-tab="sch"]');
  if (!S) {
    tab.disabled = true;
    tab.title = "No schematic found next to the board";
    return;
  }

  const $ = (s) => document.querySelector(s);
  const svg = $("#sch"), tip = $("#stip"), card = $("#scard");
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const n4 = (v) => Math.round(v * 1e4) / 1e4;
  // Status codes from the backend (html.cpp).
  const ST = ["unchanged", "added", "removed", "changed", "fields changed", "moved", "old position"];
  const LABEL_KIND = ["label", "global label", "hierarchical label", "sheet pin"];

  // ------------------------------------------------------------ geometry

  // Symbol transform: library (y down) -> sheet. KiCad rotates
  // counter-clockwise, then mirrors.
  function matrix(sym) {
    const q = ((Math.round(sym.a / 90) % 4) + 4) % 4;
    const [c, s] = [[1, 0], [0, 1], [-1, 0], [0, -1]][q];
    let a = c, b = -s, cc = s, d = c; // x' = a x + cc y, y' = b x + d y
    if (sym.my) { a = -a; cc = -cc; }
    if (sym.mx) { b = -b; d = -d; }
    return [a, b, cc, d, sym.x, sym.y];
  }
  const apply = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
  const applyDir = (m, x, y) => [m[0] * x + m[2] * y, m[1] * x + m[3] * y];
  const dirOf = (deg) => { const r = (deg * Math.PI) / 180; return [Math.round(Math.cos(r)), -Math.round(Math.sin(r))]; };

  // KiCad markup: ~{X} overbar, _{x} subscript, ^{x} superscript. Shown plainly.
  const plain = (t) => String(t).replace(/[~_^]\{([^}]*)\}/g, "$1");

  // Real text width in sheet units, for sizing label boxes.
  const measure = document.createElement("canvas").getContext("2d");
  measure.font = '100px "DejaVu Sans", "Segoe UI", Roboto, Ubuntu, sans-serif';
  const textWidth = (str, size) => (measure.measureText(plain(str)).width / 100) * size * 1.38;

  // Text in its final, readable orientation. vertical: reads bottom to top.
  // h: -1 start, 0 middle, 1 end. v: -1 top, 0 centre, 1 bottom.
  // KiCad's size is roughly the cap height; browser font-size is the em box.
  function text(str, x, y, vertical, h, v, size, cls = "") {
    const lines = plain(str).split("\n");
    const fs = size * 1.38, lh = size * 1.55;
    const anchor = h < 0 ? "start" : h > 0 ? "end" : "middle";
    // Baseline offset so the block sits on the requested side of (x, y).
    const capH = size;
    const block = (lines.length - 1) * lh;
    const first = v < 0 ? capH : v > 0 ? -block : capH / 2 - block / 2;
    const rot = vertical ? ` transform="rotate(-90 ${n4(x)} ${n4(y)})"` : "";
    let out = `<text class="${cls}" x="${n4(x)}" y="${n4(y)}" font-size="${n4(fs)}" text-anchor="${anchor}"${rot}>`;
    lines.forEach((l, i) => {
      out += `<tspan x="${n4(x)}" ${i === 0 ? `dy="${n4(first)}"` : `dy="${n4(lh)}"`}>${esc(l)}</tspan>`;
    });
    return out + "</text>";
  }

  // Turns a direction/up pair into readable placement: text never reads
  // right-to-left or top-to-bottom, so flipped directions swap justification.
  function readable(dir, up, h, v) {
    const vertical = Math.abs(dir[1]) > Math.abs(dir[0]);
    const R = vertical ? [0, -1] : [1, 0];
    const U = vertical ? [-1, 0] : [0, -1];
    if (dir[0] * R[0] + dir[1] * R[1] < 0) h = -h;
    if (up[0] * U[0] + up[1] * U[1] < 0) v = -v;
    return { vertical, h, v, U };
  }

  // ------------------------------------------------------------ drawing

  function symbolSvg(sym, k) {
    const def = S.defs[sym.d];
    if (!def) return "";
    const m = matrix(sym);
    const data = sym.pw ? `data-n="${sym.pn[0] ?? -1}"` : `data-i="${sym.i}"`;
    let out = `<g class="sym st${sym.st}${sym.pw ? " pw" : ""}" ${data} data-k="${k}">`;
    out += `<g transform="matrix(${m.join(" ")})">`;
    // Lines thicker than the default (capacitor plates, crystal electrodes)
    // keep their real width so they scale with zoom like in KiCad.
    for (const [d, fill, w] of def.g)
      out += w >= 0.4 ? `<path class="f${fill} thick" style="stroke-width:${w}" d="${d}"/>` : `<path class="f${fill}" d="${d}"/>`;
    out += "</g>";

    def.p.forEach((p, j) => {
      const [x, y, ang, len, num, name, numSize, nameSize, hidden] = p;
      if (hidden) return;
      const dl = dirOf(ang);
      const [ax, ay] = apply(m, x, y);
      const [ex, ey] = apply(m, x + dl[0] * len, y + dl[1] * len);
      const net = sym.pn[j] ?? -1;
      out += `<path class="pin" data-n="${net}" d="M${n4(ax)} ${n4(ay)}L${n4(ex)} ${n4(ey)}"/>`;
      if (sym.pw) return;
      const d = [Math.sign(ex - ax), Math.sign(ey - ay)];
      const vertical = d[0] === 0;
      const U = vertical ? [-1, 0] : [0, -1];
      const R = vertical ? [0, -1] : [1, 0];
      const mid = [(ax + ex) / 2, (ay + ey) / 2];
      const gap = 0.35;
      const showName = !def.hn && name && name !== "~";
      const showNum = !def.hu && num;
      if (showName && def.off > 0) {
        // Name inside the body, past the pin's inner end.
        const at = [ex + d[0] * def.off, ey + d[1] * def.off];
        const h = d[0] * R[0] + d[1] * R[1] > 0 ? -1 : 1;
        out += text(name, at[0], at[1], vertical, h, 0, nameSize, "pintext");
      } else if (showName) {
        out += text(name, mid[0] + U[0] * gap, mid[1] + U[1] * gap, vertical, 0, 1, nameSize, "pintext");
      }
      if (showNum) {
        const side = showName && def.off === 0 ? -1 : 1; // below the line if the name took the top
        out += text(num, mid[0] + U[0] * gap * side, mid[1] + U[1] * gap * side, vertical, 0, side > 0 ? 1 : -1,
                    numSize, "pintext");
      }
    });

    // Fields keep their absolute position; their angle is relative to the symbol.
    for (const f of sym.f) {
      const [str, x, y, angle, size, h, v] = f;
      const base = dirOf(angle), baseUp = [base[1], -base[0]];
      const r = readable(applyDir(m, base[0], base[1]), applyDir(m, baseUp[0], baseUp[1]), h, v);
      out += text(str, x, y, r.vertical, r.h, r.v, size);
    }
    if (sym.st === 4) {
      // Only BOM fields changed: a small marker by the part.
      out += `<circle class="mark" cx="${n4(sym.x + 1.2)}" cy="${n4(sym.y - 1.2)}" r="0.45"/>`;
    }
    return out + "</g>";
  }

  // Global/hierarchical label outline, in label-local coordinates where the
  // body extends along +x from the anchor and the box is `h` tall.
  function labelShape(kind, shape, len, h) {
    const t = h / 2;
    if (kind === 2 || kind === 3) {
      // Small closed flag at the anchor. A sheet pin's arrow is mirrored
      // relative to a hierarchical label's (it points into the sheet box).
      const s = h * 0.62, q = s / 2;
      let sh = shape;
      if (kind === 3) sh = shape === "input" ? "output" : shape === "output" ? "input" : shape;
      if (sh === "input") return `M0 0L${q} ${-q}H${s}V${q}H${q}Z`;
      if (sh === "output") return `M0 ${-q}H${q}L${s} 0L${q} ${q}H0Z`;
      if (sh === "bidirectional" || sh === "tri_state") return `M0 0L${q} ${-q}L${s} 0L${q} ${q}Z`;
      return `M0 ${-q}H${s}V${q}H0Z`;
    }
    const p = t; // point length
    switch (shape) {
      case "input": return `M0 0L${p} ${-t}H${len}V${t}H${p}Z`;
      case "output": return `M0 ${-t}H${len - p}L${len} 0L${len - p} ${t}H0Z`;
      case "bidirectional": case "tri_state":
        return `M0 0L${p} ${-t}H${len - p}L${len} 0L${len - p} ${t}H${p}Z`;
      default: return `M0 ${-t}H${len}V${t}H0Z`;
    }
  }

  function labelSvg(l) {
    const [kind, str, x, y, angle, size, shape, st, net] = l;
    let d = dirOf(angle);
    if (kind === 3) d = [-d[0], -d[1]]; // sheet pin text points into the sheet box
    const vertical = d[0] === 0;
    const R = vertical ? [0, -1] : [1, 0];
    const U = vertical ? [-1, 0] : [0, -1];
    const forward = d[0] * R[0] + d[1] * R[1] > 0;
    const textLen = textWidth(str, size);
    let out = `<g class="lbl st${st}${net < 0 ? " buslbl" : ""}" data-n="${net}">`;
    if (kind === 0) {
      const at = [x + U[0] * 0.3, y + U[1] * 0.3];
      out += text(str, at[0], at[1], vertical, forward ? -1 : 1, 1, size);
    } else {
      const h = size * 1.6;
      const flag = kind === 1 ? 0 : h * 0.62;
      const len = kind === 1 ? textLen + size * 1.9 : 0;
      // Rotate the local shape so +x follows d.
      const rot = Math.atan2(d[1], d[0]) * (180 / Math.PI);
      out += `<path transform="translate(${n4(x)} ${n4(y)}) rotate(${n4(rot)})" d="${labelShape(kind, shape, n4(len), n4(h))}"/>`;
      const start = kind === 1 ? size * 1.0 : flag + size * 0.5;
      const at = [x + d[0] * start, y + d[1] * start];
      out += text(str, at[0], at[1], vertical, forward ? -1 : 1, 0, size);
    }
    return out + "</g>";
  }

  function boxSvg(b) {
    let out = `<g class="box st${b.st}" data-c="${b.c}"><rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}"/>`;
    for (const t of [b.name, b.file]) {
      const [str, x, y, angle, size, h, v] = t;
      if (!str) continue;
      const dd = dirOf(angle);
      const r = readable(dd, [dd[1], -dd[0]], h, v);
      out += text(str, x, y, r.vertical, r.h, r.v, size, t === b.file ? "note" : "");
    }
    return out + "</g>";
  }

  // ------------------------------------------------------------ state

  let cur = 0;                   // current sheet index
  let netEls = new Map(), partEls = new Map();
  const views = new Map();       // sheet -> saved view box

  // Sheets each net appears on, for "also on" in tooltips.
  const netSheets = S.nets.map(() => new Set());
  S.sheets.forEach((sh, i) => {
    for (const w of sh.wires) if (w[5] >= 0) netSheets[w[5]].add(i);
    for (const l of sh.labels) if (l[8] >= 0) netSheets[l[8]].add(i);
    for (const s of sh.symbols) for (const n of s.pn) if (n >= 0) netSheets[n].add(i);
  });

  function render() {
    const sh = S.sheets[cur];
    let out = `<rect class="paper" x="0" y="0" width="${sh.w}" height="${sh.h}"/><g id="schContent">`;
    for (const d of sh.drawings) out += `<path class="drawing" d="${d}"/>`;
    for (const t of sh.texts) {
      const [str, x, y, angle, size, h, v] = t;
      const dd = dirOf(angle);
      const r = readable(dd, [dd[1], -dd[0]], h, v);
      out += text(str, x, y, r.vertical, r.h, r.v, size, "note");
    }
    for (const b of sh.boxes) out += boxSvg(b);
    // Ghosts and removed things underneath, then unchanged, then added on top.
    const order = (st) => (st === 6 ? 0 : st === 2 ? 1 : st === 1 ? 3 : 2);
    const syms = sh.symbols.map((s, k) => [s, k]).sort((p, q) => order(p[0].st) - order(q[0].st));
    for (const [s, k] of syms) out += symbolSvg(s, k);
    const wires = [...sh.wires].sort((p, q) => order(p[4]) - order(q[4]));
    // Buses (thick) and bus entries (the short diagonals into them).
    for (const e of sh.entries || []) out += `<path class="bus-entry" d="M${e[0]} ${e[1]}L${e[2]} ${e[3]}"/>`;
    for (const b of [...(sh.buses || [])].sort((p, q) => order(p[4]) - order(q[4])))
      out += `<path class="bus st${b[4]}" d="M${b[0]} ${b[1]}L${b[2]} ${b[3]}"/>`;
    for (const w of wires)
      out += `<path class="wire st${w[4]}" data-n="${w[5]}" d="M${w[0]} ${w[1]}L${w[2]} ${w[3]}"/>`;
    for (const j of sh.junctions) out += `<circle class="junction st${j[2]}" cx="${j[0]}" cy="${j[1]}" r="0.46"/>`;
    for (const [x, y] of sh.nc) {
      const s = 0.64;
      out += `<path class="nc" d="M${x - s} ${y - s}L${x + s} ${y + s}M${x - s} ${y + s}L${x + s} ${y - s}"/>`;
    }
    for (const l of sh.labels) out += labelSvg(l);
    for (const w of sh.wires) out += `<path class="hit" data-n="${w[5]}" d="M${w[0]} ${w[1]}L${w[2]} ${w[3]}"/>`;
    svg.innerHTML = out + "</g>";

    netEls = new Map();
    partEls = new Map();
    svg.querySelectorAll("[data-n]").forEach((el) => {
      const n = +el.dataset.n;
      if (n < 0 || el.classList.contains("hit")) return;
      if (!netEls.has(n)) netEls.set(n, []);
      netEls.get(n).push(el);
    });
    svg.querySelectorAll(".sym[data-i]").forEach((el) => {
      const i = +el.dataset.i;
      if (i < 0) return;
      if (!partEls.has(i)) partEls.set(i, []);
      partEls.get(i).push(el);
    });
    shown = null;
    renderSide();
  }

  // ------------------------------------------------------------ view box

  let vb = { x: 0, y: 0, w: 297, h: 210 };
  const applyVB = () => svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  function fitBox(b, pad = 0.03) {
    const r = svg.getBoundingClientRect();
    const aspect = r.width / Math.max(r.height, 1);
    let w = Math.max(b.width, 1) * (1 + 2 * pad), h = Math.max(b.height, 1) * (1 + 2 * pad);
    if (w / h < aspect) w = h * aspect; else h = w / aspect;
    vb = { x: b.x + b.width / 2 - w / 2, y: b.y + b.height / 2 - h / 2, w, h };
    applyVB();
  }
  // Fit what's drawn (not the whole paper); an empty sheet shows the paper.
  function fitSheet() {
    const g = svg.querySelector("#schContent");
    const b = g && g.getBBox();
    if (b && b.width > 0 && b.height > 0) fitBox(b, 0.04);
    else fitBox({ x: 0, y: 0, width: S.sheets[cur].w, height: S.sheets[cur].h });
  }
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
    if (wasDrag || e.button !== 0) return;
    const t = targetOf(e.target);
    if (!t) return pin(null);
    pin(pinned && pinned.kind === t.kind && pinned.id === t.id ? null : t);
  });
  svg.addEventListener("dblclick", (e) => {
    const box = e.target.closest(".box");
    if (box) openSheet(+box.dataset.c);
  });
  svg.addEventListener("pointerleave", () => { hideTip(); setHover(null); });

  // ------------------------------------------------------------ highlight

  // A hover/pin target: a net (kind "n") or a part (kind "p").
  function targetOf(el) {
    if (!el || !el.closest) return null;
    const n = el.closest("[data-n]");
    const p = el.closest(".sym[data-i]");
    // Pins and wires mean the net; a part's body means the part.
    if (n && (!p || n !== p) && +n.dataset.n >= 0) return { kind: "n", id: +n.dataset.n };
    if (p && +p.dataset.i >= 0) return { kind: "p", id: +p.dataset.i };
    if (n && +n.dataset.n >= 0) return { kind: "n", id: +n.dataset.n };
    return null;
  }

  let hovered = null, pinned = null, shown = null;
  const same = (a, b) => (a === b) || (a && b && a.kind === b.kind && a.id === b.id);
  function refreshHL() {
    const target = hovered || pinned;
    if (same(target, shown)) return;
    svg.querySelectorAll(".on").forEach((el) => el.classList.remove("on"));
    if (target) {
      const els = (target.kind === "n" ? netEls : partEls).get(target.id) || [];
      els.forEach((el) => {
        el.classList.add("on");
        // Light up the part a pin belongs to as well, without dimming its body.
        const g = el.closest(".sym");
        if (g) g.classList.add("on");
      });
    }
    svg.classList.toggle("hl", !!target);
    shown = target;
    document.querySelectorAll(".chg.cur").forEach((r) => r.classList.remove("cur"));
    if (target) document.querySelector(`.chg[data-kind="${target.kind}"][data-id="${target.id}"]`)?.classList.add("cur");
  }
  const setHover = (t) => { hovered = t; refreshHL(); };
  function pin(t) {
    pinned = t;
    document.querySelectorAll(".chg.pin").forEach((r) => r.classList.remove("pin"));
    if (t) document.querySelector(`.chg[data-kind="${t.kind}"][data-id="${t.id}"]`)?.classList.add("pin");
    renderCard();
    refreshHL();
  }

  // ------------------------------------------------------------ descriptions

  const sheetName = (i) => S.sheets[i].name || S.sheets[i].file;
  const list = (v, max = 6) => v.length > max ? v.slice(0, max).join(", ") + `, +${v.length - max} more` : v.join(", ");

  function netInfo(id) {
    const n = S.nets[id];
    const lines = [];
    if (n.merged) lines.push(`merged into <b>${esc(n.merged)}</b>`);
    if (n.st === 3 && n.before && n.before !== n.name) lines.push(`renamed from <b>${esc(n.before)}</b>`);
    if (n.st === 1) lines.push("new net");
    if (n.joined.length && n.st !== 1) lines.push(`<span style="color:var(--added)">joined:</span> ${esc(list(n.joined))}`);
    if (n.st === 1 && n.joined.length) lines.push(`pins: ${esc(list(n.joined))}`);
    if (n.left.length && !n.merged) lines.push(`<span style="color:var(--removed)">left:</span> ${esc(list(n.left))}`);
    if (!n.el && n.st !== 3 && (n.wa || n.wr || n.la || n.lr))
      lines.push(`wiring redrawn, connections unchanged (wires +${n.wa} −${n.wr})`);
    else if (n.wa || n.wr) lines.push(`wires +${n.wa} −${n.wr}`);
    if (!lines.length) lines.push("no changes");
    const others = [...netSheets[id]].filter((s) => s !== cur).map(sheetName);
    if (others.length) lines.push(`also on: ${esc(others.join(", "))}`);
    const st = n.st === 0 && (n.wa || n.wr || n.la || n.lr) ? 5 : n.st;
    return { title: n.name || "(unnamed net)", st, lines };
  }

  function partInfo(id) {
    const p = S.parts[id];
    const lines = [`${esc(p.value)} · ${esc(p.lib)}`];
    if (p.fp) lines.push(esc(p.fp));
    if (p.before && p.before !== p.ref && p.st !== 1) lines.push(`renamed from <b>${esc(p.before)}</b>`);
    for (const [f, b, a] of p.fields) lines.push(`<b>${esc(f)}</b>: ${esc(b || "(none)")} → ${esc(a || "(none)")}`);
    for (const [pinText, b, a] of p.pins) lines.push(`<b>${esc(pinText)}</b>: ${esc(b || "(none)")} → ${esc(a || "(none)")}`);
    if (p.moved) lines.push("moved");
    return { title: p.ref, st: p.st, lines };
  }

  const info = (t) => (t.kind === "n" ? netInfo(t.id) : partInfo(t.id));

  // ------------------------------------------------------------ tooltip & card

  const hideTip = () => { tip.style.display = "none"; };
  function hover(e) {
    const t = targetOf(e.target);
    if (!t) { hideTip(); setHover(null); return; }
    setHover(t);
    const i = info(t);
    tip.innerHTML = `<div class="t">${esc(i.title)}<span class="badge st${i.st}">${ST[i.st].toUpperCase()}</span></div>` +
      i.lines.slice(0, 8).map((l) => `<div class="m">${l}</div>`).join("");
    tip.style.display = "block";
    const host = svg.getBoundingClientRect();
    let x = e.clientX - host.left + 14, y = e.clientY - host.top + 14;
    if (x + tip.offsetWidth > host.width - 8) x = e.clientX - host.left - tip.offsetWidth - 14;
    if (y + tip.offsetHeight > host.height - 8) y = e.clientY - host.top - tip.offsetHeight - 14;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }

  function boxOf(t) {
    const els = (t.kind === "n" ? netEls : partEls).get(t.id) || [];
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const el of els) {
      const r = el.getBBox();
      // Part bodies sit inside a transformed group; use the outer group's box.
      x0 = Math.min(x0, r.x); y0 = Math.min(y0, r.y); x1 = Math.max(x1, r.x + r.width); y1 = Math.max(y1, r.y + r.height);
    }
    return x0 === Infinity ? null : { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  }

  function renderCard() {
    if (!pinned) { card.style.display = "none"; return; }
    const i = info(pinned);
    let html = `<div class="t">${esc(i.title)} <span class="badge st${i.st}">${ST[i.st].toUpperCase()}</span></div>` +
      `<div style="margin:8px 0;font-size:12px;color:var(--muted)">${i.lines.map((l) => `<div>${l}</div>`).join("")}</div>`;
    if (pinned.kind === "n") {
      const sheets = [...netSheets[pinned.id]];
      if (sheets.length > 1)
        html += `<div class="row sheets" style="margin-bottom:8px">` +
          sheets.map((s) => `<button data-sheet="${s}"${s === cur ? " disabled" : ""}>${esc(sheetName(s))}</button>`).join("") + `</div>`;
    }
    html += `<div class="row"><button id="schZoom">Zoom to</button><button id="schClear">Clear</button></div>`;
    card.innerHTML = html;
    card.style.display = "block";
    card.querySelectorAll("[data-sheet]").forEach((b) => (b.onclick = () => openSheet(+b.dataset.sheet, true)));
    $("#schZoom").onclick = () => { const b = boxOf(pinned); if (b) fitBox(b, 0.6); };
    $("#schClear").onclick = () => pin(null);
  }

  // ------------------------------------------------------------ sidebar

  function sheetDepth(i) { let d = 0; while (S.sheets[i].parent >= 0) { i = S.sheets[i].parent; d++; } return d; }
  // Changes on a sheet and below it, for the list badges.
  const subtreeChanges = S.sheets.map((_, i) => {
    let total = 0;
    S.sheets.forEach((sh, j) => { let k = j; while (k >= 0) { if (k === i) { total += sh.changes; break; } k = S.sheets[k].parent; } });
    return total;
  });

  function renderSide() {
    // Sheets, in hierarchy order.
    const ordered = [];
    const walk = (parent) => S.sheets.forEach((sh, i) => { if (sh.parent === parent) { ordered.push(i); walk(i); } });
    walk(-1);
    $("#sheetList").innerHTML = ordered.map((i) => {
      const sh = S.sheets[i], ch = subtreeChanges[i];
      return `<button class="sheet-row${i === cur ? " cur" : ""}" data-sheet="${i}" style="padding-left:${8 + sheetDepth(i) * 14}px">` +
        `<span class="nm">${esc(sheetName(i))}</span>${ch ? `<span class="ch">${ch}</span>` : ""}</button>`;
    }).join("");

    // What changed on this sheet: parts and nets drawn here.
    const sh = S.sheets[cur];
    const parts = new Set(), nets = new Set();
    for (const s of sh.symbols) if (s.i >= 0 && s.st !== 6) parts.add(s.i);
    for (const w of sh.wires) if (w[5] >= 0) nets.add(w[5]);
    for (const l of sh.labels) if (l[8] >= 0) nets.add(l[8]);
    for (const s of sh.symbols) for (const n of s.pn) if (n >= 0) nets.add(n);
    const rows = [];
    const rank = (st) => (st === 1 || st === 2 || st === 3 ? 0 : st === 4 ? 1 : 2);
    for (const i of parts) {
      const p = S.parts[i];
      if (p.st === 0) continue;
      const inf = partInfo(i);
      rows.push({ kind: "p", id: i, st: p.st, name: p.ref, desc: inf.lines.slice(p.fp ? 2 : 1).join(" · ").replace(/<[^>]+>/g, "") || ST[p.st] });
    }
    for (const n of nets) {
      const net = S.nets[n];
      const inf = netInfo(n);
      if (inf.st === 0) continue;
      rows.push({ kind: "n", id: n, st: inf.st, name: net.name || "(unnamed)", desc: inf.lines[0].replace(/<[^>]+>/g, "") });
    }
    rows.sort((a, b) => rank(a.st) - rank(b.st) || a.name.localeCompare(b.name, undefined, { numeric: true }));
    const marks = { 1: "+", 2: "−", 3: "~", 4: "•", 5: "≈" };
    $("#schCount").textContent = rows.length ? `${rows.length} changes on ${sheetName(cur)}` : `No changes on ${sheetName(cur)}`;
    $("#schChanges").innerHTML = rows.map((r) =>
      `<button class="chg" data-kind="${r.kind}" data-id="${r.id}"><span class="k st${r.st}">${marks[r.st] || "·"}</span>` +
      `<span><div class="nm">${r.kind === "n" ? "net " : ""}${esc(r.name)}</div><div class="d">${esc(r.desc)}</div></span></button>`).join("");

    // Breadcrumbs.
    const chain = [];
    for (let i = cur; i >= 0; i = S.sheets[i].parent) chain.unshift(i);
    $("#crumbs").innerHTML = chain.map((i, k) => k === chain.length - 1
      ? `<span class="here">${esc(sheetName(i))}</span>`
      : `<button data-sheet="${i}">${esc(sheetName(i))}</button><span class="sep">/</span>`).join("");
  }

  $("#sheetList").addEventListener("click", (e) => { const b = e.target.closest("[data-sheet]"); if (b) openSheet(+b.dataset.sheet); });
  $("#crumbs").addEventListener("click", (e) => { const b = e.target.closest("[data-sheet]"); if (b) openSheet(+b.dataset.sheet); });
  const changes = $("#schChanges");
  changes.addEventListener("mouseover", (e) => { const r = e.target.closest(".chg"); if (r) setHover({ kind: r.dataset.kind, id: +r.dataset.id }); });
  changes.addEventListener("mouseleave", () => setHover(null));
  changes.addEventListener("click", (e) => {
    const r = e.target.closest(".chg");
    if (!r) return;
    const t = { kind: r.dataset.kind, id: +r.dataset.id };
    pin(same(t, pinned) ? null : t);
    if (pinned) { const b = boxOf(t); if (b) fitBox(b, 0.8); }
  });

  document.querySelectorAll("input[data-sch]").forEach((cb) => {
    const sync = () => svg.classList.toggle(cb.dataset.sch, !cb.checked);
    cb.addEventListener("change", sync);
    sync();
  });

  // ------------------------------------------------------------ navigation

  function openSheet(i, keepPin = false) {
    if (i < 0 || i >= S.sheets.length) return;
    views.set(cur, { ...vb });
    cur = i;
    const keep = keepPin ? pinned : null;
    hovered = null;
    pinned = null;
    render();
    const saved = views.get(cur);
    if (saved) { vb = saved; applyVB(); } else fitSheet();
    if (keep) pin(keep); else renderCard();
  }

  document.addEventListener("keydown", (e) => {
    if (document.body.dataset.tab !== "sch" || e.target.matches("input")) return;
    if (e.key === "Escape") pin(null);
    else if (e.key === "f" || e.key === "F") fitSheet();
    else if (e.key === "Backspace" && S.sheets[cur].parent >= 0) { e.preventDefault(); openSheet(S.sheets[cur].parent); }
  });
  window.addEventListener("resize", applyVB);

  // Shown the first time the tab opens (the svg has no size while hidden).
  let started = false;
  window.kigitShowSchematic = () => {
    if (started) return;
    started = true;
    // Start on the sheet with the most changes.
    let best = 0;
    S.sheets.forEach((sh, i) => { if (sh.changes > S.sheets[best].changes) best = i; });
    cur = best;
    render();
    fitSheet();
  };
  const total = S.sheets.reduce((a, sh) => a + sh.changes, 0);
  $("#schTabN").textContent = total ? total : "";
})();
