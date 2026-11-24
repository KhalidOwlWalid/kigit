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
    what: str = ""                  # the line being looked up ("R1 R3 R5")
    started: float = 0.0            # time.time() when it started
    stopped: bool = False           # stopped by you
    proc: object = None             # kigit's process, while it runs

    def state(self) -> dict:
        return {"running": self.running, "done": self.done, "total": self.total, "boards": self.boards,
                "sites": self.sites, "result": self.result, "error": self.error, "what": self.what,
                "elapsed": round(time.time() - self.started, 1) if self.started else 0, "stopped": self.stopped}


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
            try:  # on backorder at the site (Digi-Key says so): ordered, but not coming soon
                row["backorder"] = min(row["qty"], max(0, int(r.get("backorder", 0))))
            except (TypeError, ValueError):
                row["backorder"] = 0
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
                entry["suggest"] = suggest_line(row, lines, drafts, fn)
                out["unmatched"].append(entry)
                continue
            m = out["lines"].setdefault(line_key(line), {"qty": {}, "rows": []})
            m["qty"][site] = m["qty"].get(site, 0) + row["qty"]
            m["rows"].append(entry)
    return out


SITE_NAMES = {"mouser": "Mouser", "lcsc": "LCSC", "digikey": "Digi-Key"}

# A cart row's description says what kind of part it is ("Thick Film Resistor", "MLCC").
_KIND_WORDS = {"resistor": ("resistor",), "capacitor": ("capacitor", "mlcc"), "inductor": ("inductor",),
               "ferrite": ("ferrite",), "led": ("led",), "diode": ("diode", "rectifier"), "crystal": ("crystal", "xtal")}


# What a passive's value is measured in, as a description writes it.
_UNITS = {"resistor": r"(?:Ω|ohms?|R\b)", "ferrite": r"(?:Ω|ohms?)", "capacitor": r"F\b", "inductor": r"H\b",
          "crystal": r"Hz\b"}
_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6,
           "G": 1e9, "r": 1.0, "R": 1.0}


def si_value(text: str, kind: str = "") -> float | None:
    """A passive's value as a number: 10k, 4k7, 100nF, 0.1uF, 32k768, 8MHz,
    10kR, 4R7. An "M" is mega (1M resistor); "m" is milli except for
    resistors and ferrites, where it's mega too (1m resistor)."""
    t = re.sub(r"\s+", "", str(text or "")).replace("Ω", "").replace("ohms", "").replace("ohm", "")
    t = re.sub(r"(?<=[\dpnuµμmkKMGRr])(F|H|Hz)$", "", t)
    t = re.sub(r"(?<=[pnuµμmkKMG])[Rr]$", "", t)                  # 10kR: the R is "ohms"
    t = re.sub(r"^(\d+[pnuµμmkKMG]\d+)[Rr]$", r"\1", t)              # 5k1R, 2M2R: so is this one
    m = re.fullmatch(r"(\d+)([pnuµμmkKMGRr])(\d+)", t)            # 4k7, 32k768, 4R7
    if m:
        t = f"{m.group(1)}.{m.group(3)}{m.group(2)}"
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)([pnuµμmkKMGRr]?)", t)
    if not m:
        return None
    prefix = m.group(2)
    if prefix == "m" and kind in ("resistor", "ferrite"):
        prefix = "M"
    return float(m.group(1).replace(",", ".")) * _PREFIX[prefix]


def _values_in(text: str, kind: str) -> list[float]:
    """The values a description gives in this kind's unit: "47 pF", "0.1uF", "10kΩ", "32.768kHz"."""
    unit = _UNITS.get(kind)
    if not unit:
        return []
    out = []
    for m in re.finditer(rf"(\d+(?:[.,]\d+)?)\s*([pnuµμmkKMG]?)\s*{unit}", text):
        v = si_value(m.group(1) + m.group(2), kind)
        if v is not None:
            out.append(v)
    return out


