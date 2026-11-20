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
Trackers ("Carted", "Placed"...) are your own tick columns for a build:
never written into the schematic, ticked per part reference (so they
survive a line's part number changing or lines regrouping).
Only made when asked (the header's BOM button); nothing runs in the
background.

Look up asks Mouser and Digi-Key (kigit bom --lookup: each site with a
key) for stock, prices and lifecycle, only when pressed; the answer is
kept with the job for the page. Keys go to kigit on stdin (kigit bom
--set-key); the page only learns whether one is set (kigit bom --keys).
"""

from __future__ import annotations

import asyncio
import html
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
    return {"drafts": drafts, "columns": columns, "tracking": _tracking(data)}


def save_drafts(board: str | Path, state: dict) -> None:
    drafts = {k: dict(sorted(d.items())) for k, d in sorted(state["drafts"].items()) if d}
    columns = list(dict.fromkeys(state.get("columns", [])))
    tracking = _tracking({"tracking": state.get("tracking") or {}})
    path = drafts_path(board)
    if not drafts and not columns and not tracking["columns"]:
        path.unlink(missing_ok=True)
        return
    out = {"version": 2, "drafts": drafts, "columns": columns}
    if tracking["columns"]:
        out["tracking"] = tracking
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


def rename_tracker(board: str | Path, old: str, new: str) -> dict:
    state = load_drafts(board)
    t = state["tracking"]
    t["columns"] = [new if c == old else c for c in t["columns"]]
    if old in t["done"]:
        t["done"][new] = t["done"].pop(old)
    save_drafts(board, state)
    return load_drafts(board)


def add_tracker(board: str | Path, name: str) -> dict:
    state = load_drafts(board)
    if name not in state["tracking"]["columns"]:
        state["tracking"]["columns"].append(name)
    save_drafts(board, state)
    return load_drafts(board)


def remove_tracker(board: str | Path, name: str) -> dict:
    state = load_drafts(board)
    t = state["tracking"]
    t["columns"] = [c for c in t["columns"] if c != name]
    t["done"].pop(name, None)
    save_drafts(board, state)
    return load_drafts(board)


def set_tracked(board: str | Path, name: str, refs: list[str], done: bool) -> dict:
    """Ticks (or unticks) parts in a tracker. Re-reads the file first."""
    state = load_drafts(board)
    t = state["tracking"]
    if name not in t["columns"]:
        t["columns"].append(name)
    have = set(t["done"].get(name, []))
    have = have | set(refs) if done else have - set(refs)
    t["done"][name] = sorted(have)
    save_drafts(board, state)
    return load_drafts(board)


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
async def _drafts(key: str) -> Response:
    job = _job(key)
    if job is None:
        return JSONResponse({}, status_code=404)
    return JSONResponse(load_drafts(job.board))


@app.post("/bom/{key}/drafts")
async def _set_draft(key: str, request: Request) -> Response:
    job = _job(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    body = await request.json()
    try:
        if body.get("column"):
            return JSONResponse(add_column(job.board, str(body["column"]).strip()[:100]))
        if body.get("rename_column") or body.get("rename_tracker"):  # {rename_column | rename_tracker, to}
            new = str(body.get("to", "")).strip()[:100]
            if not new or any(ch in new for ch in "\r\n"):
                return JSONResponse({"error": "a column needs a name (one line)"}, status_code=400)
            if body.get("rename_tracker"):
                return JSONResponse(rename_tracker(job.board, str(body["rename_tracker"]), new[:60]))
            return JSONResponse(rename_column(job.board, str(body["rename_column"]), new))
        if body.get("tracker"):  # {tracker, remove?}: add or remove a tracker column
            name = str(body["tracker"]).strip()[:60]
            return JSONResponse(remove_tracker(job.board, name) if body.get("remove") else add_tracker(job.board, name))
        if body.get("track"):  # {track, refs, done}: tick parts
            refs = [str(r) for r in body.get("refs", []) if isinstance(r, str)][:5000]
            return JSONResponse(set_tracked(job.board, str(body["track"]).strip()[:60], refs, bool(body.get("done"))))
        line, name = str(body.get("key", "")), str(body.get("field", ""))
        if not line or not name:
            return JSONResponse({"error": "no line or field"}, status_code=400)
        value = body.get("value")
        return JSONResponse(set_draft(job.board, line, name, None if value is None else str(value)))
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
    state = load_drafts(job.board)
    for k, name in cells:
        state["drafts"].get(k, {}).pop(name, None)
    save_drafts(job.board, state)
    for old, new in renames:
        rename_column(job.board, old, new)
    await _refresh(job)
    logs.log.info("bom: wrote %s fields into %s", result.get("fields"), ", ".join(result.get("written", [])))
    return JSONResponse({"result": result, "data": job.data, "drafts": load_drafts(job.board)})


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
            .replace("%%NAME%%", json.dumps(name))
            .replace("%%EDITABLE%%", "true" if job.rev == "LOCAL" else "false")
            .replace("%%DRAFTS_FILE%%", html.escape(str(drafts_path(job.board))))
            .replace("%%DATA%%", data))


_PAGE = open(Path(__file__).with_name("bom_page.html"), encoding="utf-8").read()
