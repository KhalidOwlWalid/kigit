"""Writes the example project shipped with kigit: examples/blinky/.

    python3 tools/make_example.py      # then commit examples/blinky/

"blinky" is a small LED board: power in (J1), a 3.3 V regulator (U1) with
its capacitors, a header for a microcontroller (J2), and LEDs with their
resistors on a hierarchical "LEDs" sheet, joined to J2 by a bus. Each step
below is a full copy of the project as it was at one commit; `kigit
example` turns them into a git repository (history.json says which step is
which commit), so every feature of kigit has something to show:

  1  first board                      (2 LEDs)
  2  two more LEDs                    parts and tracks added; J2 1x03 -> 1x05
  3  rework the power                 U1 moved, power tracks wider, vias, pour
                                      outline, C2 and R1 values, silkscreen Rev B
  4  rename VIN, share an LED line    net renamed, D4 moved to LED2, TP1 and its
                                      track removed
  5  move the project folder          board/ -> hardware/
  6  design notes                     reviews and discussions (reviews/)
  7  (left uncommitted)               R2 value, D1 nudged: the working tree

KiCad 8 file format, so KiCad 8, 9 and 10 open it. Footprints point at
KiCad's own 3D models (${KICAD8_3DMODEL_DIR}), so the 3D view shows parts.
Everything is generated from the description below, with UUIDs derived
from names (uuid5), so running this again gives the same files.
"""

from __future__ import annotations

import json
import math
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "blinky"
NAME = "blinky"
NS = uuid.UUID("6b1d6f3e-9a3c-4c55-9a51-6b6967697421")  # "kigit!"


def uid(*parts) -> str:
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def f(x: float) -> str:
    """A number as KiCad writes it."""
    s = f"{round(x, 4):.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ------------------------------------------------------------------ design
@dataclass
class Design:
    """The board at one step: what differs between the steps."""
    leds: int = 2
    tp1: bool = True
    vin: str = "VIN"
    c2: str = "10u"
    r_values: dict = field(default_factory=lambda: {1: "1k", 2: "1k", 3: "1k", 4: "1k"})
    d4_on: int = 3            # the LED line D4's cathode is on (3: its own, LED3; 2: shares LED2)
    u1_x: float = 16.0
    power_w: float = 0.4
    rev: str = "A"
    d1_dx: float = 0.0        # D1 nudged (working tree)


def design(step: int) -> Design:
    d = Design()
    if step >= 2:
        d.leds = 4
    if step >= 3:
        d.c2, d.u1_x, d.power_w, d.rev = "22u", 19.0, 0.6, "B"
        d.r_values[1] = "470"
    if step >= 4:
        d.vin, d.d4_on, d.tp1 = "VBUS", 2, False  # D4 moves to LED2
    if step >= 7:
        d.r_values[2] = "680"
        d.d1_dx = 0.6
    return d


# ------------------------------------------------------------- schematic
FONT = "(effects (font (size 1.27 1.27)))"
HIDE = "(effects (font (size 1.27 1.27)) (hide yes))"


def lib_symbol(name: str, ref: str, value: str, body: str, pins: list[tuple], power: bool = False,
               fp: str = "", desc: str = "") -> str:
    """pins: (number, name, type, x, y, angle, length, hidden)."""
    short = name.split(":")[1]
    pin_txt = "".join(
        f"\n\t\t\t\t(pin {t} line (at {f(x)} {f(y)} {a}) (length {f(ln)}){' (hide yes)' if hid else ''}"
        f" (name {q(pn)} {FONT}) (number {q(num)} {FONT}))"
        for num, pn, t, x, y, a, ln, hid in pins)
    return (f"\n\t\t(symbol {q(name)}" + ("\n\t\t\t(power)" if power else "")
            + ("\n\t\t\t(pin_numbers (hide yes)) (pin_names (offset 0) (hide yes))" if power or short in ("R", "C", "LED")
               else "\n\t\t\t(pin_names (offset 1.016))")
            + "\n\t\t\t(exclude_from_sim no) (in_bom yes) (on_board yes)"
            + f"\n\t\t\t(property \"Reference\" {q(ref)} (at 0 3.81 0) {FONT})"
            + f"\n\t\t\t(property \"Value\" {q(value)} (at 0 -3.81 0) {FONT})"
            + f"\n\t\t\t(property \"Footprint\" {q(fp)} (at 0 0 0) {HIDE})"
            + f"\n\t\t\t(property \"Datasheet\" \"~\" (at 0 0 0) {HIDE})"
            + f"\n\t\t\t(property \"Description\" {q(desc)} (at 0 0 0) {HIDE})"
            + f"\n\t\t\t(symbol {q(short + '_0_1')}{body}\n\t\t\t)"
            + f"\n\t\t\t(symbol {q(short + '_1_1')}{pin_txt}\n\t\t\t)\n\t\t)")


def g(kind: str, pts: list[tuple], fill: str = "none", width: float = 0.254) -> str:
    if kind == "rect":
        (x1, y1), (x2, y2) = pts
        return (f"\n\t\t\t\t(rectangle (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)}) "
                f"(stroke (width {f(width)}) (type default)) (fill (type {fill})))")
    xy = " ".join(f"(xy {f(x)} {f(y)})" for x, y in pts)
    return f"\n\t\t\t\t(polyline (pts {xy}) (stroke (width {f(width)}) (type default)) (fill (type {fill})))"