def suggest_line(row: dict, lines: list[dict], drafts: dict, field_names: dict) -> dict | None:
    """A line a cart row is most likely for, from its description and part
    number: a passive by kind + value (+ package), anything else by its
    value (part name) in the row's MPN or description. Only a clear best is
    suggested; it's never matched until you accept it. {key, refs, why}."""
    from .inventory import norm_value
    desc = f"{row.get('description', '')} {row.get('mpn', '')}"
    low = desc.lower()
    tokens = {norm_value(t) for t in re.split(r"[\s,;/()]+", desc) if t}
    scored = []
    for l in lines:
        if l.get("dnp"):
            continue
        kind, value, package = l.get("kind", ""), l.get("value", ""), (l.get("package") or "").lower()
        score, why = 0, []
        if kind in _KIND_WORDS:
            if not any(w in low for w in _KIND_WORDS[kind]):
                continue
            v = si_value(value, kind)
            same = v is not None and any(abs(x - v) <= 1e-6 * max(abs(v), 1e-15) for x in _values_in(desc, kind))
            if not same and norm_value(value) not in tokens:  # a value as a word: "RED" for an LED
                continue
            score, why = 2, [f"{kind} {value}"]
            if package and package in low:
                score, why = 3, why + [package]
        elif len(value) >= 4 and _norm(value) and (_norm(value) in _norm(row.get("mpn", "")) or value.lower() in low):
            score, why = 2, [f"{value} in its part number or description"]
        if score:
            scored.append((score, l, why))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None  # two lines fit as well: no guess
    _, l, why = scored[0]
    return {"key": line_key(l), "refs": l["refs"], "label": f"{l['value']} · {', '.join(l['refs'][:6])}"
            + (" …" if len(l["refs"]) > 6 else ""), "why": " + ".join(why)}


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
        _done(f"board #{n} of build {build} is done", "every part placed")
    elif not done and b["status"] == "done":
        b["status"], b["finished"] = "in progress", ""
    logs.log.info("bom: build %s board #%d: %s %d part(s), %d from the inventory", build, n,
                  "placed" if placed else "took off", len(refs), len(deltas))
    return builds.save_board(board, build, b)


# ------------------------------------------------------- log and the bell
def _err(message: str, status: int, what: str = "", go: str = "", **extra) -> JSONResponse:
    """An error answer for the page, also in the session log and, unless it's
    just a page left open after kigit restarted (404), in the notification
    bell (the GUI's and the BOM page's), so it isn't only a passing alert."""
    message = str(message)
    if status == 404:
        logs.log.info("bom: %s", message)
    else:
        logs.log.warning("bom: %s%s", f"{what}: " if what else "", message)
        from . import notices
        notices.add("error" if status >= 500 else "warning", f"BOM: {message}", what, go=go)
    return JSONResponse({"error": message, **extra}, status_code=status)


def _done(title: str, detail: str = "") -> None:
    """Something worth knowing happened (a cart imported, a board done): the log and the bell's list."""
    from . import notices
    logs.log.info("bom: %s%s", title, f" ({detail})" if detail else "")
    notices.add("info", f"BOM: {title}", detail)


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
        return _err("no board data", 404)
    return FileResponse(CACHE / job.board_json, media_type="application/json")


@app.get("/bom/{key}/status")
async def _status(key: str) -> Response:
    job = _job(key)
    if job is None:
        return _err("gone", 404)
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
        return _err("gone", 404)
    body = await request.json()
    build = str(body.get("build") or "")
    try:
        if body.get("column"):
            add_column(job.board, str(body["column"]).strip()[:100])
        elif body.get("rename_column") or body.get("rename_tracker"):  # {rename_column | rename_tracker, to}
            new = str(body.get("to", "")).strip()[:100]
            if not new or any(ch in new for ch in "\r\n"):
                return _err("a column needs a name (one line)", 400)
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
                return _err("no line or field", 400)
            value = body.get("value")
            set_draft(job.board, line, name, None if value is None else str(value))
        return JSONResponse(state(job.board, build))
    except (NoBuild, BuildError) as e:
        return _err(str(e), 400)
    except OSError as e:
        return _err(str(e), 500)


async def _refresh(job: Job) -> None:
    job.data = await kigit.bom(job.board, job.rev)


