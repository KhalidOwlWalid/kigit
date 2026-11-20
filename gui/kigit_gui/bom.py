"""The BOM page: the board's bill of materials (kigit bom --json), and an
editor for its part information: MPN, manufacturer, distributor part
numbers and any information field you add. Not a schematic editor: kigit
only ever writes those fields (kigit bom --write refuses KiCad's own and
anything that would change the design), never values, footprints, the
board or the wiring.

Beside the list: the board in 2D (kigit's own board data, REV..REV) and
in 3D (the 3D view's model, made after the page opens). Hovering a line
lights its parts up in both; hovering a part lights its line up.

Edits are drafts until you write them, kept next to the board in
kigit-bom.json (in git, so they go with the project): {"version": 2,
"drafts": {line key: {field name: value}}, "columns": [added fields],
"tracking": {"columns": [tracker names], "done": {name: [refs]}}}.
What's bought belongs to a build (builds.py: kigit-builds/<id>/build.json),
not the design: its trackers ("Sourced", "Carted"...: your own tick
columns, never written into the schematic, ticked per part reference so
they survive a line's part number changing or lines regrouping) and its
carts from Mouser or LCSC (cart.py), one per site: {site: {"file", "time",
"received"?, "rows": [{sku, mpn, manufacturer, description, qty, refs,
assigned?}]}}, matched to the BOM's lines (match_carts) for the Ordered
column and the board view. state(board, build) is the drafts plus the
build's; save_state writes each to its own file. Receiving a cart adds it
to your inventory (inventory.py).
Only made when asked (the header's BOM button); nothing runs in the
background.

Look up asks Mouser and Digi-Key (kigit bom --lookup: each site with a
key) for stock, prices and lifecycle, only when pressed; the answer is
kept with the job for the page. Keys go to kigit on stdin (kigit bom
--set-key); the page only learns whether one is set (kigit bom --keys).
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import os
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from nicegui import app

from . import kigit, logs

DRAFTS = "kigit-bom.json"


@dataclass
class Job:
    board: str
    title: str
    data: dict
    rev: str = "LOCAL"              # only the working tree can be written
    board_json: str = ""            # the 2D view's data, a file in CACHE ("" if it couldn't be made)
    glb: str = ""                   # the 3D model, a file in CACHE (made after the page opens)
    model_ready: bool = False
    model_error: str = ""
    expected: float | None = None   # seconds the 3D build should take, if known
    started: float = field(default_factory=time.monotonic)
    backup: str = ""                # the last write's backup, for Undo
    lookup: Lookup = field(default_factory=lambda: Lookup())


@dataclass
class Lookup:
    """A Look up: running, then its result (kigit bom --lookup --json) or error."""
    running: bool = False
    done: int = 0
    total: int = 0
    boards: int = 1
    sites: str = ""                 # "Mouser and Digi-Key": who's being asked
    result: dict | None = None
    error: str = ""
    task: asyncio.Task | None = None

    def state(self) -> dict:
        return {"running": self.running, "done": self.done, "total": self.total, "boards": self.boards,
                "sites": self.sites, "result": self.result, "error": self.error}


jobs: dict[str, Job] = {}


def new_job(job: Job) -> str:
    key = secrets.token_hex(8)
    jobs[key] = job
    return key


def line_key(line: dict) -> str:
    """A line's name for drafts: its value and footprint, and its part number
    if it has one (two lines can share a value and footprint)."""
    number = line.get("mpn") or line.get("lcsc") or line.get("digikey") or line.get("mouser") or ""
    return f"{line.get('value', '')}|{line.get('footprint', '')}" + (f"|{number}" if number else "")


def drafts_path(board: str | Path) -> Path:
    return Path(board).parent / DRAFTS


def _tracking(data: dict) -> dict:
    t = data.get("tracking") if isinstance(data.get("tracking"), dict) else {}
    cols = t.get("columns") if isinstance(t.get("columns"), list) else []
    names = list(dict.fromkeys(c for c in cols if isinstance(c, str) and c.strip()))
    done = t.get("done") if isinstance(t.get("done"), dict) else {}
    ticked = {n: done[n] for n in names if isinstance(done.get(n), list) and done[n]}
    return {"columns": names, "done": {n: sorted({r for r in refs if isinstance(r, str)}) for n, refs in ticked.items()}}


def _carts(data: dict) -> dict:
    from .cart import SITES
    carts = data.get("carts") if isinstance(data.get("carts"), dict) else {}
    out = {}
    for site, c in carts.items():
        if site not in SITES or not isinstance(c, dict) or not isinstance(c.get("rows"), list):
            continue
        rows = []
        for r in c["rows"]:
            if not isinstance(r, dict):
                continue
            row = {k: str(r.get(k, "")) for k in ("sku", "mpn", "manufacturer", "description")}
            try:
                row["qty"] = max(0, int(r.get("qty", 0)))
            except (TypeError, ValueError):
                row["qty"] = 0
            row["refs"] = [x for x in r.get("refs", []) if isinstance(x, str)] if isinstance(r.get("refs"), list) else []
            if isinstance(r.get("assigned"), list):
                row["assigned"] = [x for x in r["assigned"] if isinstance(x, str)]
            rows.append(row)
        out[site] = {"file": str(c.get("file", "")), "time": str(c.get("time", "")), "rows": rows}
        if c.get("received"):
            out[site]["received"] = str(c["received"])
            out[site]["moved"] = [m for m in c.get("moved", []) if isinstance(m, dict)]
    return out


def load_drafts(board: str | Path) -> dict:
    """{"drafts": {line key: {field: value}}, "columns": [field, ...],
    "tracking": {"columns": [...], "done": {name: [refs]}}}. A version 1
    file (picks: mpn, manufacturer, note) is read as drafts."""
    try:
        data = json.loads(drafts_path(board).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    drafts: dict[str, dict[str, str]] = {}
    columns = [c for c in data.get("columns", []) if isinstance(c, str)]
    if data.get("version", 1) == 1 and isinstance(data.get("picks"), dict):
        names = {"mpn": "MPN", "manufacturer": "Manufacturer", "note": "Note"}
        for k, pick in data["picks"].items():
            if isinstance(pick, dict):
                d = {names[f]: str(v) for f, v in pick.items() if f in names and v}
                if d:
                    drafts[k] = d
        if any("Note" in d for d in drafts.values()) and "Note" not in columns:
            columns.append("Note")
    else:
        for k, d in (data.get("drafts") or {}).items():
            if isinstance(d, dict):
                drafts[k] = {str(f): str(v) for f, v in d.items()}
    # Trackers and carts used to be kept here, for the whole BOM; they're per
    # build now (kigit-builds/), and the old ones were left behind on purpose.
    return {"drafts": drafts, "columns": columns, "tracking": _tracking({}), "carts": {}}


def save_drafts(board: str | Path, state: dict) -> None:
    drafts = {k: dict(sorted(d.items())) for k, d in sorted(state["drafts"].items()) if d}
    columns = list(dict.fromkeys(state.get("columns", [])))
    path = drafts_path(board)
    if not drafts and not columns:
        path.unlink(missing_ok=True)
        return
    out = {"version": 2, "drafts": drafts, "columns": columns}
    text = json.dumps(out, indent=2, ensure_ascii=False) + "\n"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(path)


def set_draft(board: str | Path, key: str, name: str, value: str | None) -> dict:
    """One cell: a value, or None to drop the draft. Re-reads the file first,
    so two pages don't undo each other."""
    state = load_drafts(board)
    cell = state["drafts"].setdefault(key, {})
    if value is None:
        cell.pop(name, None)
    else:
        cell[name] = value.strip()[:500]
    save_drafts(board, state)
    return load_drafts(board)