def conn_symbol(n: int) -> str:
    pins = [(str(k), f"Pin_{k}", "passive", -5.08, -(k - 1) * 2.54, 0, 3.81, False) for k in range(1, n + 1)]
    body = g("rect", [(-1.27, 1.27), (1.27, -(n - 1) * 2.54 - 1.27)], "background")
    return lib_symbol(f"Connector_Generic:Conn_01x{n:02d}", "J", f"Conn_01x{n:02d}", body, pins,
                      desc="Generic connector, single row")


LIBS = {
    "Device:R": lambda: lib_symbol("Device:R", "R", "R", g("rect", [(-1.016, -2.54), (1.016, 2.54)]),
                                    [("1", "~", "passive", 0, 3.81, 270, 1.27, False),
                                     ("2", "~", "passive", 0, -3.81, 90, 1.27, False)], desc="Resistor"),
    "Device:C": lambda: lib_symbol("Device:C", "C", "C",
                                    g("poly", [(-2.032, 0.762), (2.032, 0.762)], width=0.508)
                                    + g("poly", [(-2.032, -0.762), (2.032, -0.762)], width=0.508),
                                    [("1", "~", "passive", 0, 3.81, 270, 3.048, False),
                                     ("2", "~", "passive", 0, -3.81, 90, 3.048, False)], desc="Capacitor"),
    "Device:LED": lambda: lib_symbol("Device:LED", "D", "LED",
                                      g("poly", [(-1.27, -1.27), (-1.27, 1.27)])
                                      + g("poly", [(1.27, -1.27), (1.27, 1.27), (-1.27, 0), (1.27, -1.27)]),
                                      [("1", "K", "passive", -3.81, 0, 0, 2.54, False),
                                       ("2", "A", "passive", 3.81, 0, 180, 2.54, False)], desc="Light emitting diode"),
    "kigit:LDO": lambda: lib_symbol("kigit:LDO", "U", "LDO_3V3", g("rect", [(-5.08, -5.08), (5.08, 2.54)], "background"),
                                     [("1", "VI", "power_in", -7.62, 0, 0, 2.54, False),
                                      ("2", "GND", "power_in", 0, -7.62, 90, 2.54, False),
                                      ("3", "VO", "power_out", 7.62, 0, 180, 2.54, False)],
                                     desc="3.3 V low-dropout regulator"),
    "Connector:TestPoint": lambda: lib_symbol("Connector:TestPoint", "TP", "TestPoint",
                                               g("poly", [(0, 2.54), (0, 3.302)]),
                                               [("1", "1", "passive", 0, 0, 90, 2.54, False)], desc="Test point"),
    "power:GND": lambda: lib_symbol("power:GND", "#PWR", "GND",
                                     g("poly", [(0, 0), (0, -1.27), (1.27, -1.27), (0, -2.54), (-1.27, -1.27), (0, -1.27)]),
                                     [("1", "GND", "power_in", 0, 0, 270, 0, True)], power=True),
    "power:+3V3": lambda: lib_symbol("power:+3V3", "#PWR", "+3V3",
                                      g("poly", [(-0.762, 1.27), (0, 2.54)]) + g("poly", [(0, 0), (0, 2.54)])
                                      + g("poly", [(0, 2.54), (0.762, 1.27)]),
                                      [("1", "+3V3", "power_in", 0, 0, 90, 0, True)], power=True),
    "power:PWR_FLAG": lambda: lib_symbol("power:PWR_FLAG", "#FLG", "PWR_FLAG",
                                          g("poly", [(0, 0), (0, 1.27), (-1.016, 1.905), (0, 2.54), (1.016, 1.905), (0, 1.27)]),
                                          [("1", "pwr", "power_out", 0, 0, 90, 0, False)], power=True),
}
PIN_AT = {  # lib pins: number -> (x, y, angle), y up
    "Device:R": {"1": (0, 3.81, 270), "2": (0, -3.81, 90)},
    "Device:C": {"1": (0, 3.81, 270), "2": (0, -3.81, 90)},
    "Device:LED": {"1": (-3.81, 0, 0), "2": (3.81, 0, 180)},
    "kigit:LDO": {"1": (-7.62, 0, 0), "2": (0, -7.62, 90), "3": (7.62, 0, 180)},
    "Connector:TestPoint": {"1": (0, 0, 90)},
}


def place(lib: tuple, at: tuple, angle: int) -> tuple:
    """A lib point (y up) on the sheet (y down), for a symbol at `at` rotated `angle` (CCW)."""
    x, y = lib[0], -lib[1]
    c, s = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[angle % 360]
    return (at[0] + x * c + y * s, at[1] - x * s + y * c)


