"""The BOM page: the board's bill of materials (kigit bom --json), with
links to search Digi-Key, Mouser and LCSC for each line, the part number
you chose for lines that have none, and a CSV for the distributors' BOM
upload tools.

Only made when asked (the header's BOM button); nothing runs in the
background. Your picks are kept next to the board in kigit-bom.json (in
git, so they go with the project), keyed by a line's value and footprint,
so they survive renumbering. Part numbers already in the schematic stay as
they are; a pick only fills in what's missing.
"""

from __future__ import annotations

import html
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from nicegui import app

PICKS = "kigit-bom.json"
PICK_FIELDS = ("mpn", "manufacturer", "note")


@dataclass
class Job:
    board: str
    title: str
    data: dict


jobs: dict[str, Job] = {}


def new_job(job: Job) -> str:
    key = secrets.token_hex(8)
    jobs[key] = job
    return key


def line_key(line: dict) -> str:
    return f"{line.get('value', '')}|{line.get('footprint', '')}"


def picks_path(board: str | Path) -> Path:
    return Path(board).parent / PICKS


def load_picks(board: str | Path) -> dict[str, dict]:
    try:
        data = json.loads(picks_path(board).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    picks = data.get("picks") if isinstance(data, dict) else None
    return {k: v for k, v in (picks or {}).items() if isinstance(v, dict)}


def save_pick(board: str | Path, key: str, pick: dict) -> dict[str, dict]:
    """Sets (or with nothing in it, removes) one line's pick. Re-reads the
    file first, so two pages don't undo each other."""
    picks = load_picks(board)
    clean = {f: str(pick.get(f, "")).strip()[:200] for f in PICK_FIELDS}
    clean = {f: v for f, v in clean.items() if v}
    if clean:
        clean["updated"] = time.strftime("%Y-%m-%d")
        picks[key] = clean
    else:
        picks.pop(key, None)
    path = picks_path(board)
    if picks:
        text = json.dumps({"version": 1, "picks": dict(sorted(picks.items()))}, indent=2, ensure_ascii=False) + "\n"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(path)
    elif path.exists():
        path.unlink()
    return picks


@app.get("/bom/{key}")
async def _page(key: str) -> Response:
    job = jobs.get(key)
    if job is None:
        return HTMLResponse("<p style='font-family:sans-serif;color:#aaa'>This BOM is gone (kigit was restarted?). "
                            "Press BOM again.</p>", status_code=404)
    return HTMLResponse(page(key, job))


@app.get("/bom/{key}/picks")
async def _picks(key: str) -> Response:
    job = jobs.get(key)
    if job is None:
        return JSONResponse({}, status_code=404)
    return JSONResponse(load_picks(job.board))


@app.post("/bom/{key}/picks")
async def _set_pick(key: str, request: Request) -> Response:
    job = jobs.get(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    body = await request.json()
    line = str(body.get("key", ""))
    if not line or not any(line_key(l) == line for l in job.data.get("lines", [])):
        return JSONResponse({"error": "no such line"}, status_code=400)
    try:
        return JSONResponse(save_pick(job.board, line, body.get("pick") or {}))
    except OSError as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def page(key: str, job: Job) -> str:
    data = json.dumps(job.data, ensure_ascii=False).replace("<", "\\u003c")
    name = re.sub(r"[^\w.-]+", "_", Path(job.board).stem) or "board"
    return (_PAGE.replace("%%TITLE%%", html.escape(job.title))
            .replace("%%KEY%%", key)
            .replace("%%NAME%%", json.dumps(name))
            .replace("%%PICKS_FILE%%", html.escape(str(picks_path(job.board))))
            .replace("%%DATA%%", data))


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BOM · %%TITLE%%</title>
<style>
:root { --bg: #0f1115; --panel: #161a20; --line: #29303a; --text: #e6e9ee; --muted: #9aa4b2; --faint: #6b7584;
  --accent: #e8b84d; --ok: #3fb950; --warn: #e8b84d; --bad: #f85149; --link: #79b8ff; }
@media (prefers-color-scheme: light) { :root { --bg: #f6f7f9; --panel: #fff; --line: #d8dde4; --text: #1d2229;
  --muted: #5b6573; --faint: #8a94a3; --accent: #9a6b00; --ok: #1a7f37; --warn: #9a6b00; --bad: #cf222e; --link: #0969da; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { position: sticky; top: 0; z-index: 2; background: var(--bg); border-bottom: 1px solid var(--line);
  padding: 12px 16px; display: flex; flex-wrap: wrap; gap: 8px 18px; align-items: center; }
h1 { font-size: 16px; margin: 0; } .sub { color: var(--muted); }
.stats { display: flex; gap: 14px; color: var(--muted); }
.stats b { color: var(--text); }
.tools { margin-left: auto; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
input, select, button { font: inherit; color: var(--text); background: var(--panel); border: 1px solid var(--line);
  border-radius: 6px; padding: 4px 8px; }
button { cursor: pointer; } button:hover { border-color: var(--accent); }
button.primary { border-color: var(--accent); color: var(--accent); }
main { padding: 8px 16px 40px; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-weight: 600; color: var(--muted); font-size: 12px; padding: 6px 8px; border-bottom: 1px solid var(--line);
  position: sticky; top: var(--head, 56px); background: var(--bg); z-index: 1; }
td { padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
tr.dnp td { opacity: .55; }
.refs { color: var(--muted); max-width: 18rem; }
.qty { text-align: right; font-variant-numeric: tabular-nums; }
.pkg { color: var(--muted); font-size: 12px; } .desc { color: var(--faint); font-size: 12px; }
.num { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }
.chip { display: inline-block; font-size: 11px; border-radius: 999px; padding: 0 7px; border: 1px solid; white-space: nowrap; }
.chip.ok { color: var(--ok); } .chip.picked { color: var(--link); } .chip.need { color: var(--warn); } .chip.dnp { color: var(--faint); }
.links a { color: var(--link); text-decoration: none; margin-right: 8px; white-space: nowrap; }
.links a:hover { text-decoration: underline; }
.pick { display: flex; gap: 4px; align-items: center; }
.pick input { width: 10.5rem; min-width: 0; } .pick input.maker { width: 7rem; } .pick input.note { width: 7rem; }
@media (max-width: 1100px) { .pick { flex-wrap: wrap; } }
.pick .saved { color: var(--ok); font-size: 11px; align-self: center; }
.empty { color: var(--faint); padding: 30px; text-align: center; }
.foot { color: var(--faint); font-size: 12px; margin-top: 14px; }
</style>
</head>
<body>
<header id="head">
  <div><h1>Bill of materials</h1><div class="sub">%%TITLE%%</div></div>
  <div class="stats" id="stats"></div>
  <div class="tools">
    <input id="filter" placeholder="Filter (ref, value, part...)" aria-label="Filter">
    <select id="show" aria-label="Show">
      <option value="all">All lines</option><option value="need">Needs a part number</option>
      <option value="has">Has a part number</option>
    </select>
    <label class="sub">Boards <input id="boards" type="number" min="1" value="1" style="width:4.5rem"></label>
    <label class="sub"><input id="dnp" type="checkbox"> DNP in export</label>
    <button id="export" class="primary" title="A CSV for Digi-Key's BOM Manager or Mouser's BOM Tool">Export CSV</button>
  </div>
</header>
<main>
<table>
  <thead><tr><th class="qty">Qty</th><th>References</th><th>Value</th><th>Part number</th><th>Search</th><th>Your pick</th></tr></thead>
  <tbody id="rows"></tbody>
</table>
<div class="foot">Picks are saved as you type, in <code>%%PICKS_FILE%%</code> (commit it to share them). Part numbers in the
schematic win over picks. The search links only open the distributors' sites: nothing is sent anywhere by kigit.</div>
</main>
<script>
const DATA = %%DATA%%, KEY = "%%KEY%%", NAME = %%NAME%%;
let picks = {};
const $ = (id) => document.getElementById(id);
const esc = (t) => String(t ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const keyOf = (l) => `${l.value}|${l.footprint}`;
const own = (l) => l.mpn || l.digikey || l.mouser || l.lcsc;  // a number from the schematic
const enc = (q) => encodeURIComponent(q).replace(/%20/g, "+");
function links(l) {
  const p = picks[keyOf(l)], q = !own(l) && p?.mpn ? p.mpn : null;  // a pick searches for itself
  const url = (site) => q ? { digikey: "https://www.digikey.com/en/products/result?keywords=", mouser: "https://www.mouser.com/c/?q=",
    lcsc: "https://www.lcsc.com/search?q=" }[site] + enc(q) : l.links[site];
  return `<a href="${esc(url("digikey"))}" target="_blank" rel="noopener">Digi-Key</a>` +
    `<a href="${esc(url("mouser"))}" target="_blank" rel="noopener">Mouser</a>` +
    `<a href="${esc(url("lcsc"))}" target="_blank" rel="noopener">LCSC</a>`;
}
function number(l) {
  if (l.mpn) return `<span class="num">${esc(l.manufacturer ? l.manufacturer + " " : "")}${esc(l.mpn)}</span>`;
  const other = [["Digi-Key", l.digikey], ["Mouser", l.mouser], ["LCSC", l.lcsc]].filter(([, v]) => v);
  if (other.length) return other.map(([s, v]) => `<span class="num">${s} ${esc(v)}</span>`).join("<br>");
  return "";
}
function status(l) {
  if (l.dnp) return `<span class="chip dnp">DNP</span>`;
  if (own(l)) return `<span class="chip ok">in schematic</span>`;
  if (picks[keyOf(l)]?.mpn) return `<span class="chip picked">picked</span>`;
  return `<span class="chip need" title="No part number in the schematic: search, then put the one you choose in Your pick">needs a part number</span>`;
}
function render() {
  const f = $("filter").value.trim().toLowerCase(), show = $("show").value;
  const rows = DATA.lines.filter((l) => {
    const has = own(l) || picks[keyOf(l)]?.mpn;
    if (show === "need" && (has || l.dnp)) return false;
    if (show === "has" && !has) return false;
    if (!f) return true;
    return [l.refs.join(" "), l.value, l.footprint, l.mpn, l.manufacturer, l.description, picks[keyOf(l)]?.mpn]
      .join(" ").toLowerCase().includes(f);
  });
  $("rows").innerHTML = rows.map((l) => {
    const i = DATA.lines.indexOf(l), p = picks[keyOf(l)] || {};
    const pick = own(l) ? `<span class="sub">from the schematic</span>` :
      `<div class="pick" data-i="${i}"><input class="mpn" placeholder="MPN" value="${esc(p.mpn)}" aria-label="Part number you chose">` +
      `<input class="maker" placeholder="Manufacturer" value="${esc(p.manufacturer)}" aria-label="Manufacturer">` +
      `<input class="note" placeholder="Note" value="${esc(p.note)}" aria-label="Note"><span class="saved"></span></div>`;
    return `<tr class="${l.dnp ? "dnp" : ""}"><td class="qty">${l.qty}</td><td class="refs">${esc(l.refs.join(", "))}</td>` +
      `<td>${esc(l.value)}<div class="pkg">${esc(l.package)}</div>${l.description ? `<div class="desc">${esc(l.description)}</div>` : ""}</td>` +
      `<td>${number(l)} ${status(l)}</td><td class="links">${links(l)}</td><td>${pick}</td></tr>`;
  }).join("") || `<tr><td colspan="6" class="empty">Nothing to show.</td></tr>`;
  stats();
}
function stats() {
  const lines = DATA.lines, need = lines.filter((l) => !l.dnp && !own(l) && !picks[keyOf(l)]?.mpn).length;
  $("stats").innerHTML = `<span><b>${lines.length}</b> lines</span><span><b>${DATA.summary.parts}</b> parts</span>` +
    (DATA.summary.dnp_parts ? `<span><b>${DATA.summary.dnp_parts}</b> not populated</span>` : "") +
    `<span style="color:${need ? "var(--warn)" : "var(--ok)"}"><b>${need}</b> need a part number</span>`;
  document.documentElement.style.setProperty("--head", $("head").offsetHeight + "px");
}
// Picks: saved a moment after typing stops.
const timers = {};
$("rows").addEventListener("input", (e) => {
  const box = e.target.closest(".pick"); if (!box) return;
  const l = DATA.lines[+box.dataset.i], k = keyOf(l);
  const pick = { mpn: box.querySelector(".mpn").value, manufacturer: box.querySelector(".maker").value, note: box.querySelector(".note").value };
  box.querySelector(".saved").textContent = "";
  clearTimeout(timers[k]);
  timers[k] = setTimeout(async () => {
    try {
      const r = await fetch(`/bom/${KEY}/picks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: k, pick }) });
      if (!r.ok) throw new Error((await r.json()).error || r.status);
      picks = await r.json();
      box.querySelector(".saved").textContent = "saved";
      const row = box.closest("tr"); row.children[3].innerHTML = `${number(l)} ${status(l)}`; row.children[4].innerHTML = links(l);
      stats();
    } catch (err) { box.querySelector(".saved").textContent = "not saved: " + err.message; box.querySelector(".saved").style.color = "var(--bad)"; }
  }, 600);
});
$("filter").addEventListener("input", render);
$("show").addEventListener("change", render);
// The CSV: what Digi-Key's BOM Manager and Mouser's BOM Tool read (they let you match the columns).
function csv() {
  const boards = Math.max(1, parseInt($("boards").value, 10) || 1), withDnp = $("dnp").checked;
  const cell = (v) => { v = String(v ?? ""); return /[",\\n\\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v; };
  const out = [["Quantity", "Manufacturer", "Manufacturer Part Number", "Digi-Key Part Number", "Mouser Part Number", "LCSC Part Number",
    "References", "Value", "Footprint", "DNP", "Note"]];
  for (const l of DATA.lines) {
    if (l.dnp && !withDnp) continue;
    const p = own(l) ? {} : (picks[keyOf(l)] || {});
    out.push([l.dnp ? 0 : l.qty * boards, l.manufacturer || p.manufacturer, l.mpn || p.mpn, l.digikey, l.mouser, l.lcsc,
      l.refs.join(" "), l.value, l.footprint, l.dnp ? "DNP" : "", p.note]);
  }
  return out.map((r) => r.map(cell).join(",")).join("\\r\\n") + "\\r\\n";
}
$("export").addEventListener("click", () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv()], { type: "text/csv" }));
  a.download = `${NAME}-bom.csv`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
window.kigitBom = { csv, picks: () => picks };  // for scripted checks
fetch(`/bom/${KEY}/picks`).then((r) => r.json()).then((p) => { picks = p; render(); }).catch(() => render());
addEventListener("resize", stats);
</script>
</body>
</html>
"""
