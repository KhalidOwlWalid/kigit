# kigit

Per-net visual diff of a KiCad PCB between two git revisions.

`kigit` reads the `.kicad_pcb` file straight out of git, matches every track,
arc, via and pad between the two revisions, and writes a single self-contained
HTML page where you can hover a trace to highlight its whole net: what was
added, what was removed, and how the net's copper length changed.

## Build

Needs a C++20 compiler and CMake 3.16+. `nlohmann_json` is used from the
system if installed, otherwise downloaded automatically.

```sh
cmake -S . -B build
cmake --build build -j
# optional: install to ~/.local/bin
cmake --install build --prefix ~/.local
```

## GUI

```sh
kigit gui                  # start in the current folder
kigit gui ~/path/to/board  # or any folder
```

1. **Open a project.** Type a folder or press **Browse** (folders holding
   KiCad files are marked). kigit looks for a project in that folder and up
   to two levels below. It tells you if it finds none, if the project has no
   `.kicad_pcb`, or if it isn't in a git repository; if it finds several, it
   asks which one.
2. **Pick two commits.** All commits are listed, newest first, tagged PCB /
   SCH when they changed the board or schematic. The top entry is your
   working tree: HEAD plus any uncommitted changes. Hover a message to read
   all of it. Nothing is rendered yet.

   **Filter commits** (then **Find**): how many to list (last 100 ... all),
   a date range, and "only commits that changed the board or schematic",
   which searches the whole history. If the project folder was renamed or
   moved, its history is followed through the old folders too.

   **Diff commits manually** (collapsed under Compare): type any two
   revisions git understands (hash, `HEAD~3`, branch, tag, or `LOCAL`) and
   press **Find manually**, for when the commit you want isn't in the list.
3. **Compare.** kigit diffs the two and the viewer opens on the schematic
   (the PCB is one tab away).