def add_column(board: str | Path, name: str) -> dict:
    state = load_drafts(board)
    if name not in state["columns"]:
        state["columns"].append(name)
    save_drafts(board, state)
    return load_drafts(board)


def rename_column(board: str | Path, old: str, new: str) -> dict:
    """An added field column's new title, with its drafts. (Values already in
    the schematic are renamed there by kigit bom --write.)"""
    state = load_drafts(board)
    state["columns"] = [new if c == old else c for c in state["columns"]]
    if new not in state["columns"]:
        state["columns"].append(new)
    for d in state["drafts"].values():
        if old in d:
            d[new] = d.pop(old)
    save_drafts(board, state)
    return load_drafts(board)


class NoBuild(ValueError):
    """Trackers and carts belong to a build, and none was picked."""


def state(board: str | Path, build: str = "") -> dict:
    """The drafts (kigit-bom.json), with the build's trackers and carts (its
    build.json); none of those with no build. Re-read every time."""
    st = load_drafts(board)
    st["build"] = build or ""
    if build:
        from . import builds
        extra = builds.load_extra(board, build)
        st["tracking"], st["carts"] = _tracking(extra), _carts(extra)
    return st


def save_state(board: str | Path, st: dict, drafts_too: bool = False) -> None:
    """The build's trackers and carts into its build.json (and the drafts,
    if they changed too)."""
    from . import builds
    if not st.get("build"):
        raise NoBuild("pick a build first: trackers and carts belong to a build")
    builds.save_extra(board, st["build"], {"tracking": _tracking({"tracking": st["tracking"]}),
                                           "carts": _carts({"carts": st["carts"]})})
    if drafts_too:
        save_drafts(board, st)


def rename_tracker(board: str | Path, build: str, old: str, new: str) -> dict:
    st = state(board, build)
    t = st["tracking"]
    t["columns"] = [new if c == old else c for c in t["columns"]]
    if old in t["done"]:
        t["done"][new] = t["done"].pop(old)
    save_state(board, st)
    return state(board, build)


def add_tracker(board: str | Path, build: str, name: str) -> dict:
    st = state(board, build)
    if name not in st["tracking"]["columns"]:
        st["tracking"]["columns"].append(name)
    save_state(board, st)
    return state(board, build)


def remove_tracker(board: str | Path, build: str, name: str) -> dict:
    st = state(board, build)
    t = st["tracking"]
    t["columns"] = [c for c in t["columns"] if c != name]
    t["done"].pop(name, None)
    save_state(board, st)
    return state(board, build)