@app.post("/bom/{key}/write")
async def _write(key: str, request: Request) -> Response:
    """Writes the given cells ({key, field, value}) into the schematic, by
    kigit bom --write, and drops their drafts."""
    from .app import CACHE

    job = _job(key)
    if job is None:
        return _err("gone", 404)
    if job.rev != "LOCAL":
        return _err("only the working tree can be written", 400)
    body = await request.json()
    refs = {line_key(l): l["refs"] for l in job.data.get("lines", [])}
    every_ref = [r for l in job.data.get("lines", []) for r in l["refs"]]
    edits, cells, renames = [], [], []
    for rn in body.get("renames", []):  # a field column's new title: the field renamed on every part that has it
        old, new = str(rn.get("from", "")), str(rn.get("to", "")).strip()
        if not old or not new:
            return _err("a rename needs both names", 400)
        edits.append({"refs": every_ref, "field": old, "rename": new})
        renames.append((old, new))
    for c in body.get("cells", []):
        k, name, value = str(c.get("key", "")), str(c.get("field", "")), str(c.get("value", ""))
        if k not in refs or not name:
            return _err(f"no such line: {k}", 400)
        edits.append({"refs": refs[k], "field": name, "value": value})
        cells.append((k, name))
    if not edits:
        return _err("nothing to write", 400)
    try:
        result = await kigit.bom_write(job.board, edits, CACHE / f"bom-edits-{key}.json", bool(body.get("force")))
    except kigit.KigitError as e:
        return _err(str(e), 409, "writing part numbers into the schematic", locked="KiCad has" in str(e))
    job.backup = result.get("backup") or job.backup
    left = load_drafts(job.board)
    for k, name in cells:
        left["drafts"].get(k, {}).pop(name, None)
    save_drafts(job.board, left)
    for old, new in renames:
        rename_column(job.board, old, new)
    await _refresh(job)
    _done(f"wrote {result.get('fields')} field(s) into the schematic", ", ".join(result.get("written", [])) +
          (f"; backup in {result['backup']}" if result.get("backup") else ""))
    try:
        answer = state(job.board, str(body.get("build") or ""))
    except ValueError:
        answer = state(job.board, "")
    return JSONResponse({"result": result, "data": job.data, "drafts": answer})


@app.post("/bom/{key}/undo")
async def _undo(key: str) -> Response:
    job = _job(key)
    if job is None or not job.backup:
        return _err("nothing to undo", 400)
    try:
        result = await kigit.bom_restore(job.backup)
    except kigit.KigitError as e:
        return _err(str(e), 500)
    job.backup = ""
    await _refresh(job)
    _done("put the schematic back as it was before the last write", ", ".join(result.get("restored", [])))
    return JSONResponse({"result": result, "data": job.data})


@app.get("/bom/{key}/notes")
async def _notes(key: str) -> Response:
    """How many notes pin each part ({ref: n}), for the + Notes buttons."""
    from . import notebook
    job = _job(key)
    if job is None:
        return _err("gone", 404)
    return JSONResponse(await asyncio.to_thread(notebook.counts_by_part, Path(job.board).parent))


def _cart_answer(job: Job, st: dict) -> JSONResponse:
    return JSONResponse({"match": match_carts(job.data, st), "drafts": st})


@app.get("/bom/{key}/cart")
async def _cart(key: str, build: str = "") -> Response:
    """The build's carts matched to the lines (none without a build)."""
    from .builds import BuildError
    job = _job(key)
    if job is None:
        return _err("gone", 404)
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
        return _err("gone", 404)
    data = await request.body()
    if len(data) > MAX_BYTES:
        return _err("the file is too big for a cart (over 5 MB)", 400, go="bom:carts")
    try:
        if not build:
            raise NoBuild("pick or make a build first: a cart belongs to a build")
        st = await asyncio.to_thread(import_cart, job.board, build, site, name, data)
    except (CartError, NoBuild, BuildError) as e:
        return _err(str(e), 400, go="bom:carts")
    except OSError as e:
        return _err(str(e), 500, go="bom:carts")
    answer = _cart_answer(job, st)
    m = match_carts(job.data, st)
    left = sum(1 for u in m["unmatched"] if u["site"] == site)
    rows = len(st["carts"].get(site, {}).get("rows", []))
    _done(f"{SITE_NAMES.get(site, site)} cart imported into build {build}",
          f"{name}: {rows} rows" + (f", {left} not matched to a line (Import cart, Carts)" if left else ", all matched"))
    if left:
        from . import notices
        notices.add("warning", f"BOM: {left} {SITE_NAMES.get(site, site)} cart row(s) match no line",
                    "They don't count as ordered until each has its line: Match them",
                    ("Site's number", "MPN", "Qty"), [(u["sku"], u["mpn"], str(u["qty"])) for u in m["unmatched"] if u["site"] == site],
                    go="bom:carts")
    return answer


