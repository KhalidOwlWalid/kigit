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
"drafts": {line key: {field name: value}}, "columns": [added fields]}.
Only made when asked (the header's BOM button); nothing runs in the
background.
"""

from __future__ import annotations

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


def load_drafts(board: str | Path) -> dict:
    """{"drafts": {line key: {field: value}}, "columns": [field, ...]}. A
    version 1 file (picks: mpn, manufacturer, note) is read as drafts."""
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
    return {"drafts": drafts, "columns": columns}


def save_drafts(board: str | Path, state: dict) -> None:
    drafts = {k: dict(sorted(d.items())) for k, d in sorted(state["drafts"].items()) if d}
    columns = list(dict.fromkeys(state.get("columns", [])))
    path = drafts_path(board)
    if not drafts and not columns:
        path.unlink(missing_ok=True)
        return
    text = json.dumps({"version": 2, "drafts": drafts, "columns": columns}, indent=2, ensure_ascii=False) + "\n"
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
    edits, cells = [], []
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


def page(key: str, job: Job) -> str:
    data = json.dumps(job.data, ensure_ascii=False).replace("<", "\\u003c")
    name = re.sub(r"[^\w.-]+", "_", Path(job.board).stem) or "board"
    return (_PAGE.replace("%%TITLE%%", html.escape(job.title))
            .replace("%%KEY%%", key)
            .replace("%%NAME%%", json.dumps(name))
            .replace("%%EDITABLE%%", "true" if job.rev == "LOCAL" else "false")
            .replace("%%DRAFTS_FILE%%", html.escape(str(drafts_path(job.board))))
            .replace("%%DATA%%", data))


_PAGE = open(Path(__file__).with_name("bom_page.html"), encoding="utf-8").read()
