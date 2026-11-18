"""The BOM page: the board's bill of materials (kigit bom --json), with
links to search Digi-Key, Mouser and LCSC for each line, the part number
you chose for lines that have none, and a CSV for the distributors' BOM
upload tools.

Beside the list: the board in 2D (kigit's own board data, REV..REV) and
in 3D (the 3D view's model, made after the page opens). Hovering a line
lights its parts up in both; hovering a part lights its line up.

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
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from nicegui import app

PICKS = "kigit-bom.json"
PICK_FIELDS = ("mpn", "manufacturer", "note")


@dataclass
class Job:
    board: str
    title: str
    data: dict
    board_json: str = ""            # the 2D view's data, a file in CACHE ("" if it couldn't be made)
    glb: str = ""                   # the 3D model, a file in CACHE (made after the page opens)
    model_ready: bool = False
    model_error: str = ""
    expected: float | None = None   # seconds the 3D build should take, if known
    started: float = field(default_factory=time.monotonic)


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


@app.get("/bom/{key}/board.json")
async def _board(key: str) -> Response:
    from .app import CACHE

    job = jobs.get(key)
    if job is None or not job.board_json or not (CACHE / job.board_json).is_file():
        return JSONResponse({"error": "no board data"}, status_code=404)
    return FileResponse(CACHE / job.board_json, media_type="application/json")


@app.get("/bom/{key}/status")
async def _status(key: str) -> Response:
    job = jobs.get(key)
    if job is None:
        return JSONResponse({"error": "gone"}, status_code=404)
    return JSONResponse({"ready": job.model_ready, "error": job.model_error, "glb": f"/diffs/{job.glb}",
                         "elapsed": time.monotonic() - job.started, "expected": job.expected})


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


_PAGE = open(Path(__file__).with_name("bom_page.html"), encoding="utf-8").read()