@app.post("/bom/{key}/cart/{site}/edit")
async def _edit_cart(key: str, site: str, request: Request) -> Response:
    """{build, remove: true} | {build, receive: true} | {build, unreceive: true} |
    {build, row, refs (null: unassign), keep}."""
    from .builds import BuildError
    from .inventory import InventoryError
    job = _job(key)
    if job is None:
        return _err("gone", 404)
    body = await request.json()
    build = str(body.get("build") or "")
    try:
        if not build:
            raise NoBuild("pick a build first: carts belong to a build")
        if body.get("remove"):
            st = remove_cart(job.board, build, site)
        elif body.get("receive") or body.get("unreceive"):
            undo = bool(body.get("unreceive"))
            st = await asyncio.to_thread(receive_cart, job.board, build, job.data, site, undo)
            _done(f"{SITE_NAMES.get(site, site)} cart of build {build} " +
                  ("taken back out of your inventory" if undo else "received into your inventory"))
        else:
            refs = body.get("refs")
            refs = [str(r) for r in refs if isinstance(r, str)] if isinstance(refs, list) else None
            st = assign_row(job.board, build, job.data, site, int(body.get("row", -1)), refs, bool(body.get("keep")))
    except (ValueError, TypeError, InventoryError, BuildError) as e:
        return _err(str(e), 400, go="bom:carts")
    return _cart_answer(job, st)


@app.get("/bom/{key}/builds")
async def _builds(key: str) -> Response:
    from . import builds
    job = _job(key)
    if job is None:
        return _err("gone", 404)
    return JSONResponse({"builds": [b.to_dict() for b in builds.all_builds(job.board)]})


@app.post("/bom/{key}/builds")
async def _edit_builds(key: str, request: Request) -> Response:
    """{action: new, name, boards} | {action: update, id, name?, boards?} | {action: delete, id}.
    Answers {build (the one made or changed, or null), builds}."""
    from . import builds
    job = _job(key)
    if job is None:
        return _err("gone", 404)
    body = await request.json()
    action = body.get("action")
    try:
        if action == "new":
            b = builds.new(job.board, str(body.get("name", "")), body.get("boards", 1), job.rev)
            _done(f"new build {b.name}", f"{b.boards} boards, kigit-builds/{b.id}")
        elif action == "update":
            b = builds.update(job.board, str(body.get("id", "")), body.get("name"), body.get("boards"))
        elif action == "delete":
            builds.delete(job.board, str(body.get("id", "")))
            _done(f"deleted build {body.get('id')}")
            b = None
        else:
            return _err(f"unknown action {action}", 400, go="bom:build")
    except builds.BuildError as e:
        return _err(str(e), 400, go="bom:build")
    except OSError as e:
        return _err(str(e), 500, go="bom:build")
    return JSONResponse({"build": b.to_dict() if b else None,
                         "builds": [x.to_dict() for x in builds.all_builds(job.board)]})


# ------------------------------------------------------- column layouts
# Which columns each view shows, kept for every project and session in
# <app data>/kigit/bom-columns.json: {"buy": {"hidden": [ids]},
# "assemble": {"shown": [ids]}}. Buy shows everything but what you hide;
# Assemble only what you show (new columns stay out of the way there).
# Ids are the page's column ids; "kind:mpn" is the MPN column, whatever the
# project calls it. A view not in the file has the page's defaults.
COLUMN_VIEWS = {"buy": "hidden", "assemble": "shown"}