def set_tracked(board: str | Path, build: str, name: str, refs: list[str], done: bool) -> dict:
    """Ticks (or unticks) parts in a build's tracker. Re-reads the file first."""
    st = state(board, build)
    t = st["tracking"]
    if name not in t["columns"]:
        t["columns"].append(name)
    have = set(t["done"].get(name, []))
    have = have | set(refs) if done else have - set(refs)
    t["done"][name] = sorted(have)
    save_state(board, st)
    return state(board, build)


# ------------------------------------------------------------------ carts
_LABELS = {"mpn": "MPN", "manufacturer": "Manufacturer", "digikey": "Digi-Key", "mouser": "Mouser", "lcsc": "LCSC"}


def _norm(pn: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (pn or "").upper())


def shown_number(line: dict, kind: str, drafts: dict, field_names: dict) -> str:
    """A line's part number as the page shows it: a draft if there is one."""
    name = field_names.get(kind) or _LABELS[kind]
    d = drafts.get(line_key(line), {})
    return (d[name] if name in d else line.get(kind, "")) or ""


def match_carts(data: dict, state: dict) -> dict:
    """Which cart rows are which BOM line: by the references in the row (its
    Customer # from kigit's export, or a line you assigned it to), else the
    site's own part number, else the MPN (both compared as letters and
    digits). {"lines": {line key: {"qty": {site: n}, "rows": [...]}},
    "unmatched": [...], "carts": {site: {file, time, rows}}}."""
    lines = [l for l in data.get("lines", []) if not l.get("dnp")]
    fn, drafts = data.get("field_names") or {}, state.get("drafts") or {}
    by_ref = {r: l for l in lines for r in l["refs"]}
    out: dict = {"lines": {}, "unmatched": [], "carts": {}}
    for site, c in (state.get("carts") or {}).items():
        out["carts"][site] = {"file": c["file"], "time": c["time"], "rows": len(c["rows"]), "received": c.get("received", "")}
        if c.get("received"):
            continue  # in your inventory now (In stock), not ordered any more
        sku_of = {_norm(shown_number(l, site, drafts, fn)): l for l in lines if shown_number(l, site, drafts, fn)}
        mpn_of = {_norm(shown_number(l, "mpn", drafts, fn)): l for l in lines if shown_number(l, "mpn", drafts, fn)}
        for i, row in enumerate(c["rows"]):
            line, by = None, ""
            refs = row.get("assigned") or row.get("refs") or []
            if refs:
                # The line with most of these parts (lines may have regrouped since the export).
                hits = [by_ref[r] for r in refs if r in by_ref]
                if hits:
                    line = max(hits, key=lambda l: sum(r in refs for r in l["refs"]))
                    by = "assigned" if row.get("assigned") else "references"
            if line is None and row["sku"] and _norm(row["sku"]) in sku_of:
                line, by = sku_of[_norm(row["sku"])], f"{SITE_NAMES.get(site, site)} number"
            if line is None and row["mpn"] and _norm(row["mpn"]) in mpn_of:
                line, by = mpn_of[_norm(row["mpn"])], "MPN"
            entry = {**row, "site": site, "i": i, "by": by}
            if line is None:
                out["unmatched"].append(entry)
                continue
            m = out["lines"].setdefault(line_key(line), {"qty": {}, "rows": []})
            m["qty"][site] = m["qty"].get(site, 0) + row["qty"]
            m["rows"].append(entry)
    return out


SITE_NAMES = {"mouser": "Mouser", "lcsc": "LCSC"}


def import_cart(board: str | Path, build: str, site: str, filename: str, data: bytes) -> dict:
    """Reads a cart file into a build (replacing that site's last one)."""
    from .cart import parse_cart
    rows = parse_cart(data, filename, site)
    st = state(board, build)
    st["carts"][site] = {"file": Path(filename).name[:200], "time": time.strftime("%Y-%m-%d %H:%M"), "rows": rows}
    save_state(board, st)
    return state(board, build)


def remove_cart(board: str | Path, build: str, site: str) -> dict:
    st = state(board, build)
    st["carts"].pop(site, None)
    save_state(board, st)
    return state(board, build)