class Sheet:
    def __init__(self, name: str, path: str) -> None:
        self.name, self.path = name, path  # path: the instance path ("/root" or "/root/sheet")
        self.items: list[str] = []
        self.libs: set[str] = set()
        self.n = 0

    def _id(self, *what) -> str:
        self.n += 1
        return uid(self.name, self.n, *what)

    def symbol(self, lib: str, ref: str, value: str, at: tuple, angle: int = 0, fp: str = "",
               pins: dict | None = None) -> None:
        self.libs.add(lib)
        sid = uid(self.name, "sym", ref)
        pin_txt = "".join(f"\n\t\t(pin {q(p)} (uuid {q(uid(sid, 'pin', p))}))" for p in (pins or PIN_AT.get(lib, {"1": 0})))
        show_ref = not ref.startswith("#")
        self.items.append(
            f"\n\t(symbol (lib_id {q(lib)}) (at {f(at[0])} {f(at[1])} {angle}) (unit 1)"
            f"\n\t\t(exclude_from_sim no) (in_bom {'yes' if show_ref else 'no'}) (on_board {'yes' if show_ref else 'no'}) (dnp no)"
            f"\n\t\t(uuid {q(sid)})"
            f"\n\t\t(property \"Reference\" {q(ref)} (at {f(at[0] + 2.54)} {f(at[1] - 1.27)} 0) "
            f"{FONT if show_ref else HIDE.replace('(hide yes)', '(hide yes)')})"
            f"\n\t\t(property \"Value\" {q(value)} (at {f(at[0] + 2.54)} {f(at[1] + 1.27)} 0) {FONT})"
            f"\n\t\t(property \"Footprint\" {q(fp)} (at {f(at[0])} {f(at[1])} 0) {HIDE})"
            f"\n\t\t(property \"Datasheet\" \"~\" (at {f(at[0])} {f(at[1])} 0) {HIDE})"
            f"{pin_txt}"
            f"\n\t\t(instances (project {q(NAME)} (path {q(self.path)} (reference {q(ref)}) (unit 1))))\n\t)")

    def wire(self, a: tuple, b: tuple) -> None:
        self.items.append(f"\n\t(wire (pts (xy {f(a[0])} {f(a[1])}) (xy {f(b[0])} {f(b[1])})) "
                          f"(stroke (width 0) (type default)) (uuid {q(self._id('wire'))}))")

    def bus(self, a: tuple, b: tuple) -> None:
        self.items.append(f"\n\t(bus (pts (xy {f(a[0])} {f(a[1])}) (xy {f(b[0])} {f(b[1])})) "
                          f"(stroke (width 0) (type default)) (uuid {q(self._id('bus'))}))")

    def label(self, text: str, at: tuple, angle: int = 0) -> None:
        just = "right" if angle == 180 else "left"
        self.items.append(f"\n\t(label {q(text)} (at {f(at[0])} {f(at[1])} {angle}) "
                          f"(effects (font (size 1.27 1.27)) (justify {just} bottom)) (uuid {q(self._id('label', text))}))")

    def hlabel(self, text: str, at: tuple, angle: int = 180) -> None:
        self.items.append(f"\n\t(hierarchical_label {q(text)} (shape input) (at {f(at[0])} {f(at[1])} {angle}) "
                          f"(effects (font (size 1.27 1.27)) (justify right)) (uuid {q(self._id('hlabel', text))}))")

    def text(self, s: str, at: tuple) -> None:
        self.items.append(f"\n\t(text {q(s)} (exclude_from_sim no) (at {f(at[0])} {f(at[1])} 0) "
                          f"(effects (font (size 1.524 1.524)) (justify left bottom)) (uuid {q(self._id('text'))}))")

    # A pin's short wire to a label or a power symbol: the schematic is
    # joined by names, which keeps it readable and its nets unambiguous.
    def stub(self, lib: str, at: tuple, angle: int, pin: str, to: str, n_power: list) -> None:
        px, py, pa = PIN_AT[lib][pin]
        p = place((px, py), at, angle)
        # Outward: away from the body, i.e. opposite to the pin's direction.
        ox, oy = math.cos(math.radians(pa)), math.sin(math.radians(pa))
        o = place((-ox * 2.54, -oy * 2.54), (0, 0), angle)
        end = (round(p[0] + o[0], 3), round(p[1] + o[1], 3))
        self.wire(p, end)
        if to in ("GND", "+3V3"):
            n_power[0] += 1
            self.symbol(f"power:{to}", f"#PWR0{n_power[0]:02d}", to, end, 0)
        else:
            self.label(to, end, 180 if o[0] < 0 else 0)
        return end

    def write(self, uuid_: str, extra: str = "", instances: str = "") -> str:
        libs = "".join(LIBS[k]() if k in LIBS else CONN[k] for k in sorted(self.libs))
        return (f"(kicad_sch (version 20231120) (generator \"eeschema\") (generator_version \"8.0\")"
                f"\n\t(uuid {q(uuid_)})\n\t(paper \"A4\")"
                f"\n\t(title_block (title \"blinky: the kigit example\") (company \"kigit\"))"
                f"\n\t(lib_symbols{libs}\n\t)"
                f"{''.join(self.items)}{extra}{instances}\n)\n")


CONN: dict[str, str] = {}

ROOT_UUID = uid("root")
SHEET_UUID = uid("leds-sheet")