def columns_file() -> Path:
    return logs.default_dir().parent / "bom-columns.json"


def load_columns() -> dict:
    """The saved layouts, cleaned; {} if none (or the file can't be read: said in the log)."""
    path = columns_file()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logs.log.warning("bom: can't read %s (%s); columns are at their defaults", path, e)
        return {}
    out = {}
    for view, kind in COLUMN_VIEWS.items():
        ids = (raw.get(view) or {}).get(kind) if isinstance(raw, dict) and isinstance(raw.get(view), dict) else None
        if isinstance(ids, list):
            out[view] = {kind: [str(i) for i in ids if isinstance(i, str)][:500]}
    return out


def save_columns(cfg: dict) -> None:
    path = columns_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@app.post("/bom/{key}/columns")
async def _set_columns(key: str, request: Request) -> Response:
    """{view, shown | hidden: [ids]} saves that view's layout; {view, reset:
    true} drops it (back to the defaults). Answers every saved layout."""
    body = await request.json()
    view = body.get("view")
    if view not in COLUMN_VIEWS:
        return _err(f"no such view: {view}", 400, go="bom:columns")
    cfg = load_columns()
    if body.get("reset"):
        cfg.pop(view, None)
        what = "back to the defaults"
    else:
        ids = body.get(COLUMN_VIEWS[view])
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            return _err(f"{view} columns need a list of column ids", 400, go="bom:columns")
        cfg[view] = {COLUMN_VIEWS[view]: ids[:500]}
        what = f"{len(ids)} {COLUMN_VIEWS[view]}"
    try:
        save_columns(cfg)
    except OSError as e:
        return _err(f"couldn't save the column layout: {e}", 500, go="bom:columns")
    logs.log.info("bom: %s columns: %s (%s)", view, what, columns_file())
    return JSONResponse(cfg)


@app.get("/bom/{key}/stock")
async def _stock(key: str) -> Response:
    job = _job(key)
    if job is None:
        return _err("gone", 404)
    return await asyncio.to_thread(_stock_answer, job)


@app.post("/bom/{key}/inventory")
async def _edit_inventory(key: str, request: Request) -> Response:
    """{action: choose | new, path} | {action: forget} | {action: set | adjust,
    key (a BOM line) or ids (a row), qty | delta}."""
    from . import inventory
    job = _job(key)
    if job is None:
        return _err("gone", 404)
    body = await request.json()
    action = body.get("action")

    def run() -> None:
        if action in ("choose", "new"):
            path = Path(str(body.get("path", ""))).expanduser()
            if not path.is_absolute():
                raise inventory.InventoryError("give the file's full path")
            inv = inventory.create(path) if action == "new" else inventory.read(path)
            inventory.remember(path, inv)
            _done(f"inventory {'made' if action == 'new' else 'chosen'}: {path.name}",
                  f"{path} ({len(inv.rows)} parts" + (f", {len(inv.problems)} rows kigit can't use" if inv.problems else "") + ")")
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
        return _err(str(e), 400, go="bom:inventory")
    except (TypeError, ValueError) as e:
        return _err(f"not a number: {e}", 400, go="bom:inventory")
    return await asyncio.to_thread(_stock_answer, job)


@app.get("/bom/{key}/browse")
async def _browse(key: str, dir: str = "") -> Response:
    """Folders and .csv files in a folder, for choosing the inventory file
    (a web page can't ask for a path). Only names, nothing read."""
    from . import inventory
    if _job(key) is None:
        return _err("gone", 404)
    where = inventory.location()
    d = Path(dir).expanduser() if dir else (where.parent if where else Path.home())
    try:
        d = d.resolve()
        entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
    except OSError as e:
        return _err(f"can't open {d}: {e}", 400, go="bom:inventory")
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
        return _err("gone", 404)
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
        return _err("gone", 404)
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
        return _err(str(e), 400, go="bom:assemble")
    except (TypeError, ValueError) as e:
        return _err(f"not a board number: {e}", 400, go="bom:assemble")
    return JSONResponse({"board": b, "boards": builds.boards(job.board, build)})


