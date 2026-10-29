# Introduction

## What is kigit?

kigit is a visual diff for KiCad projects kept in git. Text diffs of `.kicad_pcb` and `.kicad_sch` files are thousands of lines of coordinates; kigit turns them into a picture of the board and schematic where every change is coloured, so you can review a layout change the way you'd review code.

It is a single command-line program (C++) plus an optional GUI. It runs on Windows and Linux.

## Core concepts

### Two revisions

Every comparison is between an **old** and a **new** revision: two commits, a commit and your uncommitted changes (`LOCAL`), or two folders when there's no git at all. "Added" always means added in the newer one.

### Matching

kigit matches items between the two revisions before colouring anything:

- **PCB:** tracks, arcs, vias and pads are matched first by KiCad's internal ID, then by geometry (same kind, net, layers and coordinates to 1 nm). An item with the same ID and the same copper at a new place is **moved**, not removed and re-added, so moving a footprint doesn't light up the whole board.
- **Schematic:** parts are matched by KiCad ID (then reference), so re-annotating shows as a rename. Nets are paired by label name, else by shared pins.

### Kinds of change

Schematic changes are split into **electrical** (a part added or removed, a value, footprint or symbol changed, a pin moved to another net), **fields only** (BOM fields like MPN, or the reference) and **cosmetic** (parts moved, wires redrawn, labels moved, with the same connections).

### One HTML file

The result is one self-contained HTML page with the PCB and schematic as tabs. It needs no server: open it, keep it, or attach it to a pull request.

## Limitations

- Custom-shaped pads are drawn as their anchor rectangle.
- Footprint graphics (courtyards, fab) aren't drawn; silkscreen is optional.
- Zones (copper pours) are drawn from the newer revision only and aren't diffed, because refilling a pour changes its shape every time.
- Old KiCad 5 boards are parsed but less tested.
- macOS isn't supported for now.