def receive_cart(board: str | Path, build: str, data: dict, site: str, undo: bool = False) -> dict:
    """The cart arrived: each row's quantity goes into your inventory (the
    part found by the row's MPN or site number, or as its line's passive),
    and it stops counting as ordered. A line the row matched that has no
    part number yet gets the row's (MPN, manufacturer, site number) as
    drafts, so it finds its stock (you write them, or not). undo takes the
    quantities back out (exactly what was added) and makes it ordered again."""
    from . import inventory
    where = inventory.location()
    if where is None:
        raise inventory.InventoryError("choose your inventory file first (Inventory, in the header)")
    st = state(board, build)
    c = st["carts"].get(site)
    if c is None:
        raise ValueError(f"no {SITE_NAMES.get(site, site)} cart in this build")
    if undo:
        if not c.get("received"):
            raise ValueError("that cart isn't received")
        inventory.change(where, deltas=[(m["ids"], -int(m["qty"])) for m in c.get("moved", [])])
        c.pop("received", None)
        c.pop("moved", None)
    else:
        if c.get("received"):
            raise ValueError(f"that cart was received already ({c['received']})")
        match = match_carts(data, st)
        line_of = {(r["site"], r["i"]): k for k, m in match["lines"].items() for r in m["rows"]}
        lines = {line_key(l): l for l in data.get("lines", [])}
        fn = data.get("field_names") or {}
        moved, add = [], {}
        for i, row in enumerate(c["rows"]):
            ids = {k: v for k, v in (("mpn", row["mpn"]), (site, row["sku"]), ("manufacturer", row["manufacturer"])) if v}
            line = lines.get(line_of.get((site, i), ""))
            if line is not None:  # a passive's kind, value and package: found as such if that's how you keep it
                ids.update({k: v for k, v in line_ids(line, st["drafts"], fn).items()
                            if k in ("kind", "value", "package")})
                # No part number on the line yet: this cart's, as drafts, so the line finds what arrived.
                if not any(shown_number(line, k, st["drafts"], fn) for k in ("mpn", "lcsc", "mouser", "digikey")):
                    d = st["drafts"].setdefault(line_key(line), {})
                    for kind, value in (("mpn", row["mpn"]), ("manufacturer", row["manufacturer"]), (site, row["sku"])):
                        if value and not shown_number(line, kind, st["drafts"], fn):
                            d[fn.get(kind) or _LABELS[kind]] = value
            if not inventory.keys_of(ids):
                continue
            moved.append({"ids": ids, "qty": row["qty"]})
            add[inventory.keys_of(ids)[0]] = {k: ids[k] for k in ("manufacturer",) if ids.get(k)}
        inventory.change(where, deltas=[(m["ids"], m["qty"]) for m in moved], add_fields=add)
        c["received"], c["moved"] = time.strftime("%Y-%m-%d %H:%M"), moved
    save_state(board, st, drafts_too=not undo)
    logs.log.info("bom: %s cart %s for build %s", site, "un-received" if undo else "received", build)
    return state(board, build)


def assign_row(board: str | Path, build: str, data: dict, site: str, i: int, refs: list[str] | None,
               keep: bool) -> dict:
    """A cart row given to a line by hand (refs), or let go (None). keep:
    also make its part numbers the line's drafts where the line has none."""
    state_ = state(board, build)
    rows = state_["carts"].get(site, {}).get("rows", [])
    if not 0 <= i < len(rows):
        raise ValueError("no such cart row")
    row = rows[i]
    if refs:
        row["assigned"] = list(refs)
    else:
        row.pop("assigned", None)
    if refs and keep:
        line = next((l for l in data.get("lines", []) if set(refs) & set(l["refs"])), None)
        if line is not None:
            fn, d = data.get("field_names") or {}, state_["drafts"].setdefault(line_key(line), {})
            for kind, value in (("mpn", row["mpn"]), ("manufacturer", row["manufacturer"]), (site, row["sku"])):
                if value and not shown_number(line, kind, state_["drafts"], fn):
                    d[fn.get(kind) or _LABELS[kind]] = value
    save_state(board, state_, drafts_too=True)
    return state(board, build)


# -------------------------------------------------------------- inventory
def line_ids(line: dict, drafts: dict, field_names: dict) -> dict:
    """What a line's part is, for the inventory (inventory.keys_of): its part
    numbers as shown (drafts count), kind, value and package."""
    ids = {k: shown_number(line, k, drafts, field_names) for k in ("mpn", "manufacturer", "lcsc", "mouser", "digikey")}
    ids.update({"kind": line.get("kind", ""), "value": line.get("value", ""), "package": line.get("package", "")})
    return {k: v for k, v in ids.items() if v}


def stock_of(data: dict, state: dict, inv) -> dict:
    """Each line's row in the inventory: {line key: {qty, by, label, row}};
    lines with nothing to find them by get {qty: null, why}."""
    from . import inventory
    fn, drafts = data.get("field_names") or {}, state.get("drafts") or {}
    out = {}
    for l in data.get("lines", []):
        if l.get("dnp"):
            continue
        ids = line_ids(l, drafts, fn)
        if not inventory.keys_of(ids):
            out[line_key(l)] = {"qty": None, "why": "no part number to look for (a passive needs a value and package)"}
            continue
        row, by = inv.find(ids)
        out[line_key(l)] = ({"qty": row.qty, "by": by, "label": row.label(), "row": row.line} if row
                            else {"qty": 0, "by": "", "missing": True})
    return out


def _stock_answer(job: Job) -> JSONResponse:
    from . import inventory
    inv, why = inventory.current()
    where = inventory.location()
    return JSONResponse({"path": str(where) if where else "", "error": "" if why in ("", "none") else why,
                         "configured": where is not None,
                         "inventory": inv.to_json() if inv else None,
                         "lines": stock_of(job.data, load_drafts(job.board), inv) if inv else {}})


