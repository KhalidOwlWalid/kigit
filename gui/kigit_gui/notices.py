"""The notification centre: warnings and errors of this session, kept so
they can be read after their pop-up is gone (the header's bell, with a red
"!" while any are unread), and two pages that open in their own tab:
/notices (these notifications) and /log (the session log). Both refresh by
themselves.

Everything here is also in the session log; this is a readable view of it.
"""

from __future__ import annotations

import html
import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime

from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from nicegui import app

from . import logs

LEVELS = ("error", "warning", "info", "mention")  # mention: someone linked to your discussion
KEEP = 200  # newest kept


@dataclass
class Notice:
    level: str                      # error, warning, info or mention
    title: str
    detail: str = ""
    headers: tuple[str, ...] = ()   # a table, e.g. ("Part", "Model file")
    rows: list[tuple[str, ...]] = field(default_factory=list)
    when: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    id: int = 0
    read: bool = False
    go: str = ""                    # where to fix it, for a page that can open it ("bom:keys", "bom:carts"...)

    def to_dict(self) -> dict:
        return {"id": self.id, "level": self.level, "title": self.title, "detail": self.detail,
                "headers": list(self.headers), "rows": [list(r) for r in self.rows], "when": self.when,
                "read": self.read, "go": self.go}


_ids = itertools.count(1)
items: list[Notice] = []  # newest first
version = 0               # changes whenever the list does (the GUI's bell watches it)


def warn(message: str, detail: str = "") -> Notice:
    """A warning: shown now, in the log, and kept for the bell."""
    from nicegui import ui

    logs.log.warning("shown to user: %s%s", message, f" ({detail})" if detail else "")
    ui.notify(message, type="warning", multi_line=True, close_button=True)
    return add("warning", message, detail)


def add(level: str, title: str, detail: str = "", headers: tuple[str, ...] = (),
        rows: list[tuple[str, ...]] | None = None, go: str = "") -> Notice:
    global version
    n = Notice(level if level in LEVELS else "info", title, detail, tuple(headers), list(rows or []), id=next(_ids),
               go=go)
    items.insert(0, n)
    del items[KEEP:]
    version += 1
    # What the bell shows, in the log too (debug: whoever added it logs the
    # problem itself); a list goes in whole, for later.
    logs.log.debug("bell (%s): %s%s", n.level, title, f": {detail}" if detail else "")
    if n.rows:
        logs.log.info("notice: %s\n%s", title, "\n".join("  " + "  ".join(r) for r in n.rows))
    return n


def unread_problems() -> int:
    return sum(1 for n in items if not n.read and n.level in ("error", "warning"))


def unread_mentions() -> int:
    return sum(1 for n in items if not n.read and n.level == "mention")


def mark_read() -> None:
    global version
    if any(not n.read for n in items):
        for n in items:
            n.read = True
        version += 1


def clear() -> None:
    global version
    items.clear()
    version += 1


# ------------------------------------------------------------- tab pages
@app.get("/notices")
async def _notices_page() -> Response:
    return HTMLResponse(_PAGE.replace("%%TITLE%%", "kigit notifications").replace("%%KIND%%", "notices"))


@app.get("/notices.json")
async def _notices_json() -> Response:
    return JSONResponse({"version": version, "items": [n.to_dict() for n in items]})


@app.post("/notices/read")
async def _notices_read() -> Response:
    """Seen (the BOM page's bell was opened): the badges go everywhere."""
    mark_read()
    return JSONResponse({"version": version})


@app.get("/log")
async def _log_page() -> Response:
    return HTMLResponse(_PAGE.replace("%%TITLE%%", "kigit session log").replace("%%KIND%%", "log"))


@app.get("/log.txt")
async def _log_text(n: int = 2000) -> Response:
    if not logs.session_file:
        return PlainTextResponse("Logging to a file is off for this session (started with --no-log).")
    return PlainTextResponse("\n".join(logs.tail(max(1, min(n, 20000)))))


def html_table(n: Notice) -> str:
    """A notice's table as HTML (the GUI shows it the same way)."""
    if not n.rows:
        return ""
    head = "".join(f"<th>{html.escape(h)}</th>" for h in n.headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in r) + "</tr>" for r in n.rows)
    return f'<table class="kigit-notice-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<style>