def schematic(d: Design) -> dict[str, str]:
    n_pwr = [0]
    root = Sheet("root", f"/{ROOT_UUID}")
    # J1: power in. Pins on the right (rotated 180).
    root.symbol("Connector_Generic:Conn_01x02", "J1", "PWR_IN", (35.56, 50.8), 180,
                "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", {"1": 0, "2": 0})
    CONN["Connector_Generic:Conn_01x02"] = conn_symbol(2)
    PIN_AT["Connector_Generic:Conn_01x02"] = {"1": (-5.08, 0, 0), "2": (-5.08, -2.54, 0)}
    end = root.stub("Connector_Generic:Conn_01x02", (35.56, 50.8), 180, "1", d.vin, n_pwr)
    root.symbol("power:PWR_FLAG", "#FLG01", "PWR_FLAG", end, 0, pins={"1": 0})
    gnd_end = root.stub("Connector_Generic:Conn_01x02", (35.56, 50.8), 180, "2", "GND", n_pwr)
    root.symbol("power:PWR_FLAG", "#FLG02", "PWR_FLAG", gnd_end, 180, pins={"1": 0})
    # U1, C1, C2: the regulator.
    root.symbol("kigit:LDO", "U1", "LDO_3V3", (78.74, 50.8), 0, "Package_TO_SOT_SMD:SOT-23")
    root.stub("kigit:LDO", (78.74, 50.8), 0, "1", d.vin, n_pwr)
    root.stub("kigit:LDO", (78.74, 50.8), 0, "2", "GND", n_pwr)
    root.stub("kigit:LDO", (78.74, 50.8), 0, "3", "+3V3", n_pwr)
    for ref, val, x, top in (("C1", "1u", 60.96, d.vin), ("C2", d.c2, 101.6, "+3V3")):
        root.symbol("Device:C", ref, val, (x, 60.96), 0, "Capacitor_SMD:C_0603_1608Metric")
        root.stub("Device:C", (x, 60.96), 0, "1", top, n_pwr)
        root.stub("Device:C", (x, 60.96), 0, "2", "GND", n_pwr)
    if d.tp1:
        root.symbol("Connector:TestPoint", "TP1", "3V3", (114.3, 43.18), 0, "TestPoint:TestPoint_Pad_D1.0mm")
        root.stub("Connector:TestPoint", (114.3, 43.18), 0, "1", "+3V3", n_pwr)
    # J2: the microcontroller header. GND, then one line per LED.
    n = 1 + d.leds
    lib = f"Connector_Generic:Conn_01x{n:02d}"
    CONN[lib] = conn_symbol(n)
    PIN_AT[lib] = {str(k): (-5.08, -(k - 1) * 2.54, 0) for k in range(1, n + 1)}
    j2 = (35.56, 88.9)
    root.symbol(lib, "J2", "MCU", j2, 180, f"Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical",
                {str(k): 0 for k in range(1, n + 1)})
    root.stub(lib, j2, 180, "1", "GND", n_pwr)
    for i in range(d.leds):
        root.stub(lib, j2, 180, str(i + 2), f"LED{i}", n_pwr)
    # The LED sheet, and the bus to it.
    width = d.leds - 1
    bus = f"LED[0..{width}]"
    root.bus((63.5, 101.6), (76.2, 101.6))
    root.label(bus, (63.5, 101.6), 0)
    root.text(f"blinky Rev {d.rev}: the kigit example", (30.48, 30.48))
    sheet = (f"\n\t(sheet (at 76.2 93.98) (size 25.4 15.24) (fields_autoplaced yes)"
             f"\n\t\t(stroke (width 0.1524) (type solid)) (fill (color 0 0 0 0.0000))"
             f"\n\t\t(uuid {q(SHEET_UUID)})"
             f"\n\t\t(property \"Sheetname\" \"LEDs\" (at 76.2 93.27 0) (effects (font (size 1.27 1.27)) (justify left bottom)))"
             f"\n\t\t(property \"Sheetfile\" \"leds.kicad_sch\" (at 76.2 109.81 0) (effects (font (size 1.27 1.27)) (justify left top)))"
             f"\n\t\t(pin {q(bus)} input (at 76.2 101.6 180) (effects (font (size 1.27 1.27)) (justify left))"
             f" (uuid {q(uid('sheetpin'))}))"
             f"\n\t\t(instances (project {q(NAME)} (path {q('/' + ROOT_UUID)} (page \"2\"))))\n\t)")
    root_text = root.write(ROOT_UUID, sheet, "\n\t(sheet_instances (path \"/\" (page \"1\")))")

    leds = Sheet("leds", f"/{ROOT_UUID}/{SHEET_UUID}")
    leds.hlabel(bus, (38.1, 101.6), 180)
    leds.bus((38.1, 101.6), (50.8, 101.6))
    leds.label(bus, (50.8, 101.6), 180)
    for i in range(1, d.leds + 1):
        x = 50.8 + (i - 1) * 20.32
        leds.symbol("Device:R", f"R{i}", d.r_values[i], (x, 63.5), 0, "Resistor_SMD:R_0603_1608Metric")
        leds.stub("Device:R", (x, 63.5), 0, "1", "+3V3", n_pwr)
        leds.symbol("Device:LED", f"D{i}", "LED", (x, 76.2), 90, "LED_SMD:LED_0603_1608Metric")
        leds.wire(place(PIN_AT["Device:R"]["2"][:2], (x, 63.5), 0), place(PIN_AT["Device:LED"]["2"][:2], (x, 76.2), 90))
        line = d.d4_on if i == 4 else i - 1
        leds.stub("Device:LED", (x, 76.2), 90, "1", f"LED{line}", n_pwr)
    leds.text("One LED per microcontroller line: it sinks the cathode.", (40.64, 50.8))
    return {"blinky.kicad_sch": root_text, "leds.kicad_sch": leds.write(uid("leds"))}


