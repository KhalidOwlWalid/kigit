"""Your inventory: a CSV file of yours, anywhere (a synced folder, its own
git repo), shared by every project. kigit keeps only where it is, and a
copy of what it last read, in <app data>/kigit/inventory.json: deleting
kigit's app folder loses nothing (choose the file again).

The format (column names matched loosely, any order, extra columns kept):

    Quantity                 how many you have (needed)
    MPN, LCSC, Mouser,       what the part is: at least one of these, or
    Digi-Key                 Kind + Value + Package for parts without a
    Kind, Value, Package     number (resistor, 10k, 0603)
    Manufacturer, Description, Location, Notes    for you

A BOM line is found in it by its MPN, else LCSC / Mouser / Digi-Key number
(part numbers compared as letters and digits), else, for resistors,
capacitors, inductors and ferrites, kind + value + package.

kigit only ever changes Quantity and adds rows for parts new to you. Each
change is a delta applied to the file as it is on disk at that moment
(re-read first), written through a temp file, with the previous version
kept as <name>.csv.bak.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import logs

HEADER = ["MPN", "Manufacturer", "LCSC", "Mouser", "Digi-Key", "Kind", "Value", "Package", "Quantity", "Location",
          "Notes"]
NUMBERS = ("mpn", "lcsc", "mouser", "digikey")  # part number columns, in matching order
GENERIC_KINDS = {"resistor", "capacitor", "inductor", "ferrite"}
MAX_BYTES = 10 * 1024 * 1024


class InventoryError(ValueError):
    """The inventory can't be read or written (the message says why)."""


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def role(name: str) -> str:
    """What a column is: qty, mpn, manufacturer, lcsc, mouser, digikey, kind,
    value, package, description, location, notes; "" for your own columns."""
    k = _key(name)
    if k in ("quantity", "qty", "stock", "onhand", "instock", "count", "amount"):
        return "qty"
    if k in ("mpn", "mfrpartnumber", "manufacturerpartnumber", "mfrno", "mfrpn", "partnumber", "manufacturepartnumber"):
        return "mpn"
    if k in ("manufacturer", "mfr", "mfrname", "brand"):
        return "manufacturer"
    if k.startswith("lcsc"):
        return "lcsc"
    if k.startswith("mouser"):
        return "mouser"
    if k.startswith("digikey") or k in ("dk", "dkpn"):
        return "digikey"
    for r in ("kind", "value", "package", "description", "location", "notes"):
        if k == r or (r == "kind" and k in ("type", "category")) or (r == "package" and k in ("footprint", "case")) \
                or (r == "notes" and k == "note"):
            return r
    return ""


def norm_pn(pn: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (pn or "").upper())


def norm_value(v: str) -> str:
    """A passive's value, written one way: 10k, 10K, 10kΩ, 10k ohm -> 10k;
    4k7 -> 4.7k; 100nF -> 100n; 4R7 -> 4.7."""
    v = re.sub(r"\s+", "", (v or "").lower().replace("µ", "u").replace("μ", "u"))
    v = re.sub(r"(ohms?|ω|Ω)$", "", v)
    v = re.sub(r"(?<=[0-9pnumk])[fh]$", "", v)          # 100nf -> 100n, 10uh -> 10u
    m = re.fullmatch(r"(\d+)([rkmgpnu])(\d+)", v)        # 4k7 -> 4.7k, 4r7 -> 4.7
    if m:
        v = f"{m.group(1)}.{m.group(3)}" + ("" if m.group(2) == "r" else m.group(2))
    return re.sub(r"(?<=\d)r$", "", v)                   # 100r -> 100


def keys_of(ids: dict) -> list[str]:
    """A part's identities, most precise first: mpn:..., lcsc:..., mouser:...,
    digikey:..., then kind|value|package for a passive."""
    out = [f"{c}:{norm_pn(ids.get(c, ''))}" for c in NUMBERS if norm_pn(ids.get(c, ""))]
    kind = (ids.get("kind") or "").strip().lower()
    if kind in GENERIC_KINDS and ids.get("value") and ids.get("package"):
        out.append(f"generic:{kind}|{norm_value(ids['value'])}|{(ids['package'] or '').strip().lower()}")
    return out