@app.post("/bom/{key}/clientlog")
async def _clientlog(key: str, request: Request) -> Response:
    """Something went wrong in the BOM page itself (a script error): into the
    session log, so it can be traced afterwards."""
    try:
        body = await request.json()
    except ValueError:
        body = {}
    logs.log.warning("bom page (browser): %s", str(body.get("message", ""))[:2000])
    return JSONResponse({})


# How to get a keyring, by Linux distribution (/etc/os-release ID and ID_LIKE).
_SECRET_TOOL_INSTALL = (
    (("ubuntu", "debian", "linuxmint", "pop", "elementary", "raspbian"), "sudo apt install libsecret-tools"),
    (("fedora", "rhel", "centos", "rocky", "almalinux"), "sudo dnf install libsecret"),
    (("arch", "manjaro", "endeavouros"), "sudo pacman -S libsecret"),
    (("opensuse", "suse", "opensuse-leap", "opensuse-tumbleweed"), "sudo zypper install libsecret-tools"),
)


def _os_release(path: str = "/etc/os-release") -> list[str]:
    """This Linux's ID and the ones it's like ("ubuntu", "debian")."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    ids: list[str] = []
    for line in text.splitlines():
        k, _, v = line.partition("=")
        if k in ("ID", "ID_LIKE"):
            ids += v.strip().strip('"').lower().split()
    return ids


def keyring_fix(store: dict, distro: list[str] | None = None, system: str | None = None) -> dict:
    """What to do when keys can't go in a keyring: {"steps": [text], "command":
    a command to copy (or "")}. Empty when there's a keyring."""
    import sys
    system = system or sys.platform
    if store.get("keyring"):
        return {}
    why = store.get("why", "")
    if "KIGIT_KEYRING=off" in why:
        if system == "win32":
            return {"steps": ["kigit was told not to use Credential Manager (the KIGIT_KEYRING setting). "
                              "Remove it in PowerShell, then restart kigit (if it's also in Windows' environment "
                              "variables, remove it there too):"],
                    "command": '[Environment]::SetEnvironmentVariable("KIGIT_KEYRING", $null, "User")'}
        return {"steps": ["kigit was told not to use the keyring. Remove that setting from where you start kigit "
                          "(your shell's profile), then restart kigit:"], "command": "unset KIGIT_KEYRING"}
    if "secret-tool" in why:
        ids = _os_release() if distro is None else distro
        command = next((c for names, c in _SECRET_TOOL_INSTALL if any(i in names for i in ids)), "")
        return {"steps": ["Install secret-tool, the program kigit uses to reach your keyring" +
                          (":" if command else " (your distribution's libsecret tools package)."),
                          ], "command": command}
    if "answered" in why:
        return {"steps": ["No keyring is running in this session. That's usual over SSH or without a desktop: "
                          "log in to your desktop and start kigit there, or keep the file (only you can read it)."],
                "command": ""}
    return {"steps": [why], "command": ""}


async def _keys_answer() -> dict:
    answer = await kigit.bom_keys()
    if isinstance(answer.get("store"), dict):
        answer["store"]["fix"] = keyring_fix(answer["store"])
    return answer


@app.get("/bom/{key}/lcsc")
async def _lcsc(key: str) -> Response:
    """Where the LCSC data (jlcparts) is kept, how old, how big: for the "?" popup."""
    if _job(key) is None:
        return _err("gone", 404)
    try:
        return JSONResponse(await kigit.bom_lcsc_info())
    except kigit.KigitError as e:
        return _err(str(e), 500, go="bom:lcsc")


@app.post("/bom/{key}/lcsc")
async def _lcsc_action(key: str, request: Request) -> Response:
    """{action: refresh} downloads the LCSC data now; {action: open} opens its folder."""
    if _job(key) is None:
        return _err("gone", 404)
    action = str((await request.json()).get("action", ""))
    try:
        if action == "refresh":
            info = await kigit.bom_lcsc_info(refresh=True)
            _done("LCSC data downloaded", info.get("dir", ""))
            return JSONResponse(info)
        if action == "open":
            info = await kigit.bom_lcsc_info()
            folder = Path(info["dir"])
            folder.mkdir(parents=True, exist_ok=True)
            _open_folder(folder)
            return JSONResponse(info)
    except kigit.KigitError as e:
        return _err(f"couldn't download the LCSC data: {e}" if action == "refresh" else str(e), 502, go="bom:lcsc")
    except OSError as e:
        return _err(f"couldn't open the folder: {e}", 500, go="bom:lcsc")
    return _err(f"unknown action {action}", 400)