# --------------------------------------------------------------------- PCB
LAYERS = """	(layers
		(0 "F.Cu" signal) (31 "B.Cu" signal)
		(32 "B.Adhes" user "B.Adhesive") (33 "F.Adhes" user "F.Adhesive")
		(34 "B.Paste" user) (35 "F.Paste" user)
		(36 "B.SilkS" user "B.Silkscreen") (37 "F.SilkS" user "F.Silkscreen")
		(38 "B.Mask" user) (39 "F.Mask" user)
		(40 "Dwgs.User" user "User.Drawings") (41 "Cmts.User" user "User.Comments")
		(44 "Edge.Cuts" user) (45 "Margin" user)
		(46 "B.CrtYd" user "B.Courtyard") (47 "F.CrtYd" user "F.Courtyard")
		(48 "B.Fab" user) (49 "F.Fab" user)
	)"""

MODEL = "${KICAD8_3DMODEL_DIR}"


def rot(p: tuple, deg: float) -> tuple:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (p[0] * c + p[1] * s, -p[0] * s + p[1] * c)


class Board:
    def __init__(self, nets: list[str]) -> None:
        self.nets = {n: i for i, n in enumerate([""] + nets)}
        self.items: list[str] = []
        self.pads: dict[tuple, tuple] = {}  # (ref, pad) -> board position

    def net(self, name: str) -> str:
        return f"(net {self.nets[name]} {q(name)})"

    def footprint(self, lib: str, ref: str, value: str, at: tuple, angle: float, pads: list[tuple],
                  model: str = "", silk: list[tuple] | None = None, layer_text: float = 1.6) -> None:
        """pads: (number, kind, shape, x, y, w, h, net, drill)."""
        fid = uid("fp", ref)
        out = [f"\n\t(footprint {q(lib)} (layer \"F.Cu\") (uuid {q(fid)}) (at {f(at[0])} {f(at[1])}"
               f"{' ' + f(angle) if angle else ''})",
               f"\n\t\t(property \"Reference\" {q(ref)} (at 0 {f(-layer_text)} {f(angle)}) (layer \"F.SilkS\")"
               f" (uuid {q(uid(fid, 'ref'))}) (effects (font (size 0.8 0.8) (thickness 0.12))))",
               f"\n\t\t(property \"Value\" {q(value)} (at 0 {f(layer_text)} {f(angle)}) (layer \"F.Fab\")"
               f" (uuid {q(uid(fid, 'val'))}) (effects (font (size 0.8 0.8) (thickness 0.12))))",
               f"\n\t\t(property \"Footprint\" {q(lib)} (at 0 0 0) (layer \"F.Fab\") (hide yes)"
               f" (uuid {q(uid(fid, 'fp'))}) (effects (font (size 1.27 1.27))))",
               "\n\t\t(attr smd)" if all(p[1] == "smd" for p in pads) else "\n\t\t(attr through_hole)"]
        for (x1, y1, x2, y2) in silk or []:
            out.append(f"\n\t\t(fp_line (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)}) "
                       f"(stroke (width 0.12) (type solid)) (layer \"F.SilkS\") (uuid {q(uid(fid, 'silk', x1, y1, x2, y2))}))")
        for num, kind, shape, x, y, w, h, net, drill in pads:
            layers = '"F.Cu" "F.Paste" "F.Mask"' if kind == "smd" else '"*.Cu" "*.Mask"'
            if shape == "circle" and kind == "smd":
                layers = '"F.Cu" "F.Mask"'
            extra = " (roundrect_rratio 0.25)" if shape == "roundrect" else ""
            dr = f" (drill {f(drill)})" if drill else ""
            netx = f" {self.net(net)}" if net else ""
            out.append(f"\n\t\t(pad {q(num)} {kind} {shape} (at {f(x)} {f(y)}{' ' + f(angle) if angle else ''}) "
                       f"(size {f(w)} {f(h)}){dr} (layers {layers}){extra}{netx} (uuid {q(uid(fid, 'pad', num))}))")
            r = rot((x, y), angle)
            self.pads[(ref, num)] = (round(at[0] + r[0], 4), round(at[1] + r[1], 4))
        if model:
            out.append(f"\n\t\t(model {q(MODEL + '/' + model)} (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) "
                       "(rotate (xyz 0 0 0)))")
        out.append("\n\t)")
        self.items.append("".join(out))

    def track(self, pts: list[tuple], net: str, width: float = 0.25, layer: str = "F.Cu") -> None:
        for a, b in zip(pts, pts[1:]):
            self.items.append(f"\n\t(segment (start {f(a[0])} {f(a[1])}) (end {f(b[0])} {f(b[1])}) (width {f(width)}) "
                              f"(layer {q(layer)}) (net {self.nets[net]}) (uuid {q(uid('seg', net, layer, a, b))}))")

    def via(self, at: tuple, net: str) -> None:
        self.items.append(f"\n\t(via (at {f(at[0])} {f(at[1])}) (size 0.6) (drill 0.3) (layers \"F.Cu\" \"B.Cu\") "
                          f"(net {self.nets[net]}) (uuid {q(uid('via', net, at))}))")

    def write(self, extra: str) -> str:
        nets = "".join(f"\n\t(net {i} {q(n)})" for n, i in self.nets.items())
        return ("(kicad_pcb (version 20240108) (generator \"pcbnew\") (generator_version \"8.0\")"
                "\n\t(general (thickness 1.6) (legacy_teardrops no))\n\t(paper \"A4\")"
                "\n\t(title_block (title \"blinky: the kigit example\") (company \"kigit\"))\n"
                f"{LAYERS}\n\t(setup (pad_to_mask_clearance 0) (allow_soldermask_bridges_in_footprints no))"
                f"{nets}{''.join(self.items)}{extra}\n)\n")