# --------------------------------------------------------------- assembly
def place_parts(board: str | Path, build: str, data: dict, n: int, refs: list[str], placed: bool) -> dict:
    """Parts placed on (or taken off) board #n of a build. Placing one takes
    it out of your inventory, if it's in it (by its line's part numbers, or
    as a passive); taking it off puts back exactly what was taken. The board
    is done when every part on it (not DNP) is placed."""
    from . import builds, inventory
    b = builds.get_board(board, build, n)
    fn, drafts = data.get("field_names") or {}, load_drafts(board)["drafts"]
    line_of = {r: l for l in data.get("lines", []) for r in l["refs"]}
    every = {r for l in data.get("lines", []) if not l.get("dnp") for r in l["refs"]}
    where = inventory.location()
    inv = None
    if where is not None:
        try:
            inv = inventory.read(where)
        except inventory.InventoryError:
            inv = None  # not there: placing is still kept, nothing taken
    have, taken = set(b["placed"]), dict(b["taken"])
    deltas = []
    for r in refs:
        if r not in every:
            continue  # not on the BOM, or DNP
        if placed and r not in have:
            have.add(r)
            ids = line_ids(line_of[r], drafts, fn)
            if inv is not None and inv.find(ids)[0] is not None:
                deltas.append((ids, -1))
                taken[r] = ids
        elif not placed and r in have:
            have.discard(r)
            if r in taken:
                deltas.append((taken.pop(r), 1))
    if deltas:
        inventory.change(where, deltas=deltas)
    b["placed"], b["taken"] = sorted(have), taken
    done = bool(every) and every <= have
    if done and b["status"] != "done":
        b["status"], b["finished"] = "done", time.strftime("%Y-%m-%d %H:%M")
    elif not done and b["status"] == "done":
        b["status"], b["finished"] = "in progress", ""
    logs.log.info("bom: build %s board #%d: %s %d part(s), %d from the inventory", build, n,
                  "placed" if placed else "took off", len(refs), len(deltas))
    return builds.save_board(board, build, b)


def _job(key: str) -> Job | None:
    return jobs.get(key)


@app.get("/bom/{key}")
async def _page(key: str) -> Response:
    job = _job(key)
    if job is None:
        return HTMLResponse("<p style='font-family:sans-serif;color:#aaa'>This BOM is gone (kigit was restarted?). "
                            "Press BOM again.</p>", status_code=404)
    return HTMLResponse(page(key, job))


@app.get("/bom/{key}/board.json")
async def _board(key: str) -> Response:
    from .app import CACHE

    job = _job(key)
    if job is None or not job.board_json or not (CACHE / job.board_json).is_file():
        return JSONResponse({"error": "no board data"}, status_code=404)
    return FileResponse(CACHE / job.board_json, media_type="application/json")


@app.get("/bom/{key}/status")
async def _status(key: str) -> Response:
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    return JSONResponse({"ready": job.model_ready, "error": job.model_error, "glb": f"/diffs/{job.glb}",
                         "elapsed": time.monotonic() - job.started, "expected": job.expected})


@app.get("/bom/{key}/drafts")
async def _drafts(key: str, build: str = "") -> Response:
    """The drafts, with the build's trackers and carts (build: its id, "" for none)."""
    from .builds import BuildError
    job = _job(key)
    if job is None:
        return JSONResponse({}, status_code=404)
    try:
        return JSONResponse(state(job.board, build))
    except BuildError:
        return JSONResponse(state(job.board, ""))  # that build is gone: just the drafts