def _open_folder(folder: Path) -> None:
    """Shows a folder in the system's file manager."""
    import subprocess
    import sys
    if sys.platform.startswith("win"):
        os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)],  # noqa: S603
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@app.get("/bom/{key}/keys")
async def _keys(key: str) -> Response:
    if _job(key) is None:
        return _err("gone", 404)
    try:
        return JSONResponse(await _keys_answer())
    except kigit.KigitError as e:
        return _err(str(e), 500, go="bom:keys")


@app.post("/bom/{key}/keys")
async def _set_key(key: str, request: Request) -> Response:
    """Saves (or with "" removes) a site's API key, through kigit."""
    if _job(key) is None:
        return _err("gone", 404)
    body = await request.json()
    site = str(body.get("site", ""))
    if site == "mouser":
        lines = [str(body.get("key", ""))]
    elif site == "digikey":
        cid = str(body.get("client_id", ""))
        lines = [cid] if not cid.strip() else [cid, str(body.get("client_secret", "")),
                                               f"{body.get('locale_site', 'US')} {body.get('currency', 'USD')}"]
    else:
        return _err(f"kigit has no lookups for {site}", 400, go="bom:keys")
    if any(len(x) > 300 or "\n" in x or "\r" in x for x in lines):
        return _err("not a key kigit can keep", 400, go="bom:keys")
    try:
        await kigit.bom_set_key(site, *lines)
        logs.log.info("bom: %s key %s", site, "saved" if lines[0].strip() else "removed")  # never the key
        answer = await _keys_answer()
        if lines[0].strip() and answer.get(site, {}).get("where") == "file":
            # Needs your attention: saved, but not encrypted.
            from . import notices
            why = answer.get("store", {}).get("why", "")
            logs.log.warning("bom: %s key saved in a plain file (no keyring: %s)", site, why)
            notices.add("warning", f"BOM: {answer[site].get('name', site)} key saved without encryption",
                        "It's in a file only you can read. Show (Keys) has the steps to keep it in your "
                        "keyring instead; kigit then moves it there by itself.", go="bom:keys")
        return JSONResponse(answer)
    except kigit.KigitError as e:
        return _err(str(e), 500, go="bom:keys")


# Sites Look up can ask (kigit bom --site).
LOOKUP_SITES = ("mouser", "digikey", "lcsc")


async def run_lookup(job: Job, boards: int, refresh: bool, sites: list[str] | None = None) -> None:
    """Look up at the ticked sites (None: every site with a key)."""
    look = job.lookup
    look.running, look.done, look.total, look.error, look.boards = True, 0, len(job.data.get("lines", [])), "", boards
    look.what, look.started, look.stopped, look.proc = "", time.time(), False, None
    try:
        names = [k.get("name", s) for s, k in (await kigit.bom_keys()).items()
                 if k.get("set") and (sites is None or s in sites)]
    except kigit.KigitError:
        names = []
    look.sites = " and ".join(names) or "the parts sites"

    def progress(done: int, total: int, what: str = "") -> None:
        look.done, look.total, look.what = done, total, what

    def started_proc(proc) -> None:
        look.proc = proc

    try:
        look.result = await kigit.bom_lookup(job.board, job.rev, boards, refresh, progress, started_proc, sites)
        look.done = look.total
        from . import notices
        for site, info in look.result.get("sites", {}).items():
            if info.get("error"):
                logs.log.warning("bom lookup: %s: %s", site, info["error"])
                notices.add("warning", f"BOM: Look up at {info.get('name', site)} stopped", info["error"], go="bom:lookup")
        notice = look.result.get("sites", {}).get("lcsc", {}).get("notice")
        if notice:  # worked from an old download (offline)
            logs.log.warning("bom lookup: %s", notice)
            notices.add("warning", "BOM: LCSC data is old", notice, go="bom:lcsc")
        names = [i.get("name", s) for s, i in look.result.get("sites", {}).items() if not i.get("error")]
        if names:
            _done(f"Look up done at {' and '.join(names)}", f"{look.total} lines, {boards} board(s)")
    except kigit.KigitError as e:
        if look.stopped:  # you stopped it: not a failure
            look.error = ""
            _done("Look up stopped", f"after {look.done} of {look.total} lines")
            return
        look.error = str(e)
        logs.log.warning("bom lookup failed: %s", e)
        from . import notices
        notices.add("warning", "BOM: Look up failed", str(e), go="bom:lookup")
    except (OSError, ValueError) as e:
        look.error = f"Couldn't look up: {e}"
        logs.log.warning("bom lookup failed: %s", e)
        from . import notices
        notices.add("warning", "BOM: Look up failed", str(e), go="bom:lookup")
    finally:
        look.running, look.proc, look.what = False, None, ""


