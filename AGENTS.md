# AGENTS.md

Notes for anyone (human or AI agent) working on kigit: what it is, how the
code is laid out, how to build and test it, and the rules this project
follows. Keep this file up to date when any of that changes.

## What kigit is

A KiCad + git diff tool: a better [KiRI](https://github.com/leoheck/kiri).
Given two revisions of a KiCad project (two git commits, the working tree,
or two folders on disk), it writes one self-contained HTML page with:

- **PCB tab**: every track, arc, via, pad, zone and footprint matched between
  the two revisions. Hover a trace to light up its whole net and see what was
  added, removed or changed, and how its copper length changed. Silkscreen
  is opt-in.
- **Schematic tab**: every sheet drawn, with parts, wires, labels and buses.
  Nets are computed the way KiCad's netlist computes them. Hover a net, part
  or bus to see what changed; click to pin a card with the details.

Pieces:

- **`kigit`**: a C++20 command-line program (CMake). It does all the work:
  reads files out of git, parses, diffs, writes the HTML or JSON.
- **`kigit gui`**: a Python [NiceGUI](https://nicegui.io) app in `gui/`. It
  only drives the `kigit` command line (no bindings, no shared code). It's
  started through [uv](https://docs.astral.sh/uv/).

## Rules

- **Don't commit or push** unless the user asks. The user commits themselves.
  When asked to commit, branch first if on `main`.
- **Always stay Windows-compatible.** CMake detects the OS and compiler by
  itself. Everything OS-specific goes in `src/utils/platform.cpp` (behind
  `include/utils/platform.hpp`), nowhere else. Never run commands through a
  shell to talk to git: use `platform::run(args)` (argv, no shell). cmd.exe
  mangles things like `%x1e%`.
- **Keep stdout clean** when output is `-o -`: only the data goes to stdout.
  Messages go to stderr and the log.
- **Keep the tests passing** (`ctest`). Add a test with each feature or fix.
- **No premature optimization.** Simple and correct first.
- **Silkscreen stays off by default**, both `--silkscreen` and the GUI's
  "Include silkscreen" checkbox.
- **Schematic nets must match KiCad's netlist exactly**: names and members.
  Check against `kicad-cli sch export netlist` (`--check-netlist`, or the
  regression test) when touching `src/sch/schematic.cpp`.
- **Write plain, short comments and messages.** Say what something is or why
  it's there, not a story.

## Layout

`include/<dir>/x.hpp` mirrors `src/<dir>/x.cpp`. Includes are path-qualified:
`#include "utils/platform.hpp"`.

| Folder | What's in it |
|---|---|
| `utils/` | `platform` (processes, paths, browser, env, app-data dirs: all OS code), `log` (spdlog session logs), `sexpr` (S-expression parser for KiCad files) |
| `git/` | `git` (log, show, resolve revisions, changed files), `locate` (find a board that moved or was renamed in history; skipped folders like `.history`) |
| `pcb/` | `board` (load `.kicad_pcb`: items, footprints, zones, silkscreen), `diff` (PCB diff) |
| `sch/` | `schematic` (load `.kicad_sch` hierarchy, compute nets and buses), `sch_diff` (schematic diff), `netcheck` (compare with a KiCad netlist) |
| `report/` | `html` (JSON for the viewer and `--json`; embeds the viewer), `viewer_template.hpp.in` |
| `commands/` | the CLI: `options` (parsing, `--help`), `common` (shared helpers: board paths, warnings, output paths, `git_board`), `summary` (terminal summary), `diff` (compare, also `--check-netlist`), `history` (`--log`), `projects` (`--projects`), `gui` (`kigit gui`) |
| `src/main.cpp` | starts the session log, then runs the command |

Everything except `commands/` and `main.cpp` builds into the `kigit_core`
static library, which the tests link against. `commands/` is part of the
`kigit` executable only (namespace `kigit::cmd`).

Other folders:

- `resources/`: the viewer: `viewer.html` (page and CSS), `shell.js` (tabs),
  `pcb.js`, `sch.js`. CMake combines them into one page and embeds it in the
  binary as a byte array. MSVC limits string literal length, hence bytes.
- `gui/kigit_gui/`: `app.py` (the UI), `kigit.py` (runs the CLI with
  `asyncio.to_thread(subprocess.run)`), `logs.py`, `folder_picker.py`.
- `tests/`: `cpp/` (doctest), `fixtures/` (demo v1/v2, hier, bus projects),
  `regression.sh`.
- `gui/tests/`: pytest with NiceGUI's simulated `user` fixture.
- `packaging/windows/kigit.iss`: Windows installer (Inno Setup).
- `.github/workflows/`: `ci.yml` (build and test on Windows and Linux on
  every push), `release.yml` (Windows release on a `v*` tag).

## Build and test

```sh
cmake -S . -B build
cmake --build build -j
ctest --test-dir build            # everything that can run here
ctest --test-dir build -L unit    # C++ only
ctest --test-dir build -L gui     # GUI (needs uv)
```

- C++20, CMake 3.16+ (tested up to 4.x). nlohmann_json and spdlog are taken
  from the system if present, else downloaded (FetchContent). doctest is
  always downloaded.
- `CMAKE_POLICY_VERSION_MINIMUM` is set to 3.5 so CMake 4 accepts doctest,
  which declares an older CMake. The remaining "Compatibility with CMake <
  3.10" notice from doctest is harmless.
- One ctest entry per doctest `TEST_CASE`, plus `gui` and `regression`.
- `regression` (Unix only) compares nets with `kicad-cli` on real projects.
  It's skipped unless `KIGIT_REGRESSION_PROJECTS="a.kicad_pcb:b.kicad_pcb"`
  is set and kicad-cli is installed.
- CLI tests run the real binary (`KIGIT_BIN`). The fixture git repo is built
  in C++ (`tests/cpp/helpers.cpp`, `make_fixture_repo`) and again in Python
  (`gui/tests/fixture_repo.py`). Keep the two the same.
- Windows: MSVC gets `/utf-8 /permissive- /EHsc /bigobj` and a static
  runtime. MinGW links `-static`.

Useful real projects for manual checks (on the user's machine):
`~/Documents/Kicad/owl/owl_v1` (74 nets), `~/Documents/Kicad/learn/CM5-SODIMM-Carrier`
(308), `~/Documents/Kicad/learn/CM5_MINIMA_REV2` (211, buses),
`~/Documents/Kicad/learn/jetson-nano-baseboard`. kigit matches KiCad on all of them.

## CLI at a glance

```
kigit [OPTIONS] [OLD..NEW | OLD NEW | REV] [BOARD.kicad_pcb]
kigit --files OLD.kicad_pcb NEW.kicad_pcb     # no git
kigit gui [PROJECT_DIR]
```

- No revisions means HEAD vs `LOCAL` (the working tree). If OLD is newer than
  NEW they're swapped (`--no-swap` to keep the order).
- `-C/--kicad-repo DIR`, `-o FILE` (`-` = stdout), `-n` no browser, `-s` all
  stats, `--json`, `--silkscreen`, `-q`, `-V/--verbose` (not `-v`, which is
  `--version`).
- Used by the GUI: `--log` (history JSON; `--max`, `--since`, `--until`
  where a bare date means the whole day, `--kicad-only`), `--projects`
  (`--depth`).
- `--check-netlist FILE`: compare kigit's nets with a KiCad netlist.
- Logging: every run writes a session log
  (`kigit_<date>_<time>_<pid>.log`) in `$KIGIT_LOG_DIR` or the app data
  folder (`%LOCALAPPDATA%`, `~/Library/Application Support`, or
  `$XDG_STATE_HOME`/`~/.local/state`, then `kigit/log`). Flags:
  `--log-dir`, `--log-file` (append; the GUI uses this so a GUI session and
  its kigit calls share one file, and kigit then logs `run:`/`done:` instead
  of session start/end), `--log-stderr`, `--no-log`. Pattern:
  `[%Y-%m-%d %H:%M:%S.%e] [%n] [%l] %v`.
- Pages go to `<board folder>/.kigit/` (with its own `.gitignore`), not
  `~/.cache`: snap browsers can't read hidden folders in `$HOME`.

## How it works

### PCB (`src/pcb/`)

- Pad positions are stored footprint-local in the file. Pad and text angles
  are absolute.
- Items are matched by KiCad ID (`uuid`/`tstamp`) first, then by geometry.
- PCB status enum: `Same=0, Added=1, Removed=2, Moved=3, OldPosition=4,
  Changed=5`. These are the `s` field in the viewer JSON.
- `FootprintDiff`: pads, graphics, fields, moved. `ZoneDiff`: `Added`,
  `Removed`, `OutlineChanged`, `Refilled` (a refill alone is routine).
- If the board isn't at the same path in a revision (moved or renamed),
  `locate` finds the board there most like the latest one and warns with a
  match score.

### Schematic nets (`src/sch/schematic.cpp`), following KiCad's netlist rules

- Wires connect at endpoints and junctions; wires that merely cross don't.
  A label touching a wire mid-way joins it.
- Labels: local (per sheet), global, hierarchical, joined to sheet pins in
  the parent.
- `power_in` pins that are hidden, or on power symbols, make global nets.
  `PWR_FLAG` is `power_out` and joins nothing.
- Unnamed nets: `Net-(U1-IN)` (ref and pin name, else pad number). Single-pin
  nets: `unconnected-(R3-Pad1)`, or `unconnected-(U1-A{slash}B-Pad3)` when the
  pin has a name.
  `/` in names is escaped as `{slash}`. The `/root/` sheet prefix is only used
  when there are several top-level sheets.
- Parts with `(on_board no)` are left out of nets.
- **Buses** live in a separate disjoint-set: buses and wires never connect.
  - Vector buses `D[0..7]` pair members by index.
  - Groups `{A B}` and named groups `NAME{ALIAS}` (with `bus_alias`) pair
    members by short name.
  - Each member is a node `B:sheet:graph:key`, joined to the `L:`/`G:`/`HB:`
    nodes for its label kind.
  - Bus labels have `net = -1`. `SchBusGroup` holds a bus's names and the
    net each member ends up on. Bus segments and bus labels carry `group`.
- Schematic diff (`sch_diff`): `SchStatus { Same, Added, Removed, Changed }`;
  `SymbolDiff` (fields, pins on another net, moved; `electrical()`,
  `fields_only()`), `NetDiff` (joined/left pins, renamed, `merged_into`,
  wiring redrawn only).

### Viewer data (`src/report/html.cpp` to `resources/*.js`)

- PCB: items with `s` (0-5), `footprints`, `zone_changes`, `silk` (null
  unless loaded). Pads carry `fp`, their footprint's index.
- Schematic view status codes:
  `0 same, 1 added, 2 removed, 3 changed, 4 fields changed, 5 moved, 6 old
  position (ghost)`.
- Per sheet: `wires [x1,y1,x2,y2,st,net]`,
  `labels [kind,text,x,y,angle,size,shape,st,net,group]`, `symbols`, `boxes`,
  `texts`, `drawings`, `buses [x1,y1,x2,y2,st,group]`, `entries`.
- Top level: `nets`, `parts`, `defs`, `busGroups [{names, members:[[full, net]]}]`.
  Net indices point into `nets` (the net diff list).
- `sch.js`: `targetOf(el)` gives `{kind: "n"|"p"|"g", id}` (net, part,
  bus); `elsFor(t)` is what lights up; `info`/`renderCard` build the tooltip
  and the pinned card (tables `.kv` and `.diff`).

### GUI (`gui/`)

- Browse a folder; projects are detected up to 2 levels down. The commit
  list starts with the working tree, has filters (limit, dates, KiCad-only)
  and a manual revision entry. "Compare folders" works without git.
  There's a log viewer and an "Include silkscreen" checkbox.
- Dialogs are created inside `dialog_host`.
- Ctrl+C: `timeout_graceful_shutdown=2` plus a force-exit watchdog
  (uvicorn otherwise waits for open websockets). On Windows, `kigit.exe`
  waits for the GUI with a `CreateProcessW` wait and a non-inherited
  `SetConsoleCtrlHandler`.
- Tests: NiceGUI's harness fails a test on any error-level log, so
  user-facing failures are logged as warnings. Wait for a button to be
  enabled, or the iframe `src` to change, instead of sleeping.
- `kigit gui` looks for the app in `$KIGIT_GUI_DIR`, `<exe>/../gui` (build
  folder) or `<exe>/../share/kigit/gui` (installed), and for `uv` next to
  the exe, then in `<exe>/../libexec/kigit`, then on PATH. The installed copy keeps its Python environment in
  `<app data>/kigit/gui-env` and runs `--no-dev --frozen` (from `uv.lock`).

## Releases (Windows)

1. Set `project(kigit VERSION x.y.z)` in `CMakeLists.txt` and commit.
2. `git tag vx.y.z && git push origin vx.y.z`.

`release.yml` has three jobs:

- **windows** (`windows-latest`): build with `-DKIGIT_PORTABLE=ON`, test,
  stage `cmake --install` output plus `uv.exe` in `bin`, then build
  `kigit-x.y.z-windows-x64.zip` and `kigit-x.y.z-setup.exe` (Inno Setup via
  choco) and test-install silently.
- **linux** (`ubuntu-22.04`, for an old enough glibc): build with
  `-DKIGIT_PORTABLE=ON`, test, then package
  `kigit-x.y.z-linux-x86_64.tar.gz` (`bin/kigit`, `share/kigit/gui`,
  `libexec/kigit/uv`), unpack it and check it runs and links only glibc.
- **publish** (tags only, after both pass): one GitHub Release with all
  files.

The tag must match the CMake version or the job fails. "Run workflow" by
hand builds the files as artifacts without releasing. Published tags don't
move: a fix gets a new version.

`KIGIT_PORTABLE=ON` downloads nlohmann_json and spdlog instead of using the
system's copies, and on Linux links libstdc++/libgcc statically, so the
binary only needs glibc. `kigit gui` looks for uv next to the exe, then in
`<prefix>/libexec/kigit/uv`, then on PATH.

The installer is per-user (no admin): `%LOCALAPPDATA%\Programs\kigit`,
`bin` added to the user PATH, a Start menu entry running `kigit gui`, and a
warning if git isn't installed.

Known gaps: the exe isn't code-signed (SmartScreen warning), the repo has
no LICENSE file yet, and the first GUI start needs internet (uv downloads
Python and NiceGUI).

## Status and open work

Not verified yet: CI and the release workflow have never run on GitHub, so
the Windows build is untested. macOS isn't built by CI for now (the
macOS code paths in `platform.cpp` stay, but nothing checks them).

Open work:

- Schematic to PCB cross-probing.
- A net filter on the schematic tab.
- Fab and courtyard layers.
- Pour outlines.
- Developer mode (see `TODO.md`).
- Linux packages; macOS support (CI and packages) if it's wanted again.
