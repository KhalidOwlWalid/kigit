"""Reading a cart exported from Mouser or LCSC into rows of {sku, mpn,
manufacturer, description, qty, refs}, for the BOM page's Ordered column
and board view.

What the sites give (tests/test_examples/exported_boms_from_distributor):
- LCSC: a CSV: Index, LCSC#, MPN, Manufacturer, Package, Customer #,
  Description, RoHS, Quantity, MOQ, Multiple, Unit Price($), ...
- Mouser: an old Excel .xls ("Cart" sheet): a title block, then Mouser No,
  Mfr. No, Manufacturer, Customer No, Description, RoHS, Lifecycle, Order
  Qty., Price (GBP), ... and totals rows after.
"Customer #" / "Customer No" holds the references when the cart came from
kigit's own export, which is the surest match.

Column names differ between sites and change over time, so columns are
found by name, loosely, and the header row is looked for in the first rows.
.xls is read with xlrd; .xlsx with the standard library (zipped XML).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from xml.etree import ElementTree

SITES = {"mouser": "Mouser", "lcsc": "LCSC"}
MAX_BYTES = 5 * 1024 * 1024
_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class CartError(ValueError):
    """A file kigit can't read as a cart (the message says why)."""


def _key(name: str) -> str:
    """A column name, compared: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


# ----------------------------------------------------------------- tables
def _xlsx_rows(data: bytes) -> list[list[str]]:
    """The first worksheet of an .xlsx, as rows of text."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise CartError("not an .xlsx file (an old .xls? Save it as .xlsx or .csv)") from e
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.iter(f"{_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
    # The first sheet in the workbook's order.
    sheet = "xl/worksheets/sheet1.xml"
    try:
        wb = ElementTree.fromstring(z.read("xl/workbook.xml"))
        first = wb.find(f"{_NS}sheets/{_NS}sheet")
        rels = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        rid = first.get(f"{_REL}id") if first is not None else None
        for r in rels:
            if r.get("Id") == rid:
                target = r.get("Target", "").lstrip("/")
                sheet = target if target.startswith("xl/") else "xl/" + target
    except (KeyError, ElementTree.ParseError):
        pass
    if sheet not in z.namelist():
        raise CartError("no worksheet in the .xlsx")
    rows: list[list[str]] = []
    for row in ElementTree.fromstring(z.read(sheet)).iter(f"{_NS}row"):
        cells: dict[int, str] = {}
        for c in row.iter(f"{_NS}c"):
            col = 0
            for ch in re.match(r"[A-Z]+", c.get("r", "A")).group(0):
                col = col * 26 + (ord(ch) - 64)
            t, v = c.get("t"), c.find(f"{_NS}v")
            if t == "s" and v is not None:
                text = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
            elif t == "inlineStr":
                text = "".join(x.text or "" for x in c.iter(f"{_NS}t"))
            else:
                text = v.text if v is not None and v.text else ""
                if re.fullmatch(r"-?\d+\.0+", text):
                    text = text.split(".")[0]  # 10.0 -> 10
            cells[col - 1] = text.strip()
        if cells:
            rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return rows


def _csv_rows(data: bytes) -> list[list[str]]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)]


def _xls_rows(data: bytes) -> list[list[str]]:
    """The first sheet of an old Excel .xls (what Mouser's cart export gives)."""
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception as e:  # xlrd raises several kinds (XLRDError, CompDocError...) for a broken file
        raise CartError(f"not an Excel .xls file kigit can read ({e})") from e
    sheet = book.sheet_by_index(0)
    rows = []
    for r in range(sheet.nrows):
        row = []
        for c in sheet.row(r):
            v = c.value
            if isinstance(v, float) and v.is_integer():
                v = int(v)  # 3.0 -> 3
            row.append(str(v).strip())
        rows.append(row)
    return rows


def read_table(data: bytes, filename: str) -> list[list[str]]:
    if len(data) > MAX_BYTES:
        raise CartError("the file is too big for a cart (over 5 MB)")
    name = filename.lower()
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or name.endswith(".xls"):  # an old Office file
        return _xls_rows(data)
    if name.endswith(".xlsx") or data[:2] == b"PK":
        return _xlsx_rows(data)
    return _csv_rows(data)


# ------------------------------------------------------------------ carts
def _role(name: str, site: str) -> str:
    """What a column is: sku (the site's number), mpn, manufacturer,
    description, qty; "" for anything else."""
    k = _key(name)
    if not k:
        return ""
    if k.startswith("customer"):  # Customer # / Customer No / Customer Part Number: kigit's references
        return "refs"
    if k.startswith(site) or (site == "lcsc" and k in ("productcode", "partcode", "lcscno", "lcsc")):
        return "sku"
    if k in ("mpn",) or k.startswith(("mfrpart", "mfrno", "manufacturerpart", "manufacturepart", "mfgpart")) \
            or k in ("mfr", "mfrnumber", "manufacturerpn", "partnumber", "mfrpn"):
        return "mpn"
    if k.startswith(("manufacturer", "mfrname", "brand")) or k in ("mfrs", "mfg"):
        return "manufacturer"
    if k.startswith(("description", "desc", "productdescription")):
        return "description"
    if k in ("qty", "quantity", "orderqty", "orderquantity", "quantity1", "cartqty", "cartquantity", "buyqty",
             "qtyordered", "orderedqty", "orderedquantity"):
        return "qty"
    return ""


def _number(s: str) -> int:
    m = re.search(r"\d[\d,. ]*", s or "")
    if not m:
        return 0
    digits = re.sub(r"[,. ](?=\d{3}(\D|$))", "", m.group(0))  # 1,000 / 1.000 / 1 000
    try:
        return int(float(digits.replace(",", ".")))
    except ValueError:
        return 0


def parse_cart(data: bytes, filename: str, site: str) -> list[dict]:
    """The cart's rows: {sku, mpn, manufacturer, description, qty, refs}.
    Rows without a quantity, or without any part number or references, are
    skipped (titles, totals)."""
    if site not in SITES:
        raise CartError(f"kigit reads Mouser and LCSC carts, not {site}")
    rows = read_table(data, filename)
    for h, header in enumerate(rows[:30]):
        roles = [_role(c, site) for c in header]
        if "qty" in roles and ("sku" in roles or "mpn" in roles):
            break
    else:
        raise CartError(f"no quantity and part number columns found: is this a {SITES[site]} cart export?")
    col = {}
    for i, r in enumerate(roles):
        col.setdefault(r, i)  # the first column of each kind
    out = []
    for row in rows[h + 1:]:
        get = lambda r: row[col[r]].strip() if r in col and col[r] < len(row) else ""  # noqa: E731
        qty = _number(get("qty"))
        sku, mpn = get("sku"), get("mpn")
        if sku.upper() in ("N/A", "-"):
            sku = ""
        refs = [r for r in re.split(r"[\s,;]+", get("refs")) if r and re.fullmatch(r"[A-Za-z#]+[\w.-]*", r)]
        if qty <= 0 or not (sku or mpn or refs):
            continue
        out.append({"sku": sku, "mpn": mpn, "manufacturer": get("manufacturer"),
                    "description": get("description")[:200], "qty": qty, "refs": refs})
    if not out:
        raise CartError("the cart has no rows with a part number and a quantity")
    return out