@app.post("/bom/{key}/lookup")
async def _start_lookup(key: str, request: Request) -> Response:
    job = _job(key)
    if job is None:
        return _err("gone", 404)
    if job.lookup.running:
        return JSONResponse(job.lookup.state())
    body = await request.json()
    try:
        boards = max(1, min(100000, int(body.get("boards", 1))))
    except (TypeError, ValueError):
        boards = 1
    sites = body.get("sites")  # the ticked ones; missing: kigit's default
    if sites is not None:
        if not isinstance(sites, list) or any(s not in LOOKUP_SITES for s in sites):
            return _err(f"Unknown site to look up at: {sites}", 400, go="bom:lookup")
        if not sites:
            return _err("Tick at least one site to look up at.", 400, go="bom:lookup")
    job.lookup.task = asyncio.create_task(run_lookup(job, boards, bool(body.get("refresh")), sites))
    await asyncio.sleep(0)  # let it start, so the state says running
    return JSONResponse(job.lookup.state())


@app.post("/bom/{key}/lookup/stop")
async def _stop_lookup(key: str) -> Response:
    """Stops a running Look up (ends kigit's process; what it found so far isn't kept)."""
    job = _job(key)
    if job is None:
        return _err("gone", 404)
    look = job.lookup
    if look.running and look.proc is not None:
        look.stopped = True
        try:
            look.proc.terminate()
        except OSError as e:
            return _err(f"couldn't stop it: {e}", 500, go="bom:lookup")
    return JSONResponse(look.state())


@app.get("/bom/{key}/lookup")
async def _lookup_state(key: str) -> Response:
    job = _job(key)
    if job is None:
        return _err("gone", 404)
    return JSONResponse(job.lookup.state())


def page(key: str, job: Job) -> str:
    from nicegui import __version__ as nicegui_version

    from .review_panel import project_key
    data = json.dumps(job.data, ensure_ascii=False).replace("<", "\\u003c")
    name = re.sub(r"[^\w.-]+", "_", Path(job.board).stem) or "board"
    return (_PAGE.replace("%%TITLE%%", html.escape(job.title))
            .replace("%%KEY%%", key)
            .replace("%%NOTESKEY%%", project_key(Path(job.board).parent))
            .replace("%%NGV%%", nicegui_version)  # kigit's own fonts, served by NiceGUI
            # Stable across GUI sessions (the keys above aren't): what this page remembers is per board.
            .replace("%%BOARDID%%", hashlib.sha1(str(Path(job.board).resolve()).encode()).hexdigest()[:16])
            .replace("%%NAME%%", json.dumps(name))
            .replace("%%EDITABLE%%", "true" if job.rev == "LOCAL" else "false")
            .replace("%%DRAFTS_FILE%%", html.escape(str(drafts_path(job.board))))
            .replace("%%COLUMNS%%", json.dumps(load_columns()).replace("<", "\\u003c"))
            .replace("%%DATA%%", data))


_PAGE = open(Path(__file__).with_name("bom_page.html"), encoding="utf-8").read()