@dataclass
class Row:
    line: int                  # the row's line in the file (2 = the first after the header)
    qty: int
    ids: dict                  # role -> text
    keys: list[str] = field(default_factory=list)

    def label(self) -> str:
        i = self.ids
        return (i.get("mpn") or i.get("lcsc") or i.get("mouser") or i.get("digikey")
                or " ".join(x for x in (i.get("kind"), i.get("value"), i.get("package")) if x) or f"row {self.line}")


@dataclass
class Inventory:
    path: Path
    header: list[str]
    rows: list[Row]
    problems: list[str]        # rows kigit can't use, and why
    by_key: dict[str, Row] = field(default_factory=dict)

    def find(self, ids: dict) -> tuple[Row | None, str]:
        """The row for a part, and what matched (mpn, lcsc, ..., generic)."""
        for k in keys_of(ids):
            if k in self.by_key:
                return self.by_key[k], k.split(":", 1)[0]
        return None, ""

    def to_json(self) -> dict:
        return {"path": str(self.path), "header": self.header, "problems": self.problems,
                "rows": [{"line": r.line, "qty": r.qty, "ids": r.ids, "label": r.label()} for r in self.rows]}


# ------------------------------------------------------------- the file
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _dialect(text: str):
    try:
        return csv.Sniffer().sniff(text.split("\n", 1)[0], delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _number(s: str) -> int | None:
    s = (s or "").strip().replace(",", "").replace(" ", "")
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return None


def parse(text: str, path: Path) -> Inventory:
    table = [r for r in csv.reader(io.StringIO(text), _dialect(text))]
    if not table or not any(c.strip() for c in table[0]):
        raise InventoryError(f"{path.name} has no header row (kigit's columns: {', '.join(HEADER)})")
    header = [c.strip() for c in table[0]]
    roles = [role(c) for c in header]
    if "qty" not in roles:
        raise InventoryError(f"{path.name} has no Quantity column")
    if not any(r in roles for r in (*NUMBERS, "value")):
        raise InventoryError(f"{path.name} has nothing that says what a part is: an MPN, LCSC, Mouser or Digi-Key "
                             "column, or Kind + Value + Package")
    rows, problems, by_key = [], [], {}
    for n, cells in enumerate(table[1:], start=2):
        if not any(c.strip() for c in cells):
            continue
        ids = {}
        for c, r in zip(cells, roles):
            if r and r != "qty" and c.strip() and r not in ids:
                ids[r] = c.strip()
        qty = _number(cells[roles.index("qty")] if roles.index("qty") < len(cells) else "")
        if qty is None:
            problems.append(f"line {n}: the quantity isn't a number")
            continue
        row = Row(n, qty, ids, keys_of(ids))
        if not row.keys:
            problems.append(f"line {n}: nothing says what the part is (no part number; Kind, Value and Package "
                            "are for resistors, capacitors, inductors and ferrites)")
            continue
        clash = [k for k in row.keys if k in by_key]
        if clash:
            problems.append(f"line {n}: the same part as line {by_key[clash[0]].line} ({clash[0].split(':', 1)[1]}): "
                            "only the first is used")
            continue
        rows.append(row)
        for k in row.keys:
            by_key.setdefault(k, row)
    return Inventory(path, header, rows, problems, by_key)


def read(path: str | Path) -> Inventory:
    path = Path(path).expanduser()
    try:
        data = path.read_bytes()
    except FileNotFoundError as e:
        raise InventoryError(f"{path} isn't there (moved, renamed, or on a drive that isn't plugged in?)") from e
    except OSError as e:
        raise InventoryError(f"can't read {path}: {e}") from e
    if len(data) > MAX_BYTES:
        raise InventoryError(f"{path.name} is too big for an inventory (over 10 MB)")
    return parse(_decode(data), path)


def _write_text(path: Path, text: str) -> None:
    """Through a temp file, keeping the old file as .bak."""
    tmp = path.with_name(path.name + ".kigit-tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="")
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        os.replace(tmp, path)
    except PermissionError as e:
        tmp.unlink(missing_ok=True)
        raise InventoryError(f"can't write {path.name}: is it open in a spreadsheet (Excel locks it)? Close it there "
                             "and try again") from e
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise InventoryError(f"can't write {path.name}: {e}") from e


def create(path: str | Path) -> Inventory:
    """A new, empty inventory file with kigit's columns (refused if the file exists)."""
    path = Path(path).expanduser()
    if path.suffix.lower() != ".csv":
        raise InventoryError("an inventory is a .csv file")
    if path.exists():
        raise InventoryError(f"{path.name} exists already: choose it instead")
    if not path.parent.is_dir():
        raise InventoryError(f"there's no folder {path.parent}")
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerow(HEADER)
    _write_text(path, out.getvalue())
    return read(path)


def change(path: str | Path, deltas: list[tuple[dict, int]] | None = None, sets: list[tuple[dict, int]] | None = None,
           add_fields: dict[str, dict] | None = None) -> Inventory:
    """Changes quantities in the file as it is now: deltas (+n / -n) and sets
    (an exact count), each for a part given by its identities. A part not in
    the file gets a new row (its identity columns filled, and add_fields'
    extra ones for it, e.g. manufacturer). Nothing else in the file changes.
    Quantities don't go below 0."""
    path = Path(path).expanduser()
    inv = read(path)
    text = _decode(path.read_bytes())
    dialect = _dialect(text)
    table = [r for r in csv.reader(io.StringIO(text), dialect)]
    roles = [role(c) for c in inv.header]
    qcol = roles.index("qty")
    crlf = "\r\n" in text
    new_rows: list[list[str]] = []
    new_keys: dict[str, list[str]] = {}

    def apply(ids: dict, n: int, exact: bool) -> None:
        row, _ = inv.find(ids)
        if row is not None:
            cells = table[row.line - 1]
            cells.extend([""] * (len(inv.header) - len(cells)))
            now = _number(cells[qcol]) or 0
            cells[qcol] = str(max(0, n if exact else now + n))
            return
        keys = keys_of(ids)
        if not keys:
            raise InventoryError("that part has nothing to find it by (no part number, and not a passive with a "
                                 "value and package)")
        existing = next((new_keys[k] for k in keys if k in new_keys), None)
        if existing is not None:
            existing[qcol] = str(max(0, n if exact else (_number(existing[qcol]) or 0) + n))
            return
        cells = [""] * len(inv.header)
        extra = (add_fields or {}).get(keys[0], {})
        if (ids.get("kind") or "").strip().lower() not in GENERIC_KINDS:  # kind/value/package only say what a passive is
            ids = {k: v for k, v in ids.items() if k not in ("kind", "value", "package")}
        for i, r in enumerate(roles):
            if r == "qty":
                cells[i] = str(max(0, n))
            elif r and (ids.get(r) or extra.get(r)):
                cells[i] = str(ids.get(r) or extra.get(r))
        new_rows.append(cells)
        for k in keys:
            new_keys[k] = cells

    for ids, n in deltas or []:
        apply(ids, int(n), False)
    for ids, n in sets or []:
        apply(ids, int(n), True)
    out = io.StringIO()
    w = csv.writer(out, dialect=dialect, lineterminator="\r\n" if crlf else "\n")
    for r in table + new_rows:
        w.writerow(r)
    _write_text(path, out.getvalue())
    logs.log.info("inventory: %d change(s), %d new part(s) in %s", len(deltas or []) + len(sets or []), len(new_rows), path)
    return read(path)


# ------------------------------------------------- which file, remembered
def _settings() -> Path:
    return logs.default_dir().parent / "inventory.json"


def location() -> Path | None:
    """The inventory file you chose (None if none yet)."""
    try:
        d = json.loads(_settings().read_text(encoding="utf-8"))
        return Path(d["path"]) if isinstance(d, dict) and d.get("path") else None
    except (OSError, ValueError, KeyError):
        return None


def remember(path: Path | None, inv: Inventory | None = None) -> None:
    """Where the inventory is (None: forget it), and a copy of what was read."""
    p = _settings()
    if path is None:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"path": str(path)}
    if inv is not None:
        try:
            st = path.stat()
            data.update({"mtime": st.st_mtime, "size": st.st_size, "copy": inv.to_json()})
        except OSError:
            pass
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def current() -> tuple[Inventory | None, str]:
    """The inventory (read again if the file changed since), or why there's none."""
    path = location()
    if path is None:
        return None, "none"
    try:
        inv = read(path)
    except InventoryError as e:
        return None, str(e)
    remember(path, inv)
    return inv, ""