The GUI is a small Python app ([NiceGUI](https://nicegui.io)) in `gui/`
that drives the `kigit` command line, so it needs
[uv](https://docs.astral.sh/uv/), which sets up its Python environment on
first run. `kigit gui` finds it next to the binary (`<repo>/gui` from a
build folder, `<prefix>/share/kigit/gui` when installed) or via
`KIGIT_GUI_DIR`. Options: `--port N`, `--no-browser`.

What the GUI uses from the CLI, if you want to script it yourself:

```sh
kigit --projects [--depth N]    # KiCad projects in the folder and below, as JSON
kigit --log [--max N] [--since DATE] [--until DATE] [--kicad-only]
                                # commits (+ uncommitted changes), as JSON
kigit -n -o - A..B              # the viewer page on stdout
kigit -n --json -o - A..B       # the data on stdout
```

GUI tests (simulated user, no browser):

```sh
cd gui && KIGIT_BIN=../build/kigit KIGIT_PROJECT=~/path/to/board uv run pytest
```

### Windows

kigit builds on Windows with MSVC (Visual Studio 2022) or MinGW-w64 GCC 11+;
CMake detects the platform and compiler. It needs `git` on PATH (Git for
Windows), and `uv` for the GUI.

```bat
cmake -S . -B build
cmake --build build --config Release
ctest --test-dir build -C Release
build\Release\kigit.exe gui
```

Every push is built and tested on Windows, Linux and macOS by GitHub Actions
(`.github/workflows/ci.yml`).

## Usage

Run it inside a KiCad project folder:

```sh
kigit                      # HEAD vs the working tree (uncommitted changes)
kigit HEAD~3               # HEAD~3 vs the working tree
kigit c46da63..HEAD        # two commits
kigit v1.0 v1.1 board.kicad_pcb
kigit -n -s HEAD~1..HEAD   # don't open a browser, print every changed net
```

Or from anywhere, pointing at the project with `--kicad-repo` (short: `-C`):

```sh
kigit --kicad-repo ~/Documents/Kicad/owl/owl_v1 c46da63..HEAD
kigit -C ~/Documents/Kicad/owl HEAD~1          # finds the board in subfolders
kigit -C path/to/board.kicad_pro HEAD~1        # a .kicad_pro/.kicad_pcb works too
```

### Moved or renamed boards

If the board isn't at the same path in one of the revisions (you moved
`hardware/owl.kicad_pcb` to `pcb/owl_v1.kicad_pcb`, say), kigit searches that
revision for every `.kicad_pcb` and picks the one sharing the most footprints
and nets with the latest version of your board. It prints a warning with the
old and new paths and how close the match is, shows the same warning in the
viewer, and carries on. If nothing is at least 25% similar it stops and lists
the boards it found instead of guessing.

```
warning: pcb/owl_v1.kicad_pcb doesn't exist in 259cd18, using hardware/owl.kicad_pcb
         instead (98% match: 62 of 63 footprints and 74 of 74 nets are the same ...)
warning: the board was moved or renamed: hardware/owl.kicad_pcb (259cd18) -> pcb/owl_v1.kicad_pcb (f038da9)
```

### Without git

Compare two copies of a board directly, e.g. two saved versions of the same
project. No git repository needed; the older file goes first:

```sh
kigit --files owl_v1_old/owl_v1.kicad_pcb owl_v1/owl_v1.kicad_pcb
kigit old.kicad_pcb new.kicad_pcb              # two board files = --files
```

The viewer labels them by file name, or by folder name when both files have
the same name.

If you give the newer revision first, kigit swaps them so "added" always
means "added in the newer revision".

The page is written to `.kigit/` next to the board (or `-o FILE`) and opened in your
browser. In the viewer:

| Action | What it does |
| --- | --- |
| Hover a trace, via or pad | Highlight its net, show the net's changes |
| Click | Pin the net (click again or `Esc` to clear) |
| Scroll / drag | Zoom / pan |
| `F` | Fit the board |
| `/` | Filter nets |
| Double-click a net in the list | Zoom to it |

The terminal also gets a summary of the most-changed nets.

### Schematic tab

The page has a **Schematic** tab next to the PCB. It draws each sheet
(wires, parts, labels, sheet boxes) with the same colours: green added, red
dashed removed, amber for parts whose value, footprint or connections
changed, grey unchanged.

| Action | What it does |
| --- | --- |
| Hover a wire, label or pin | Highlight its net; tooltip shows pins that joined/left, renames, "wiring redrawn, connections unchanged" |
| Hover a part | Its changes: fields (value, footprint, MPN...), pins moved to other nets, moved |
| Click | Pin it; the card can jump to other sheets the net is on |
| Double-click a sheet box | Open that sheet (Backspace goes back up) |
| Sidebar | Sheet tree with change counts, and the changes on the current sheet |

"Old positions" shows moved parts' previous place as a faint ghost (off by
default). The drawing is kigit's own, not KiCad's export: close to KiCad but
with a different font, and buses, images and text boxes aren't drawn yet.

## Schematic nets (work in progress)

kigit also reads the schematic next to the board (all sheets, including
KiCad 10's multiple top-level sheets from the `.kicad_pro`) and works out its
nets itself: which pins each wire, label and power symbol connects. There's
no schematic view yet; for now it's available as data:

```sh
kigit --json c46da63..HEAD            # PCB diff + both revisions' schematic nets
```

To verify the connectivity against KiCad's own netlist:

```sh
kicad-cli sch export netlist -o owl.net owl_v1.kicad_sch
kigit --check-netlist owl.net         # LOCAL; or add a revision: ... owl.net c46da63
```

It prints any net whose pins or name differ. On the owl_v1 history (25
schematic commits) every net matches KiCad exactly. Buses aren't supported
yet.

### Schematic diff

Every run also compares the two schematics and prints what changed:

```
schematic: parts +1 -0, 8 changed electrically, 1 fields only, 0 only moved; 3 nets changed, 0 renamed, 1 only redrawn
  ~ J3     J3.1 (Pin_1): /owl_v1/CAN Transceiver/CAN_H -> GND, J3.3 (Pin_3): GND -> /owl_v1/CAN Transceiver/CAN_H, moved
  + R19    R          [IOs] on +3.3V, GND
  ~ C14    Footprint Capacitor_SMD:C_0402_1005Metric -> Capacitor_SMD:C_0603_1608Metric
  ~ net GND                      joined: J3.1 (Pin_1), R19.2  left: J3.3 (Pin_3)
```

- Parts are matched by KiCad's internal ID, so re-annotating shows as a
  rename, not a remove + add.
- Changes are split into **electrical** (part added/removed, value,
  footprint or symbol changed, a pin moved to another net), **fields only**
  (BOM fields like MPN, or the reference) and **cosmetic** (part moved,
  wires redrawn, labels moved, but the same connections). Cosmetic changes
  are counted but only listed with `--stats`.
- Nets are paired by label name, else by shared pins, and report which pins
  joined or left, renames, and nets merged into another.

`--json` includes all of this under `schematic_diff`.

## How matching works

**PCB.** Tracks, arcs, vias and pads are matched in two passes:

1. **By KiCad's ID** (the `uuid`/`tstamp` KiCad gives every item and keeps
   when you move it; a pad uses its footprint's ID plus its pad number).
   Same ID and same place: unchanged. Same ID and same copper (net, layers,
   width/size, length) at a new place or angle: **moved**, shown in blue,
   with an optional ghost at the old position. Same ID but edited (a dragged
   track end, a new width or net): removed + added.
2. **By geometry** for everything else (files without IDs, or copper KiCad
   gave new IDs, e.g. after re-routing): same kind, net, layers and
   coordinates (to 1 nm) means unchanged.

So moving a footprint or the whole layout shows as moved, not as everything
removed and re-added, while re-routing still shows the new and old copper.

Zones (copper pours) are drawn from the newer revision only and aren't
diffed, because refilling a pour changes its shape every time.

**Schematic.** Parts are matched by KiCad ID (then reference), nets by label
name or shared pins, wires and labels by position; see "Schematic diff".

## Logs

Every run keeps a log, named after when it started, so you can look back at
what happened (and send it along with a bug report):

| Platform | Default folder |
| --- | --- |
| Linux | `~/.local/state/kigit/log/` |
| macOS | `~/Library/Application Support/kigit/log/` |
| Windows | `%LOCALAPPDATA%\kigit\log\` |

Change it with `--log-dir DIR` (or `KIGIT_LOG_DIR`); `--no-log` turns it off.
Old logs are kept.

- **Command line:** `kigit_<date>_<time>_<pid>.log`: what was compared, timings,
  how much changed, warnings, errors, exit code. `-V` also prints the log to
  the console, with debug lines (every git command and its duration).
- **GUI:** `kigit-gui_<date>_<time>_<pid>.log` holds the whole session: what
  you opened and compared, every message the GUI showed you, the kigit calls
  it made (their own lines included), and any error in the GUI. The same lines
  go to the console you ran `kigit gui` from, and the **log** button in the
  GUI's header shows the file and its latest lines.

```
[2026-10-28 01:25:56.785] [kigit-gui] [info] found 1 KiCad project(s): owl_v1 (/home/me/Kicad/owl/owl_v1)
[2026-10-28 01:25:56.792] [kigit] [info] run: kigit -C .../owl_v1.kicad_pcb --log --max 200 ...
[2026-10-28 01:25:56.826] [kigit] [info] done: exit 0 in 34 ms
[2026-10-28 01:25:56.827] [kigit-gui] [info] loaded .../owl_v1.kicad_pcb: 39 of 39 commits listed
```

## Testing

```sh
cmake -S . -B build && cmake --build build -j
cd build && ctest            # everything (about 5 s)
ctest -L unit                # C++ only
ctest -L gui                 # the GUI (needs uv)
```

The tests don't need any of your projects: `tests/fixtures/` holds a tiny
KiCad project in two versions, and the tests build a throwaway git repo from
it (`make_fixture_repo` in `tests/cpp/helpers.cpp`, `gui/tests/fixture_repo.py`) (four commits, including a folder rename). The
expected nets in the schematic tests are KiCad's own netlist for those files.

- `tests/cpp/`: parser, board, PCB diff, schematic nets, schematic diff, git
  integration, and the `kigit` binary end to end.
- `gui/tests/`: the GUI with NiceGUI's simulated user.
- Optional check against real projects: kigit's nets must match `kicad-cli`
  exactly. Skipped unless you list projects:

  ```sh
  KIGIT_REGRESSION_PROJECTS="~/boards/a/a.kicad_pcb:~/boards/b/b.kicad_pcb" ctest -L regression -V
  ```

## Layout

```
src/sexpr.*    S-expression parser (KiCad's file syntax)
src/board.*    .kicad_pcb -> tracks, arcs, vias, pads, zones, outline
src/git.*      git show / rev-parse wrapper
src/diff.*     per-net matching and stats
src/html.*     JSON payload + viewer template
src/schematic.*         .kicad_sch -> sheets, parts, wires, labels, nets
src/sch_diff.*          schematic diff (parts, nets, wires, labels)
tests/                  C++ tests, fixtures, fixture-repo script, regression check
gui/tests/              GUI tests
resources/viewer.html   page shell + styles; pcb.js, sch.js, shell.js are
                        combined into it at build time (one HTML file)
```

## Limitations

- Custom-shaped pads are drawn as their anchor rectangle.
- Footprint graphics (silkscreen, courtyards) and text aren't drawn.
- Old KiCad 5 boards (`module`, numeric nets) are parsed but less tested.