@app.post("/bom/{key}/drafts")
async def _set_draft(key: str, request: Request) -> Response:
    """Drafts (part numbers, added columns) and the build's trackers. Answers
    with state(board, build)."""
    from .builds import BuildError
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    body = await request.json()
    build = str(body.get("build") or "")
    try:
        if body.get("column"):
            add_column(job.board, str(body["column"]).strip()[:100])
        elif body.get("rename_column") or body.get("rename_tracker"):  # {rename_column | rename_tracker, to}
            new = str(body.get("to", "")).strip()[:100]
            if not new or any(ch in new for ch in "\r\n"):
                return JSONResponse({"error": "a column needs a name (one line)"}, status_code=400)
            if body.get("rename_tracker"):
                return JSONResponse(rename_tracker(job.board, build, str(body["rename_tracker"]), new[:60]))
            rename_column(job.board, str(body["rename_column"]), new)
        elif body.get("tracker"):  # {tracker, remove?}: add or remove a tracker column
            name = str(body["tracker"]).strip()[:60]
            return JSONResponse(remove_tracker(job.board, build, name) if body.get("remove")
                                else add_tracker(job.board, build, name))
        elif body.get("track"):  # {track, refs, done}: tick parts
            refs = [str(r) for r in body.get("refs", []) if isinstance(r, str)][:5000]
            return JSONResponse(set_tracked(job.board, build, str(body["track"]).strip()[:60], refs,
                                            bool(body.get("done"))))
        else:
            line, name = str(body.get("key", "")), str(body.get("field", ""))
            if not line or not name:
                return JSONResponse({"error": "no line or field"}, status_code=400)
            value = body.get("value")
            set_draft(job.board, line, name, None if value is None else str(value))
        return JSONResponse(state(job.board, build))
    except (NoBuild, BuildError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except OSError as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def _refresh(job: Job) -> None:
    job.data = await kigit.bom(job.board, job.rev)


@app.post("/bom/{key}/write")
async def _write(key: str, request: Request) -> Response:
    """Writes the given cells ({key, field, value}) into the schematic, by
    kigit bom --write, and drops their drafts."""
    from .app import CACHE

    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    if job.rev != "LOCAL":
        return JSONResponse({"error": "only the working tree can be written"}, status_code=400)
    body = await request.json()
    refs = {line_key(l): l["refs"] for l in job.data.get("lines", [])}
    every_ref = [r for l in job.data.get("lines", []) for r in l["refs"]]
    edits, cells, renames = [], [], []
    for rn in body.get("renames", []):  # a field column's new title: the field renamed on every part that has it
        old, new = str(rn.get("from", "")), str(rn.get("to", "")).strip()
        if not old or not new:
            return JSONResponse({"error": "a rename needs both names"}, status_code=400)
        edits.append({"refs": every_ref, "field": old, "rename": new})
        renames.append((old, new))
    for c in body.get("cells", []):
        k, name, value = str(c.get("key", "")), str(c.get("field", "")), str(c.get("value", ""))
        if k not in refs or not name:
            return JSONResponse({"error": f"no such line: {k}"}, status_code=400)
        edits.append({"refs": refs[k], "field": name, "value": value})
        cells.append((k, name))
    if not edits:
        return JSONResponse({"error": "nothing to write"}, status_code=400)
    try:
        result = await kigit.bom_write(job.board, edits, CACHE / f"bom-edits-{key}.json", bool(body.get("force")))
    except kigit.KigitError as e:
        return JSONResponse({"error": str(e), "locked": "KiCad has" in str(e)}, status_code=409)
    job.backup = result.get("backup") or job.backup
    left = load_drafts(job.board)
    for k, name in cells:
        left["drafts"].get(k, {}).pop(name, None)
    save_drafts(job.board, left)
    for old, new in renames:
        rename_column(job.board, old, new)
    await _refresh(job)
    logs.log.info("bom: wrote %s fields into %s", result.get("fields"), ", ".join(result.get("written", [])))
    try:
        answer = state(job.board, str(body.get("build") or ""))
    except ValueError:
        answer = state(job.board, "")
    return JSONResponse({"result": result, "data": job.data, "drafts": answer})


@app.post("/bom/{key}/undo")
async def _undo(key: str) -> Response:
    job = _job(key)
    if job is None or not job.backup:
        return JSONResponse({"error": "nothing to undo"}, status_code=400)
    try:
        result = await kigit.bom_restore(job.backup)
    except kigit.KigitError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    job.backup = ""
    await _refresh(job)
    logs.log.info("bom: undid the last write (%s)", ", ".join(result.get("restored", [])))
    return JSONResponse({"result": result, "data": job.data})


@app.get("/bom/{key}/notes")
async def _notes(key: str) -> Response:
    """How many notes pin each part ({ref: n}), for the + Notes buttons."""
    from . import notebook
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    return JSONResponse(await asyncio.to_thread(notebook.counts_by_part, Path(job.board).parent))


def _cart_answer(job: Job, st: dict) -> JSONResponse:
    return JSONResponse({"match": match_carts(job.data, st), "drafts": st})


@app.get("/bom/{key}/cart")
async def _cart(key: str, build: str = "") -> Response:
    """The build's carts matched to the lines (none without a build)."""
    from .builds import BuildError
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    try:
        return _cart_answer(job, state(job.board, build))
    except BuildError:
        return _cart_answer(job, state(job.board, ""))


@app.post("/bom/{key}/cart/{site}")
async def _import_cart(key: str, site: str, request: Request, name: str = "cart.csv", build: str = "") -> Response:
    """A cart file (the request's body), from Mouser or LCSC, into a build."""
    from .builds import BuildError
    from .cart import MAX_BYTES, CartError
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    data = await request.body()
    if len(data) > MAX_BYTES:
        return JSONResponse({"error": "the file is too big for a cart (over 5 MB)"}, status_code=400)
    try:
        if not build:
            raise NoBuild("pick or make a build first: a cart belongs to a build")
        st = await asyncio.to_thread(import_cart, job.board, build, site, name, data)
    except (CartError, NoBuild, BuildError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except OSError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    logs.log.info("bom: %s cart %s imported into %s (%d rows)", site, name, build, len(st["carts"].get(site, {}).get("rows", [])))
    return _cart_answer(job, st)


@app.post("/bom/{key}/cart/{site}/edit")
async def _edit_cart(key: str, site: str, request: Request) -> Response:
    """{build, remove: true} | {build, receive: true} | {build, unreceive: true} |
    {build, row, refs (null: unassign), keep}."""
    from .builds import BuildError
    from .inventory import InventoryError
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    body = await request.json()
    build = str(body.get("build") or "")
    try:
        if not build:
            raise NoBuild("pick a build first: carts belong to a build")
        if body.get("remove"):
            st = remove_cart(job.board, build, site)
        elif body.get("receive") or body.get("unreceive"):
            st = await asyncio.to_thread(receive_cart, job.board, build, job.data, site, bool(body.get("unreceive")))
        else:
            refs = body.get("refs")
            refs = [str(r) for r in refs if isinstance(r, str)] if isinstance(refs, list) else None
            st = assign_row(job.board, build, job.data, site, int(body.get("row", -1)), refs, bool(body.get("keep")))
    except (ValueError, TypeError, InventoryError, BuildError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return _cart_answer(job, st)


@app.get("/bom/{key}/builds")
async def _builds(key: str) -> Response:
    from . import builds
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    return JSONResponse({"builds": [b.to_dict() for b in builds.all_builds(job.board)]})


@app.post("/bom/{key}/builds")
async def _edit_builds(key: str, request: Request) -> Response:
    """{action: new, name, boards} | {action: update, id, name?, boards?} | {action: delete, id}.
    Answers {build (the one made or changed, or null), builds}."""
    from . import builds
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    body = await request.json()
    action = body.get("action")
    try:
        if action == "new":
            b = builds.new(job.board, str(body.get("name", "")), body.get("boards", 1), job.rev)
            logs.log.info("bom: new build %s (%d boards)", b.id, b.boards)
        elif action == "update":
            b = builds.update(job.board, str(body.get("id", "")), body.get("name"), body.get("boards"))
        elif action == "delete":
            builds.delete(job.board, str(body.get("id", "")))
            logs.log.info("bom: deleted build %s", body.get("id"))
            b = None
        else:
            return JSONResponse({"error": f"unknown action {action}"}, status_code=400)
    except builds.BuildError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except OSError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return JSONResponse({"build": b.to_dict() if b else None,
                         "builds": [x.to_dict() for x in builds.all_builds(job.board)]})


@app.get("/bom/{key}/stock")
async def _stock(key: str) -> Response:
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    return await asyncio.to_thread(_stock_answer, job)


@app.post("/bom/{key}/inventory")
async def _edit_inventory(key: str, request: Request) -> Response:
    """{action: choose | new, path} | {action: forget} | {action: set | adjust,
    key (a BOM line) or ids (a row), qty | delta}."""
    from . import inventory
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    body = await request.json()
    action = body.get("action")

    def run() -> None:
        if action in ("choose", "new"):
            path = Path(str(body.get("path", ""))).expanduser()
            if not path.is_absolute():
                raise inventory.InventoryError("give the file's full path")
            inv = inventory.create(path) if action == "new" else inventory.read(path)
            inventory.remember(path, inv)
            logs.log.info("inventory: %s %s (%d parts)", "made" if action == "new" else "chose", path, len(inv.rows))
        elif action == "forget":
            inventory.remember(None)
            logs.log.info("inventory: forgot the file (it stays where it is)")
        elif action in ("set", "adjust"):
            where = inventory.location()
            if where is None:
                raise inventory.InventoryError("choose your inventory file first")
            if body.get("key"):
                line = next((l for l in job.data.get("lines", []) if line_key(l) == body["key"]), None)
                if line is None:
                    raise inventory.InventoryError("no such line")
                ids = line_ids(line, load_drafts(job.board).get("drafts") or {}, job.data.get("field_names") or {})
            else:
                ids = {k: str(v) for k, v in (body.get("ids") or {}).items() if isinstance(v, str | int)}
            n = int(body.get("qty" if action == "set" else "delta", 0))
            keys = inventory.keys_of(ids)
            extra = {keys[0]: {k: ids[k] for k in ("manufacturer", "description") if ids.get(k)}} if keys else {}
            inventory.change(where, deltas=[(ids, n)] if action == "adjust" else None,
                             sets=[(ids, n)] if action == "set" else None, add_fields=extra)
        else:
            raise inventory.InventoryError(f"unknown action {action}")

    try:
        await asyncio.to_thread(run)
    except inventory.InventoryError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except (TypeError, ValueError) as e:
        return JSONResponse({"error": f"not a number: {e}"}, status_code=400)
    return await asyncio.to_thread(_stock_answer, job)


@app.get("/bom/{key}/browse")
async def _browse(key: str, dir: str = "") -> Response:
    """Folders and .csv files in a folder, for choosing the inventory file
    (a web page can't ask for a path). Only names, nothing read."""
    from . import inventory
    if _job(key) is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    where = inventory.location()
    d = Path(dir).expanduser() if dir else (where.parent if where else Path.home())
    try:
        d = d.resolve()
        entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
    except OSError as e:
        return JSONResponse({"error": f"can't open {d}: {e}"}, status_code=400)
    folders = [p.name for p in entries if p.is_dir() and not p.name.startswith(".")]
    files = [p.name for p in entries if p.is_file() and p.suffix.lower() == ".csv"]
    return JSONResponse({"dir": str(d), "parent": str(d.parent) if d.parent != d else "", "folders": folders,
                         "files": files, "sep": os.sep})


@app.get("/bom/{key}/boards")
async def _boards(key: str, build: str = "") -> Response:
    """A build's started boards (#1, #2...), with what's placed on each."""
    from . import builds
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    try:
        return JSONResponse({"boards": builds.boards(job.board, build) if build else []})
    except builds.BuildError:
        return JSONResponse({"boards": []})


@app.post("/bom/{key}/boards")
async def _edit_boards(key: str, request: Request) -> Response:
    """{build, action: start (n?) | place (n, refs, placed) | status (n, status) |
    notes (n, notes) | delete (n)}. Answers {boards, board}."""
    from . import builds, inventory
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    body = await request.json()
    build, action = str(body.get("build") or ""), body.get("action")

    def run() -> dict | None:
        if not build:
            raise NoBuild("pick a build first: boards belong to a build")
        n = body.get("n")
        if action == "start":
            return builds.start_board(job.board, build, None if n in (None, "") else int(n))
        if action == "place":
            refs = [str(r) for r in body.get("refs", []) if isinstance(r, str)][:5000]
            return place_parts(job.board, build, job.data, int(n), refs, bool(body.get("placed")))
        if action in ("status", "notes"):
            b = builds.get_board(job.board, build, int(n))
            if action == "status":
                if body.get("status") not in builds.BOARD_STATUS:
                    raise builds.BuildError("a board is in progress or done")
                b["status"] = body["status"]
                b["finished"] = time.strftime("%Y-%m-%d %H:%M") if b["status"] == "done" else ""
            else:
                b["notes"] = str(body.get("notes", ""))
            return builds.save_board(job.board, build, b)
        if action == "delete":
            builds.delete_board(job.board, build, int(n))
            return None
        raise builds.BuildError(f"unknown action {action}")

    try:
        b = await asyncio.to_thread(run)
    except (NoBuild, builds.BuildError, inventory.InventoryError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except (TypeError, ValueError) as e:
        return JSONResponse({"error": f"not a board number: {e}"}, status_code=400)
    return JSONResponse({"board": b, "boards": builds.boards(job.board, build)})


@app.get("/bom/{key}/keys")
async def _keys(key: str) -> Response:
    if _job(key) is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    try:
        return JSONResponse(await kigit.bom_keys())
    except kigit.KigitError as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/bom/{key}/keys")
async def _set_key(key: str, request: Request) -> Response:
    """Saves (or with "" removes) a site's API key, through kigit."""
    if _job(key) is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    body = await request.json()
    site = str(body.get("site", ""))
    if site == "mouser":
        lines = [str(body.get("key", ""))]
    elif site == "digikey":
        cid = str(body.get("client_id", ""))
        lines = [cid] if not cid.strip() else [cid, str(body.get("client_secret", "")),
                                               f"{body.get('locale_site', 'US')} {body.get('currency', 'USD')}"]
    else:
        return JSONResponse({"error": f"kigit has no lookups for {site}"}, status_code=400)
    if any(len(x) > 300 or "\n" in x or "\r" in x for x in lines):
        return JSONResponse({"error": "not a key kigit can keep"}, status_code=400)
    try:
        await kigit.bom_set_key(site, *lines)
        logs.log.info("bom: %s key %s", site, "saved" if lines[0].strip() else "removed")  # never the key
        return JSONResponse(await kigit.bom_keys())
    except kigit.KigitError as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def run_lookup(job: Job, boards: int, refresh: bool) -> None:
    look = job.lookup
    look.running, look.done, look.total, look.error, look.boards = True, 0, len(job.data.get("lines", [])), "", boards
    try:
        names = [k.get("name", s) for s, k in (await kigit.bom_keys()).items() if k.get("set")]
    except kigit.KigitError:
        names = []
    look.sites = " and ".join(names) or "the parts sites"

    def progress(done: int, total: int) -> None:
        look.done, look.total = done, total

    try:
        look.result = await kigit.bom_lookup(job.board, job.rev, boards, refresh, progress)
        look.done = look.total
        for site, info in look.result.get("sites", {}).items():
            if info.get("error"):
                logs.log.warning("bom lookup: %s: %s", site, info["error"])
    except kigit.KigitError as e:
        look.error = str(e)
    except (OSError, ValueError) as e:
        look.error = f"Couldn't look up: {e}"
        logs.log.warning("bom lookup failed: %s", e)
    finally:
        look.running = False


@app.post("/bom/{key}/lookup")
async def _start_lookup(key: str, request: Request) -> Response:
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    if job.lookup.running:
        return JSONResponse(job.lookup.state())
    body = await request.json()
    try:
        boards = max(1, min(100000, int(body.get("boards", 1))))
    except (TypeError, ValueError):
        boards = 1
    job.lookup.task = asyncio.create_task(run_lookup(job, boards, bool(body.get("refresh"))))
    await asyncio.sleep(0)  # let it start, so the state says running
    return JSONResponse(job.lookup.state())


@app.get("/bom/{key}/lookup")
async def _lookup_state(key: str) -> Response:
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    return JSONResponse(job.lookup.state())


def page(key: str, job: Job) -> str:
    from .review_panel import project_key
    data = json.dumps(job.data, ensure_ascii=False).replace("<", "\\u003c")
    name = re.sub(r"[^\w.-]+", "_", Path(job.board).stem) or "board"
    return (_PAGE.replace("%%TITLE%%", html.escape(job.title))
            .replace("%%KEY%%", key)
            .replace("%%NOTESKEY%%", project_key(Path(job.board).parent))
            # Stable across GUI sessions (the keys above aren't): what this page remembers is per board.
            .replace("%%BOARDID%%", hashlib.sha1(str(Path(job.board).resolve()).encode()).hexdigest()[:16])
            .replace("%%NAME%%", json.dumps(name))
            .replace("%%EDITABLE%%", "true" if job.rev == "LOCAL" else "false")
            .replace("%%DRAFTS_FILE%%", html.escape(str(drafts_path(job.board))))
            .replace("%%DATA%%", data))


_PAGE = open(Path(__file__).with_name("bom_page.html"), encoding="utf-8").read()