def chip(n1: str, n2: str) -> list[tuple]:
    """0603 pads: (number, kind, shape, x, y, w, h, net, drill)."""
    return [("1", "smd", "roundrect", -0.825, 0, 0.8, 0.95, n1, 0),
            ("2", "smd", "roundrect", 0.825, 0, 0.8, 0.95, n2, 0)]


def header(nets: list[str]) -> list[tuple]:
    return [(str(k + 1), "thru_hole", "rect" if k == 0 else "oval", 0, k * 2.54, 1.7, 1.7, n, 1.0)
            for k, n in enumerate(nets)]


def pcb(d: Design) -> str:
    # Net names as KiCad gives them: labels on the root sheet get its path, "/".
    vin = "/" + d.vin
    led = lambda i: f"/LED{i}"
    led_lines = [led(i) for i in range(d.leds)]
    nets = ["GND", vin, "+3V3"] + led_lines + [f"Net-(D{i}-A)" for i in range(1, d.leds + 1)]
    b = Board(nets)
    pw = d.power_w
    # J1 power in, U1 regulator, C1/C2.
    b.footprint("Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", "J1", "PWR_IN", (5, 8), 0,
                header([vin, "GND"]), "Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x02_P2.54mm_Vertical.step",
                [(-1.33, -1.33, 1.33, -1.33), (1.33, -1.33, 1.33, 3.87), (1.33, 3.87, -1.33, 3.87),
                 (-1.33, 3.87, -1.33, -1.33)], 2.6)
    ux = d.u1_x
    b.footprint("Package_TO_SOT_SMD:SOT-23", "U1", "LDO_3V3", (ux, 10), 0,
                [("1", "smd", "roundrect", -1.1, 0.95, 1.3, 0.6, vin, 0),
                 ("2", "smd", "roundrect", -1.1, -0.95, 1.3, 0.6, "GND", 0),
                 ("3", "smd", "roundrect", 1.1, 0, 1.3, 0.6, "+3V3", 0)],
                "Package_TO_SOT_SMD.3dshapes/SOT-23.step", [(-0.6, -1.5, 0.6, -1.5), (-0.6, 1.5, 0.6, 1.5)], 2.4)
    b.footprint("Capacitor_SMD:C_0603_1608Metric", "C1", "1u", (12, 15), 0, chip(vin, "GND"),
                "Capacitor_SMD.3dshapes/C_0603_1608Metric.step")
    b.footprint("Capacitor_SMD:C_0603_1608Metric", "C2", d.c2, (24, 15), 0, chip("+3V3", "GND"),
                "Capacitor_SMD.3dshapes/C_0603_1608Metric.step")
    if d.tp1:
        b.footprint("TestPoint:TestPoint_Pad_D1.0mm", "TP1", "3V3", (27, 5), 0,
                    [("1", "smd", "circle", 0, 0, 1, 1, "+3V3", 0)], "", None, 1.5)
    n = 1 + d.leds
    b.footprint(f"Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical", "J2", "MCU", (5, 22), 0,
                header(["GND"] + led_lines),
                f"Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x{n:02d}_P2.54mm_Vertical.step",
                [(-1.33, -1.33, 1.33, -1.33), (1.33, -1.33, 1.33, (n - 1) * 2.54 + 1.33),
                 (1.33, (n - 1) * 2.54 + 1.33, -1.33, (n - 1) * 2.54 + 1.33),
                 (-1.33, (n - 1) * 2.54 + 1.33, -1.33, -1.33)], 2.6)
    for i in range(1, d.leds + 1):
        x = 32 + (i - 1) * 7
        b.footprint("Resistor_SMD:R_0603_1608Metric", f"R{i}", d.r_values[i], (x, 12), 270,
                    chip("+3V3", f"Net-(D{i}-A)"), "Resistor_SMD.3dshapes/R_0603_1608Metric.step")
        line = d.d4_on if i == 4 else i - 1
        dx = d.d1_dx if i == 1 else 0
        b.footprint("LED_SMD:LED_0603_1608Metric", f"D{i}", "LED", (x + dx, 20), 90,
                    chip(led(line), f"Net-(D{i}-A)"), "LED_SMD.3dshapes/LED_0603_1608Metric.step",
                    [(-1.4, 0.8, 1.4, 0.8)])
    for ref, at in (("H1", (56, 4)), ("H2", (56, 36))):
        b.footprint("MountingHole:MountingHole_3.2mm_M3", ref, "MountingHole", at, 0,
                    [("", "np_thru_hole", "circle", 0, 0, 3.2, 3.2, "", 3.2)], "", None, 3)

    P = b.pads
    # VIN: J1 to U1 and C1.
    b.track([P[("J1", "1")], (9, 8), (9, P[("U1", "1")][1]), P[("U1", "1")]], vin, pw)
    b.track([(9, P[("U1", "1")][1]), (9, 15), P[("C1", "1")]], vin, pw)
    # +3V3: U1 to C2, the test point and the LED resistors along a rail.
    out = P[("U1", "3")]
    b.track([out, (P[("C2", "1")][0], out[1]), P[("C2", "1")]], "+3V3", pw)
    rail_end = 32 + (d.leds - 1) * 7
    b.track([(P[("C2", "1")][0], out[1]), (28, out[1]), (28, 7), (rail_end, 7)], "+3V3", pw)
    if d.tp1:
        b.track([(28, 7), (28, 5), P[("TP1", "1")]], "+3V3", 0.25)
    for i in range(1, d.leds + 1):
        x = 32 + (i - 1) * 7
        b.track([(x, 7), P[(f"R{i}", "1")]], "+3V3", 0.25)
        b.track([P[(f"R{i}", "2")], P[(f"D{i}", "2")]], f"Net-(D{i}-A)", 0.25)
    # GND: every GND pad drops to the bottom pour through a via.
    for ref, pad, v in (("J1", "2", (8, 12)), ("U1", "2", (ux - 1.1, 6.5)), ("C1", "2", (12.825, 17.5)),
                        ("C2", "2", (24.825, 17.5)), ("J2", "1", (8, 22))):
        b.track([P[(ref, pad)], v], "GND", pw if ref in ("J1", "U1") else 0.25)
        b.via(v, "GND")
    if d.rev == "B":
        b.via((45, 30), "GND")  # stitching, added with the power rework
    # LED lines: from each cathode down through a via, along the bottom to J2.
    for i in range(1, d.leds + 1):
        x = (32 + (i - 1) * 7) + (d.d1_dx if i == 1 else 0)
        line = d.d4_on if i == 4 else i - 1
        b.track([P[(f"D{i}", "1")], (x, 24)], led(line), 0.25)
        b.via((x, 24), led(line))
        y = 22 + (line + 1) * 2.54
        if i == 4 and line != 3:  # D4 shares LED2: joins its line instead of running to J2
            b.track([(x, 24), (x, y), (32 + 2 * 7, y)], led(line), 0.25, "B.Cu")
            continue
        b.track([(x, 24), (x, y), P[("J2", str(line + 2))]], led(line), 0.25, "B.Cu")

    outline = "(gr_rect (start 0 0) (end 60 40) (stroke (width 0.1) (type default)) (fill none) " \
              f"(layer \"Edge.Cuts\") (uuid {q(uid('edge'))}))"
    silk = (f"(gr_text \"blinky Rev {d.rev}\" (at 30 36 0) (layer \"F.SilkS\") (uuid {q(uid('rev'))}) "
            "(effects (font (size 1.5 1.5) (thickness 0.2))))")
    corner = [(1, 1), (59, 1), (59, 39), (1, 39)] if d.rev == "A" else [(1, 1), (59, 1), (59, 30), (50, 39), (1, 39)]
    zone = (f"(zone (net {b.nets['GND']}) (net_name \"GND\") (layer \"B.Cu\") (uuid {q(uid('zone'))}) "
            "(hatch edge 0.5) (connect_pads (clearance 0.3)) (min_thickness 0.25) (filled_areas_thickness no) "
            "(fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon (pts "
            + " ".join(f"(xy {f(x)} {f(y)})" for x, y in corner) + ")))")
    return b.write(f"\n\t{outline}\n\t{silk}\n\t{zone}")


