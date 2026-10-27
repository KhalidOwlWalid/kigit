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

## How matching works

Items are matched by kind, net, layer and geometry (rounded to 1 nm). An item
that exists in both revisions is "unchanged"; anything else is "added" or
"removed". Moving a footprint therefore shows its pads as removed + added,
and changing a track's width shows it as replaced.

Zones (copper pours) are drawn from the newer revision only and aren't
diffed, because refilling a pour changes its shape every time.

## Layout

```
src/sexpr.*    S-expression parser (KiCad's file syntax)
src/board.*    .kicad_pcb -> tracks, arcs, vias, pads, zones, outline
src/git.*      git show / rev-parse wrapper
src/diff.*     per-net matching and stats
src/html.*     JSON payload + viewer template
resources/viewer.html   the interactive page (embedded at build time)
```

## Limitations

- Custom-shaped pads are drawn as their anchor rectangle.
- Footprint graphics (silkscreen, courtyards) and text aren't drawn.
- Old KiCad 5 boards (`module`, numeric nets) are parsed but less tested.