:root { --bg: #0f1115; --panel: #161a20; --line: #29303a; --text: #e6e9ee; --muted: #9aa4b2; --faint: #6b7584;
  --accent: #e8b84d; --error: #f07178; --warning: #e8b84d; --info: #7fb3ff; --mention: #c39bff; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
header { position: sticky; top: 0; display: flex; gap: 12px; align-items: center; padding: 10px 18px;
  background: var(--panel); border-bottom: 1px solid var(--line); z-index: 1; }
header b { color: var(--accent); } header .t { font-weight: 600; } header .s { color: var(--faint); font-size: 12px; margin-left: auto; }
input[type=search] { background: var(--bg); color: var(--text); border: 1px solid var(--line); border-radius: 6px; padding: 5px 9px; font: inherit; width: 16rem; }
label { color: var(--muted); font-size: 13px; display: flex; gap: 6px; align-items: center; }
main { padding: 14px 18px 40px; }
.n { background: var(--panel); border: 1px solid var(--line); border-left: 3px solid var(--line); border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; }
.n.error { border-left-color: var(--error); } .n.warning { border-left-color: var(--warning); } .n.info { border-left-color: var(--info); }
.n.mention { border-left-color: var(--mention); } .mention .lvl { color: var(--mention); }
.n .h { display: flex; gap: 10px; align-items: baseline; } .n .when { color: var(--faint); font-size: 12px; font-variant-numeric: tabular-nums; }
.n .lvl { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
.error .lvl { color: var(--error); } .warning .lvl { color: var(--warning); } .info .lvl { color: var(--info); }
.n .d { color: var(--muted); margin-top: 4px; white-space: pre-wrap; }
table { border-collapse: collapse; margin-top: 8px; font-size: 13px; }
th { text-align: left; color: var(--muted); font-weight: 500; } th, td { padding: 3px 14px 3px 0; border-bottom: 1px solid var(--line); }
td { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; }
pre { margin: 0; font: 12px/1.5 ui-monospace, Menlo, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
pre .warn { color: var(--warning); } pre .err { color: var(--error); } pre .dbg { color: var(--faint); }
.empty { color: var(--faint); font-style: italic; }
</style>
</head>
<body>
<header><b>kigit</b><span class="t" id="title"></span>
  <input type="search" id="q" placeholder="Filter" autocomplete="off">
  <label id="followBox"><input type="checkbox" id="follow" checked> Follow</label>
  <span class="s" id="status"></span></header>
<main id="out"></main>
<script>
const KIND = "%%KIND%%";
const out = document.getElementById("out"), q = document.getElementById("q"), status = document.getElementById("status");
const follow = document.getElementById("follow");
document.getElementById("title").textContent = KIND === "log" ? "Session log" : "Notifications";
if (KIND !== "log") document.getElementById("followBox").style.display = "none";
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let data = null, last = "";
function show() {
  const words = q.value.toLowerCase().split(/\\s+/).filter(Boolean);
  const hit = (t) => words.every((w) => t.toLowerCase().includes(w));
  if (KIND === "log") {
    const lines = (data || "").split("\\n").filter(hit);
    const cls = (l) => /\\[warning\\]/.test(l) ? "warn" : /\\[(error|critical)\\]/.test(l) ? "err" : /\\[debug\\]/.test(l) ? "dbg" : "";
    out.innerHTML = "<pre>" + lines.map((l) => `<span class="${cls(l)}">${esc(l)}</span>`).join("\\n") + "</pre>";
    if (follow.checked) window.scrollTo(0, document.body.scrollHeight);
    status.textContent = `${lines.length} lines · refreshes by itself`;
    return;
  }
  const items = (data?.items || []).filter((n) => hit(n.title + " " + n.detail + " " + n.rows.flat().join(" ")));
  out.innerHTML = items.length ? items.map((n) => `<div class="n ${n.level}"><div class="h"><span class="lvl">${n.level}</span>` +
    `<b>${esc(n.title)}</b><span class="when">${esc(n.when)}</span></div>` +
    (n.detail ? `<div class="d">${esc(n.detail)}</div>` : "") +
    (n.rows.length ? `<table><tr>${n.headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>` +
      n.rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("") + "</table>" : "") +
    "</div>").join("") : '<p class="empty">No notifications.</p>';
  status.textContent = `${items.length} notification${items.length === 1 ? "" : "s"} · refreshes by itself`;
}
async function load() {
  try {
    const r = await fetch(KIND === "log" ? "/log.txt?n=3000" : "/notices.json", { cache: "no-store" });
    const text = await r.text();
    if (text !== last) { last = text; data = KIND === "log" ? text : JSON.parse(text); show(); }
  } catch { status.textContent = "kigit isn't running any more"; }
}
q.addEventListener("input", show);
load();
setInterval(load, 2000);
</script>
</body>
</html>
"""