def project() -> str:
    return json.dumps({"meta": {"filename": f"{NAME}.kicad_pro", "version": 1},
                       "sheets": [[ROOT_UUID, "Root"], [SHEET_UUID, "LEDs"]]}, indent=2) + "\n"


# ------------------------------------------------------- reviews (step 6)
def reviews() -> dict[str, str]:
    """Design notes on the history: placeholders {{commit:N}} are the Nth
    commit's full hash, filled in by `kigit example`."""
    c = lambda n: "{{commit:%d}}" % n
    seen = lambda n, side="new": {"old": c(n - 1), "new": c(n), "side": side}
    note = lambda title, body, anchor, tags, created: (
        f"## {title}\n<!-- kigit-note {json.dumps({'id': uid('note', title)[:8], 'anchor': anchor, 'tags': tags, 'created': created})} -->\n\n{body}\n\n")
    r2 = ("---\nid: 2a5c0e11\ncommit: " + c(2) + "\nparent: " + c(1) + "\nsubject: Add two more LEDs\n"
          "date: 2026-01-12 10:00\nauthor: Author A\ncreated: 2026-01-12 18:20\nupdated: 2026-01-12 18:20\n---\n\n"
          "Four status LEDs instead of two: one per state of the firmware's state machine. "
          "J2 grows from 3 to 5 pins to bring the extra lines out.\n\n"
          + note("D3 and D4 added", "Same LED and 1k resistor as D1/D2, so the brightness matches.\n\n"
                 "- [x] footprints from the standard library\n- [ ] check the colour order with the firmware",
                 {"tab": "pcb", "kind": "footprint", "name": "D3", "seen": seen(2)}, ["reason", "todo"], "2026-01-12 18:20")
          + note("LED bus widened", "The bus to the LEDs sheet is now `LED[0..3]`.",
                 {"tab": "sch", "kind": "bus", "name": "LED[0..3]", "seen": seen(2)}, ["reason"], "2026-01-12 18:22"))
    r3 = ("---\nid: 3b6d1f22\ncommit: " + c(3) + "\nparent: " + c(2) + "\nsubject: Rework the power\n"
          "date: 2026-01-19 10:00\nauthor: Author A\ncreated: 2026-01-19 17:05\nupdated: 2026-01-20 09:12\n---\n\n"
          "Rev B power: the regulator moves next to the LED rail and the power tracks get wider.\n\n"
          + note("U1 moved 3 mm right", "Shorter +3V3 run to C2. Its pads keep their nets, so the diff shows it "
                 "as **moved**, not removed and added.",
                 {"tab": "pcb", "kind": "footprint", "name": "U1", "seen": seen(3)}, ["reason"], "2026-01-19 17:05")
          + note("C2 to 22u", "Output ripple with four LEDs switching: $\\Delta V = \\frac{I \\, \\Delta t}{C}$, "
                 "so twice the capacitance halves it.",
                 {"tab": "sch", "kind": "part", "name": "C2", "seen": seen(3)}, ["reason"], "2026-01-19 17:20")
          + note("Is 0.6 mm enough?", "Worst case is ~80 mA; 0.6 mm on 1 oz copper is plenty, but worth a look.",
                 {"tab": "pcb", "kind": "net", "name": "+3V3", "seen": seen(3)}, ["question"], "2026-01-20 09:12"))
    msg = lambda who, when, kind, head, text: (
        f"**{who}** · {when} · at {{{{short:{head}}}}}\n<!-- kigit-msg "
        f"{json.dumps({'author': who, 'time': when, 'head': c(head), 'kind': kind})} -->\n\n{text}\n\n")
    t1 = ("---\nid: 7e3a90c4\ntitle: TP1 is in the way of the rail\nopened: 2026-01-19 17:30\nby: Author B\n"
          f"commit: {c(3)}\nanchor: {json.dumps({'tab': 'pcb', 'kind': 'footprint', 'name': 'TP1', 'seen': seen(3)})}\n---\n\n"
          + msg("Author B", "2026-01-19 17:30", "comment", 3, "TP1 sits right where the +3V3 rail turns. Do we still need it now that C2 has a big pad?")
          + msg("Author A", "2026-01-21 11:02", "done", 4, "Removed TP1 and its stub; probe C2 instead."))
    t2 = ("---\nid: 9c41b2d7\ntitle: D4 shares LED2: intended?\nopened: 2026-01-26 09:15\nby: Author C\n"
          f"commit: {c(4)}\nanchor: {json.dumps({'tab': 'sch', 'kind': 'part', 'name': 'D4', 'seen': seen(4)})}\n---\n\n"
          + msg("Author C", "2026-01-26 09:15", "comment", 4, "D4's cathode now joins LED2, so D3 and D4 always light together. "
                "Is that what the firmware expects? If not, it needs its own line back."))
    decisions = ("---\ntags: [decision, power]\nstatus: accepted\n---\n# Why an LDO\n\nThe LEDs draw under 100 mA in "
                 "total, so a small LDO is simpler and quieter than a buck converter. See [[3b6d1f22]] for the "
                 "rework. #power\n")
    return {"reviews/2a5c0e11.md": r2, "reviews/3b6d1f22.md": r3, "reviews/threads/7e3a90c4.md": t1,
            "reviews/threads/9c41b2d7.md": t2, "reviews/decisions/Why an LDO.md": decisions}


STEPS = [
    (1, "board", "First board: power in, 3.3 V regulator, two status LEDs", "2026-01-05T10:00:00+00:00"),
    (2, "board", "Add two more LEDs", "2026-01-12T10:00:00+00:00"),
    (3, "board", "Rework the power: move U1, wider tracks, Rev B", "2026-01-19T10:00:00+00:00"),
    (4, "board", "Rename VIN to VBUS, let D4 share LED2, drop TP1", "2026-01-26T10:00:00+00:00"),
    (5, "hardware", "Move the project into hardware/", "2026-02-02T10:00:00+00:00"),
    (6, "hardware", "Add design notes: reviews and discussions", "2026-02-09T10:00:00+00:00"),
]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    steps_dir = OUT / "steps"
    for step in [s[0] for s in STEPS] + [7]:
        d = design(min(step, 4) if step in (5, 6) else step)
        files = {f"{NAME}.kicad_pro": project(), f"{NAME}.kicad_pcb": pcb(d), **schematic(d)}
        if step >= 6:
            files.update(reviews())
        for rel, text in files.items():
            p = steps_dir / str(step) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text.encode("utf-8"))
    history = {
        "name": NAME,
        "author": {"name": "Author A", "email": "author-a@example.invalid"},
        "commits": [{"step": s, "folder": folder, "message": msg, "date": date} for s, folder, msg, date in STEPS],
        "uncommitted": {"step": 7, "folder": "hardware"},
    }
    (OUT / "history.json").write_text(json.dumps(history, indent=2) + "\n")
    (OUT / "README.md").write_text(
        "# blinky: the kigit example\n\nProject snapshots, one per commit, that `kigit example` turns into a git "
        "repository to try kigit on. Made by `tools/make_example.py`; don't edit by hand.\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
