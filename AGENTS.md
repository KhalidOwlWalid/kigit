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
- **Silkscreen and source stay off by default**: `--silkscreen` / `--source`
  and the GUI's "Include silkscreen" / "Include source" checkboxes.
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
| `net/` | `http` (HTTPS through the `curl` program: `curl -K -` with the whole request, URL included, on stdin; `Http` is a function so tests pass a stand-in) |
| `parts/` | part lookups: `offer` (`Offer`, `cost_at`, `parse_price`), `source` (`Source`: a site; `send` paces calls), `mouser` (Search API v1), `digikey` (Product Information v4, token, substitutes), `match` (pick or choices), `store` (keys, cache in the app folder), `lookup` (a BOM through the cache, JSON, table) |
| `sch/` | `schematic` (load `.kicad_sch` hierarchy, compute nets and buses), `sch_diff` (schematic diff), `netcheck` (compare with a KiCad netlist), `bom` (bill of materials: lines, part number fields, search queries and links) |
| `report/` | `html` (JSON for the viewer and `--json`; embeds the viewer), `viewer_template.hpp.in` |
| `commands/` | the CLI: `options` (parsing, `--help`), `common` (shared helpers: board paths, warnings, output paths, `git_board`), `summary` (terminal summary), `diff` (compare, also `--check-netlist`), `history` (`--log`, `--rewritten`), `board3d` (`--3d`), `example` (`kigit example`), `uninstall` (`kigit uninstall`), `bom` (`kigit bom`), `projects` (`--projects`), `gui` (`kigit gui`) |
| `src/main.cpp` | starts the session log, then runs the command |

Everything except `commands/` and `main.cpp` builds into the `kigit_core`
static library, which the tests link against. `commands/` is part of the
`kigit` executable only (namespace `kigit::cmd`).

Other folders:

- `resources/`: the viewer: `viewer.html` (page and CSS), `shell.js` (tabs),
  `source.js` (the source panel, shared by both tabs), `pcb.js`, `sch.js`. CMake combines them into one page and embeds it in the
  binary as a byte array. MSVC limits string literal length, hence bytes.
- `gui/kigit_gui/`: `app.py` (the UI), `kigit.py` (runs the CLI with
  `asyncio.to_thread(subprocess.run)`), `logs.py`, `folder_picker.py`,
  `review.py` (review file format), `review_panel.py` (the review drawer),
  `threads.py` + `discussions.py` (PR-style discussions),
  `rewritten.py` (reviews of rebased/amended/squashed commits),
  `buildtime.py` (3D build time estimates for the progress bar),
  `sessions.py` (recent projects for the landing page),
  `shortcuts.py` (every shortcut, for the header's list),
  `board3d.py` (the 3D view page), `board3d_diff.py` (the 3D diff, beta),
  `resize.py` (drag handles for the drawers), `panels.py` (hiding drawers
  to a rail), `md_editor.py` (the GitHub-style Markdown editor: Write /
  Preview, toolbar formatting done in page JS via `execCommand` so undo
  works, files by paste/drop/click to `/review-upload/{key}` ->
  `review.save_file` in reviews/assets/; `Editors` is one per page, used by
  the review panel and discussions).
- `submodules/`: the libraries (json, spdlog, doctest) as pinned git submodules.
- `tests/`: `cpp/` (doctest), `fixtures/` (demo v1/v2, hier, bus projects),
  `regression.sh`.
- `gui/tests/`: pytest with NiceGUI's simulated `user` fixture.
- `examples/blinky/`: the example project (`kigit example`, the landing
  page's "Try the example project"): `steps/<n>/` is the whole project at
  each commit, `history.json` the commits (step, folder, message, UTC
  date, author "Author A"; reviews and discussions by Author A/B/C) plus an
  uncommitted step. Generated by
  `tools/make_example.py` (don't edit by hand; KiCad 8 format, uuid5
  UUIDs, so it's reproducible); installed to `share/kigit/examples`.
  `src/commands/example.cpp` commits the steps in order with fixed
  author/dates and `core.autocrlf=false`, so the hashes are the same on
  every OS (pinned in the CLI test; `examples/** -text` in .gitattributes,
  and text files are committed with LF even from a CRLF copy); `{{commit:N}}`/`{{short:N}}` in .md
  files become the Nth commit's hash. After changing the generator: check
  the nets against KiCad (`kicad-cli sch export netlist` per step,
  `kigit --check-netlist`), then update the pinned hashes.
- `packaging/windows/kigit.iss`: Windows installer (Inno Setup).
- `packaging/icons/`: the logo (`kigit.svg`, `.png`, `.ico` at 16-256 px),
  made by `tools/make_logo.py` (Pillow; regenerate, don't edit). The .ico is
  compiled into kigit.exe on Windows (`packaging/windows/kigit.rc.in`,
  configured with the icon's absolute path by CMake) and is the installer's
  `SetupIconFile`.
- `kigit uninstall` (`src/commands/uninstall.cpp`): the install is
  `<prefix>/bin/kigit` with `<prefix>/share/kigit` beside it (anything else,
  like a build folder, is refused). Removes only `bin/kigit`, `share/kigit`,
  `libexec/kigit` (never the shared folders), asks unless `--yes`;
  `--purge` adds `<state dir>/kigit`. No session log (it may remove the
  folder). Windows: runs `<prefix>/unins000.exe` (Inno's), else tells you
  to delete the folder (a running .exe can't delete itself).
- `docs/` + `mkdocs.yml`: the docs site (MkDocs Material; published with
  `mkdocs gh-deploy`, `mkdocs build --strict` to check). GUI screenshots
  live in `docs/img/gui/` and are made by `tools/docs_screenshots.py`
  (Playwright + headless Chrome driving the real GUI on scratch clones of
  the projects given, with demo reviews; needs KiCad for the 3D shots):
  `uv run --no-project --with playwright --with pillow python
  tools/docs_screenshots.py --project <repo> --extra <repo>`, `--only` to
  redo some. Retake them when the GUI changes how something looks.
  `docs/app-folder.md` lists what's kept in `<app data>/kigit`; update it
  when something new is stored there, and link to it from the page that
  mentions it.
- `.github/workflows/`: `ci.yml` (build and test on Windows and Linux on
  every push), `release.yml` (Windows release on a `v*` tag).

## Build and test

```sh
git submodule update --init       # once, after cloning
cmake -S . -B build
cmake --build build -j
ctest --test-dir build            # everything that can run here
ctest --test-dir build -L unit    # C++ only
ctest --test-dir build -L gui     # GUI (needs uv)
```

- C++20, CMake 3.16+ (tested up to 4.x).
- Libraries are git submodules in `submodules/`, each pinned to a release
  tag: `json` (nlohmann_json v3.11.3), `spdlog` (v1.14.1), `doctest`
  (v2.4.11, tests only). They're built in with `add_subdirectory`; nothing is
  taken from the system or downloaded at configure time. CMake stops with a
  hint if one is missing. They're shallow (`shallow = true` in
  `.gitmodules`). To update one:
  `git -C submodules/spdlog fetch --depth 1 origin tag vX.Y.Z && git -C submodules/spdlog checkout vX.Y.Z`,
  then commit the new submodule commit. CI checks out with `submodules: true`.
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
`~/Documents/Kicad/owl/OwlKit/owl_v1.kicad_pcb` (74 nets),
`~/Documents/Kicad/learn/CM5-SODIMM-Carrier/PCB/carrier.kicad_pcb` (308),
`~/Documents/Kicad/learn/CM5_MINIMA_REV2` (211, buses),
`~/Documents/Kicad/learn/hackrf/hardware/hackrf-one` (379; KiCad 6 files,
a sheet named `mcu/usb/power`), `~/Documents/Kicad/learn/jetson-nano-baseboard`.
kigit matches KiCad 10.0.7 on all but Jetson, where 49 of 487 nets have the
right pins but another name (multi-unit parts: KiCad 10 writes
`Net-(J15B-...)` with the unit letter; and `unconnected-(D8-Pad5)`).
When checking by hand, use kicad-cli's default netlist format:
`--format kicadxml` unescapes names (`{slash}` shows as `/`).

## CLI at a glance

```
kigit [OPTIONS] [OLD..NEW | OLD NEW | REV] [BOARD.kicad_pcb]
kigit --files OLD.kicad_pcb NEW.kicad_pcb     # no git
kigit gui [PROJECT_DIR] [--port N]
```

`kigit gui` passes its arguments on to the Python app. Port (`pick_port` in
`app.py`): `--port N` if free, else exit with a message; without it 8765 or
the next free one (up to 50 more), printed on stderr, so several GUIs can run
at once. localStorage settings are per origin, so per port.

- No revisions means HEAD vs `LOCAL` (the working tree). If OLD is newer than
  NEW they're swapped (`--no-swap` to keep the order).
- `-C/--kicad-repo DIR`, `-o FILE` (`-` = stdout), `-n` no browser, `-s` all
  stats, `--json`, `--silkscreen`, `--source`, `-q`, `-V/--verbose` (not `-v`, which is
  `--version`).
- `--rewritten HASH...` (GUI): JSON per hash: `live` (reachable from a
  branch, tag or HEAD: `git log --all`), `exists`, and `matches`: live
  commits with the same author email and author time (`git::rewritten`);
  times are in seconds, so if several match, those with the old subject win.
- `--3d [REV] [-o FILE.glb]` (GUI's 3D view): one revision (default
  LOCAL) as binary glTF, made by `kicad-cli pcb export glb` with tracks,
  pads, zones, silkscreen and mask. For a commit, the board (found by
  `find_similar_board` if it moved), its `.kicad_pro` and every 3D model file
  in the repo (`.step`, `.wrl`, ...) are written to a temp folder in the repo's
  layout, so `${KIPRJMOD}` paths resolve; LOCAL uses the file on disk.
  `platform::find_kicad_cli()`: `$KIGIT_KICAD_CLI`, PATH, then the install
  folders. Prints the output path on stdout. The working tree is copied
  too (read from disk). `modernize_model_paths` (in `pcb/board`) points
  `${KICADn_3DMODEL_DIR}` library models at the running KiCad's version
  (`kicad-cli version`), and `.wrl`/`.wrz` at `.step` from KiCad 10 on:
  kicad-cli doesn't define older versions' variables, KiCad 10's library has
  only STEP, and `--subst-models` doesn't help when the .wrl is missing.
  "Could not add 3D model" lines are counted into one warning.
  `--3d --disk BOARD` (no git; Compare folders): `checkout_disk` copies the
  board (model paths modernized), its .kicad_pro and the model files in
  its folder (not hidden or `_restore_backup*` folders) into a scratch
  folder in the same layout. The GUI gives such boards as revisions
  `disk:<board path>` (`kigit.DISK`): `short_rev` names them by folder,
  `board3d_name` keys them by the file's time and size, and
  `run_files_diff` sets `state["pair"]` to them (`files_pair`).
  KiCad versions (`kicad_major`, from `kicad-cli version`): 9+ get
  `--include-pads/-silkscreen/-soldermask`; 8 doesn't have them (glb with
  tracks and zones only, plus a warning); an unknown version that turns
  them down ("Unknown argument", `unknown_option`) is retried without
  them; 7 and older are refused (no glb). `check_readable` stops early with
  a clear message when the board's `(version N)` is newer than that KiCad
  reads (8: 20240108, 7: 20221018). `--render` has no `pcb render` before
  9: it writes a 2D `pcb export svg` (top layers, board-sized) next to -o
  as `.svg` and prints that path; the GUI keeps `thumbnails/<key>.png` or
  `.svg` (`sessions.thumb`), served by `/session-thumb/{name}`. Tested with
  a stand-in kicad-cli (test_cli). Windows picks the newest KiCad folder
  by number, not name.
- Used by the GUI: `--log` (history JSON; `--max`, `--since`, `--until`
  where a bare date means the whole day, `--kicad-only`; each commit has its
  first `parent`, the real one even when filtered), `--projects`
  (`--depth`).
- `--check-netlist FILE`: compare kigit's nets with a KiCad netlist.
- `kigit bom --write EDITS.json` (`sch/fields`, `write_fields` in
  commands/bom.cpp): **kigit only writes part information fields, never the
  design** (the user's rule). `field_refused` refuses KiCad's own fields
  (Reference, Value, Footprint, Datasheet, Description, sheet fields, ki_*,
  Sim.*). `set_fields` edits text in place: a value replaced at its atom's
  offset (atoms are views into the text), or a new property copied from the
  symbol's own hidden field (Footprint, Datasheet, ...; KiCad 6 gets the
  next `(id N)`), inserted after its last property with its indent and the
  file's line endings. Every unit of a part (by ref, via the loaded
  schematic) gets it. Before writing: the edited text is loaded again and
  `same_design` must hold (sheets, symbols' ref/value/footprint/lib/unit/
  flags/position, fields other than the edited ones, nets, wires, labels,
  junctions, no-connects) and each field must read back as written;
  KiCad's lock `~<file>.lck` refuses unless `--force`. Then the old files
  go to `<schematic folder>/.kigit/bom-backup/<time>/` (with
  manifest.json: root, files) and each file is written via a temp file and
  rename. `--restore DIR` (only a `.kigit/bom-backup/` folder) puts them
  back. Prints JSON on stdout.
- `kigit bom --lookup [--boards N] [--site mouser,digikey] [--refresh]` (`parts/`):
  stock, price, lead time, lifecycle per line, only on request. HTTP is the
  `curl` program (`$KIGIT_CURL`, else PATH; on Windows 10+ too) via
  `platform::run_input`: the request goes as a curl config on stdin, so keys
  never reach argv; error text is `redact`ed and keys aren't logged. Keys:
  `$KIGIT_<SITE>_API_KEY`, else `<app data>/kigit/parts-keys.json` (owner
  only), set by `--set-key SITE` from stdin. Cache: `parts-cache.json`,
  keyed `site|pn|NORMPN` or `site|kw|words`, used 24 h, dropped after 7 days
  (both in the folder above `$KIGIT_LOG_DIR` when that's set); `--keys`
  prints which sites have a key;
  errors aren't cached. Matching (`parts/match`): the line's site number,
  else its MPN, gets only that exact part (`norm_pn`), best ranked first; a
  line without one gets up to 5 ranked `choose` candidates and no pick (never
  guess a part). Need = qty x boards; `cost_at` honours min, mult and price
  breaks. Mouser: 30 calls/min, 1000/day, so 2.1 s between calls
  (`KIGIT_LOOKUP_PACE_MS`, 0 in tests); a refused key, the limit or no
  network is `fatal` and skips the site's remaining lines. Line `key` is
  the GUI's `bom.line_key`. Tests: `test_parts` (stand-in Http), and
  test_cli with a stand-in curl script (Unix). LCSC and RS have no
  public API. Sites are `Source`s (`site()`, `part_number`, `keyword`,
  `substitutes` + `has_substitutes`); `lookup` takes a map site ->
  Source and a map of why the others are missing; `--site` defaults to
  every site with a key (`has_key`), else all (to say how to get one).
  Digi-Key: token from `POST /v1/oauth2/token` (form, client
  credentials; kept in memory until `expires_in` - 30 s, a 401 gets a new
  one once), then `POST /products/v4/search/keyword` {Keywords, Limit,
  Offset} for numbers and words alike (ExactMatches first) with
  `X-DIGIKEY-Client-Id` and `X-DIGIKEY-Locale-Site/-Language/-Currency`.
  One Offer per ProductVariation (`package`; Digi-Reel skipped: cut tape
  plus a fee; Tape & Reel's `mult` = its minimum, a whole reel). A pick
  that's short or `winding_down` gets `GET .../{DigiKey number}/
  substitutions` (cached `digikey|sub|...`, 404 = none) as the match's
  `alternatives` (`note` = SubstituteType). Login in `parts-keys.json`
  as {"digikey": {client_id, client_secret, site, currency}};
  `--set-key digikey` reads ID, secret, optional "SITE CURRENCY" lines.
  Pace 600 ms (about 120 a minute). Checked against the real token
  endpoint (a fake ID gets "client_id form parameter has incorrect
  value"); not yet against a real reply.
- `kigit bom [REV] [PATH] [--json | --csv] [-o FILE]` (`commands/bom.cpp`,
  `sch/bom`): a subcommand with its own options (like `uninstall`), run
  from `run()` in main.cpp so it's logged. Default the working tree, read
  from disk (works outside git); REV reads git. PATH: .kicad_sch, .kicad_pro,
  .kicad_pcb or a folder (its board's schematic, else its only .kicad_pro's).
  Lines: same value, footprint, MPN, manufacturer, Digi-Key, Mouser, LCSC
  and DNP; skips power, `#` refs, `in_bom no` / `exclude_from_bom yes`;
  multi-unit parts once (by ref). Part numbers by normalised field name
  (`key_of`: lower case, letters and digits only; `kMpn`, `kLcsc`, ...).
  DNP: the flag, a `DNP` field, or value "DNP" (KiCad 6). `query`: the MPN,
  else for passives the value (`ohms()`: 10kR -> 10k, 5k1 -> 5.1k) +
  package (0402.., from the footprint name after `_` or `-`) + a word;
  `search_url` per site prefers that site's own number.
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
  the parent. A local label also joins a global label of the same name on
  the same sheet (not on other sheets).
- Sheets: `Sheetname`/`Sheetfile`, or KiCad 6's `Sheet name`/`Sheet file`.
  A `/` in a sheet name is `{slash}` in net names.
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

### Source panel (`--source`)

- The parser records each list's byte span (`sexpr::Node::span`, `Span`
  in `utils/sexpr.hpp`). Items, pads, footprints and zones keep theirs
  (`src`); a zone's stops before its first `filled_polygon` (`src_cut`).
  Schematic symbols, wires, labels, sheet pins and buses keep theirs, and
  `Schematic::files` holds every sheet file's text.
- `report/source.*`: `SourceFile` turns a span into whole lines plus the
  first line number; `SourceTable` collects entries
  `{k: label, o: [file, line, text] | null, n: [...] | null, cut?}` with one
  entry per old/new pair. `DiffItem::other` pairs a moved/changed item with
  its old self.
- JSON: PCB `src` (entries) plus `src` on items, footprints and
  zone_changes. Schematic `sch.src`, with the entry appended to rows:
  `wires[6]`, `labels[10]`, `buses[6]`, and `src` on symbols and parts.
  Without `--source` none of this is in the page.
- A removed and an added label with the same kind, name and sheet are paired
  into one entry (a moved label).
- `resources/source.js` (`kigitSourcePanel.create(view, entries, key)`):
  LCS line diff, side-by-side rows, changed characters marked, unchanged runs
  folded beyond 3 lines of context, 25 entries then "show more". Its height
  and open state are remembered in localStorage. `pcb.js`
  (`showNetSource`, `showFootprintSource`) and `sch.js` (`showSource`) call
  `show(list, heading, focus)` on hover and pin; `data-s` on schematic
  elements gives the hovered element's own entry.

### GUI (`gui/`)

- Browse a folder; projects are detected up to 2 levels down. The commit
  list starts with the working tree, has filters (limit, dates, KiCad-only)
  and a manual revision entry. "Compare folders" works without git.
  There's a log viewer and "Include silkscreen" / "Include source" checkboxes.
- Dialogs are created inside `dialog_host`.
- Hiding and new tabs, per panel (every panel has both; keep it that way):
  commit list and review panel: `panels.Panels` makes the drawer Quasar's
  `mini` (a `RAIL_WIDTH` rail with `q-mini-drawer-only` contents; the normal
  contents and the resize grip are `q-mini-drawer-hide`), remembered as
  `kigit.hidden.<key>` in localStorage (restored with
  `kigit_panel_hidden`); opening a review un-hides its panel. New tab:
  `/?folder=..&board=..` (`index()` takes them) and the Reviews page at
  `#r-<id>` (written reviews only). Viewer sidebar (`shell.js`): « hides it
  to a rail (`#app.aside-hidden`, `kigit.asideHidden`), ↗ (only when framed)
  by the board's name and on the rail. 3D pages: "New tab" when framed
  straight by the GUI (`/board3d` not in a grid cell, `/board3d-grid`), not
  in the dock (`dock_load` adds `&dock=1`; its bar has pop-out). The dock
  folds to its bar (`set_dock_folded`, class `folded` on the split, the
  iframe stays loaded).
- "Wrap messages" adds `kigit-wrap` to the commit table (CSS in `build()`):
  the message cell wraps and takes the remaining width, and the date column
  is dropped (`.kigit-date` shows it under the hash). Remembered in
  localStorage (`kigit.wrapMessages`).
- Panels resize by dragging their inner edge (double-click resets), and the
  width is remembered in localStorage. GUI drawers: `Resizer.add()` in
  `resize.py`; the drag sets the width in the page and sends it to the server
  when the drag ends (`kigit_panel_width`). A drawer stops where less than
  400 px would be left for the viewer. Viewer sidebar: `shell.js` sets
  `--aside-w`; no handle in the narrow (< 760 px) layout. The source panel's
  height was already adjustable.
- Window: the browser by default everywhere (Windows too, since the user
  asked); `--native` opens a pywebview window (`ui.run(native=True)`),
  `--browser` is the default spelled out. `choose_window()`
  decides, and `native_problem()` probes pywebview in a separate Python
  first, because NiceGUI exits, or shuts the server down, if the window
  can't open. Any problem means fall back to the browser with a warning.
  pywebview is a Windows-only dependency in `pyproject.toml`. The server
  always binds `127.0.0.1`.
- `kigit gui` starts the app as `python -m kigit_gui` (not the `kigit-gui`
  script), so the native window's child process can re-import it by module
  name on Windows. `main()` returns early outside the main process.
- Ctrl+C: `timeout_graceful_shutdown=2` plus a force-exit watchdog
  (uvicorn otherwise waits for open websockets). On Windows, `kigit.exe`
  waits for the GUI with a `CreateProcessW` wait and a non-inherited
  `SetConsoleCtrlHandler`.
- Python: `requires-python = ">=3.10,<3.14"`: NiceGUI's vbuild calls
  `pkgutil.find_loader`, gone in 3.14 (CI's uv picked 3.14 and the GUI
  tests died on import). Lift it when NiceGUI drops vbuild.
- Always pass `encoding="utf-8"` to `read_text`/`write_text`/`open`, in
  tests too: Windows defaults to cp1252 and mangles `·`, `→` and the like
  (CI failed on a notebook log line that way).
- Tests: NiceGUI's harness fails a test on any error-level log, so
  user-facing failures are logged as warnings. Wait for a button to be
  enabled, or the iframe `src` to change, instead of sleeping.
- 3D view (`board3d.py`): the 3D button (one to `MAX_3D` = 4 rows; the table
  keeps the last 4 picked, Compare needs 2, Review 1; the working tree too)
  runs `kigit --3d` into `CACHE` (`board3d_name`: a commit's file is reused
  for the session; LOCAL is keyed by the board's mtime and size) and points
  the viewer iframe at `/board3d/{name}`: a standalone three.js page using
  NiceGUI's bundled three (r168), served from `/kigit-three/` (only the
  files in `THREE_FILES`), with GLTFLoader and OrbitControls via an
  importmap. glTF is Y-up in metres with KiCad's Y along +Z, so Top looks
  down -Y with -Z up. Parts are the model's top-level nodes named by
  reference (the board's own meshes are named `=>[...]`). Lighting: a small
  PMREM room as the environment plus a light above and below. KiCad writes
  material colours as sRGB values in glTF's linear slots, so the page runs
  `convertSRGBToLinear()` on each material once (else the mask is pale
  mint); Neutral tone mapping. Tuned against `kicad-cli pcb render` of the
  CM5 board by measuring median mask and pad colours: environment
  intensity 0.3 (more mirrors the bright "ceiling" into the mask and washes
  it out seen from above), mask opacity 0.8 (KiCad exports 0.83; a bit less
  shows the traces), and KiCad's pure-metal copper made half metal (0.55,
  roughness <= 0.35) so pads are gold, not a dull reflection of the room.
  Parts (no metallic factor in the file, so 1 by glTF's default) get the
  same. KiCad's own 3D viewer does nothing more for traces (mask at its
  colour's alpha over copper, shiny specular; see
  `render_3d_opengl.cpp`), so traces under mask on poured boards are faint
  there too; like KiCad, the page lets you hide layers: the board group's
  merged meshes with a see-through dark material are the mask, see-through
  light ones the silkscreen (`layers`, `setLayer`; M, K, P). A layer change
  is posted as `{kigit3d: "layer"}` and the grid relays it as `setLayer`
  while linked. Silkscreen: KiCad exports it see-through (0.9) almost in
  the mask's plane, so the draw order of the two flipped with the angle
  and the mask covered it at low angles. It's made solid, a little
  emissive (0.35 of its colour), with polygon offset in front of the mask
  (silk -2/-4, mask -1/-2; KiCad uses -4 and -2). It draws on
  demand (`redraw()`: on controls `change`, while damping still moves, on
  resize and view changes), not every frame, and the static model's
  matrices are computed once; no hover raycasting (it lagged on big boards).
  `window.kigit3dReady` is set once loaded (for browser checks).
  The 3D dock: while a comparison shows, the header's 3D button (`dock_btn`)
  opens a panel beside it (`.kigit-split` flex row: `.kigit-main`, grip,
  `.kigit-dock`) or below it (class `below`, column). `state["pair"]` is the
  comparison (older first, by list order); `dock_side` New/Old/Both picks
  the board(s) (`board3d_src`, grid for both). Width/height are CSS
  variables `--kigit-dock-w`/`-h`, set by the grip's drag in page JS (the
  frames get `pointer-events: none` while dragging), remembered in
  localStorage (`kigit.dockWidth`/`Height`/`Below`). Unplaced, it goes below
  if the split is under 1100 px wide. `no_comparison()` (from
  `show_message`, a 3D-only view, folder compare) hides the button and
  closes the dock; `dock_close` blanks its iframe to free WebGL memory and
  bumps `dock_token` so a model still being made isn't shown. Names like
  HEAD~1 aren't reused by `board3d_name` (they can move).
  Pop-out: the dock's open_in_new button runs `window.kigitPopOut(src)` in
  its click (`js_handler`; window.open outside a click is blocked), which
  keeps `window.kigitPopout` and polls `.closed`; on close it emits
  `kigit_dock_back` unless `kigitPopoutQuiet` (kigit closed it). Popped
  (`set_popped`, class `popped` on the split): only the dock's header bar
  stays, under the comparison; the dock iframe is blanked and `dock_load`
  sends `state["dock_src"]` to the tab (`location.href`) instead.
  Progress: kicad-cli prints nothing while it exports (checked with a pty
  too), so `build_models` shows time against the board's last build
  (`buildtime`: `<app data>/kigit/3d-build-times.json`, per board path,
  averaged with the previous build, scaled by 1 + 0.25 per extra build at
  once; builds under 2 s aren't kept). First build: indeterminate bar.
  Shown under the main placeholder (`build-progress`) or in the dock.
  Several rows: their models are made at once (`asyncio.gather`) and the
  iframe shows `/board3d-grid?b=..&t=..&s=..` (oldest first): one
  `/board3d` iframe per board. Each board posts `{kigit3d: "camera"}` to its
  parent on controls `change`; the grid relays it as `setCamera` to the
  others while "Link views" is on; `applying` stops a received camera
  being sent back, and a board's first view isn't sent. kicad-cli writes a
  scratch `$tempfile$.bin.tmp` next to its output, so `--3d` exports into
  its own temp folder and moves the file into place (parallel exports into
  the GUI's one cache folder failed before).
  Render stats (`stats` in the page; `?stats=1` or S): only measured while
  shown. Input → drawn (first unanswered pointerdown/drag/wheel to the end
  of the next render), CPU per `renderer.render`, GPU via
  `EXT_disjoint_timer_query_webgl2` when available (one query in flight,
  polled every 500 ms), frame gaps while dragging or within 400 ms of
  input (> 25 ms counts as dropped), long tasks, `renderer.info` calls and
  triangles. `window.kigit3dStats()` returns the report. On CM5 KiCad's
  export gives ~37k meshes and draw calls for ~500k triangles: draw calls,
  not triangles, are the cost. So on load `mergeByMaterial` bakes every
  mesh into world space and merges them per material (`mergeGeometries`,
  position and normal only), once for the board's own meshes and once for
  the parts (one `parts` group, which the Parts button hides): CM5 went
  from 36,759 meshes to 32, 37,163 draw calls to 36, CPU per redraw from
  ~240 ms to ~1.3 ms (headless), in ~0.4 s at load. `window.kigit3dMerge`
  has the counts. Per-part objects are gone, so anything per part (picking,
  highlighting) would need a part id per vertex. Headless
  Chrome renders big models in software and slowly.
- BOM (`bom.py`): the header's BOM button (opens its tab in the click,
  `window.kigitBomTab`) runs `kigit bom --json` for the working tree or the
  one ticked commit and shows `/bom/{key}` (`bom.jobs`, in memory). It's
  also the editor for part information fields: columns MPN, Manufacturer,
  Digi-Key/Mouser/LCSC (when used), fields added with + Field, each by the
  project's own name (`field_names` in the JSON). Edited cells are drafts
  in `<board folder>/kigit-bom.json` (`{"version": 2, "drafts": {line key:
  {field: value}}, "columns": [...]}`; version 1 "picks" are read as
  drafts; line key = value|footprint[|part number], `bom.line_key` and the
  page's `lineKey` must agree), posted to `/bom/{key}/drafts`. Write posts
  the changed cells to `/bom/{key}/write` -> `kigit bom --write` (refs per
  line from the job's data), then drops their drafts and re-reads the BOM;
  `/bom/{key}/undo` -> `--restore` of that write's backup. Commits'
  BOMs are read-only (`EDITABLE`, and the route refuses). KiCad's lock
  (409 `locked`) asks before `force`. Export CSV is made in the page (what's
  shown, drafts included; quantities x Build qty `#boards`, DNP left out unless ticked).
  Only on request: no background
  lookups. The page is `bom_page.html` (a plain file, read at import: no
  Python escaping), placeholders `%%KEY%%` etc. Beside the list: a 2D
  board drawn from `kigit --json REV..REV` (`kigit.board_json`, in CACHE
  as `<3d name>-board.json`, served by `/bom/{key}/board.json`; pads keep
  `data-ref`, a box per ref from its pads) and a 3D board (the 3D view's
  model, `build_models` after the tab opens; `/bom/{key}/status` for the
  wait). `light(refs, one)` lights a line's parts in both (`board2d.light`,
  `window.bom3d.light`: tinted copies of the part's meshes + a Box3Helper,
  other parts faded); hovering a pad or a part (box picking, as in the 3D
  diff) calls `window.bomHover(ref)`. The 3D code is a trimmed copy of the
  3D diff's (merge by material, materials, picking), sized to its pane
  (ResizeObserver). Planned step 2: Digi-Key / Mouser API lookups (stock, price,
  lifecycle, alternatives), keys in the app folder. Look up (every site with a key):
  the page POSTs `/bom/{key}/lookup` {boards = Build qty, refresh =
  Shift}, which runs `bom.run_lookup` as a task (`Job.lookup`: running,
  done/total from kigit's "looking up i/n" stderr lines via
  `kigit.bom_lookup`'s Popen reader, result, error); the page polls GET
  `/bom/{key}/lookup` (also on load, so a reload keeps it). Rows match
  by `key` (= `lineKey`). Per site in the result, columns `site:<s>` and
  `price:<s>`; `N choices` / `N instead` opens a `tr.choices` row
  (opened keys `"<line>|<site>"`; alternatives above candidates) and Use
  (`data-site`, `data-list`) posts MPN + Manufacturer drafts. Keys:
  `/bom/{key}/keys` GET -> `kigit bom --keys` (set/env/name, Digi-Key's
  site and currency; never a key), POST {site: mouser, key} or {site:
  digikey, client_id, client_secret, locale_site, currency} ->
  `kigit.bom_set_key(site, *lines)` on stdin (`_run(input=)`); never
  logged. The Keys dialog does both sites. Parts files follow
  `KIGIT_LOG_DIR`'s parent like the GUI's, so GUI tests stay in temp.
  Layout: panels List/PCB/3D (`PANES`, header buttons + `[data-hide]`
  on pane bars; the last shown one can't be hidden), `kigit.bomPanes`
  {list, two, three}. Columns: `tableCols()` is every column ({id, th,
  td}; ids `qty`, `refs` (fixed), `value`, `f:<field name>`,
  `site:<s>` and `price:<s>` per looked-up site, `search`), `visibleCols()` drops `hiddenCols`
  (`kigit.bomHiddenCols`); the Columns button opens `#colmenu`. Code
  finds cells by class (`td.refs`, `td.links`), never by position.
  Widths: `#bom` is `table-layout: fixed` with a `<colgroup>` from
  `applyWidths` (`widthOf(id)`: dragged `colWidths`, kept in
  `kigit.bomColWidths`, else `defaultWidth`), and the table is exactly
  their sum (no 100%, so dragging one doesn't move the others); a `.grip`
  inside each th's right edge drags (pointer capture), double-click drops
  that width, `#resetw`/`#colsreset` drop all. Field cells are
  `textarea.cell` (rows 1, `fit()` sets the height to the text; Enter
  blurs; line breaks become spaces) so long values wrap.
  Trackers (+ Tracker): the user's own tick columns for a build, in
  `kigit-bom.json` as `"tracking": {"columns": [names], "done": {name:
  [refs]}}` (`bom._tracking` cleans it; `add_tracker`, `remove_tracker`,
  `set_tracked` re-read the file first), posted to `/bom/{key}/drafts` as
  {tracker, remove?} or {track, refs, done}. Never written to the
  schematic. Per reference, not line key (keys change when an MPN is
  written; lines regroup): `trackState` is all/some/none (some =
  indeterminate box). Column id `t:<name>`; the CSV adds yes/partly/"".
  Column filters: a column with `filter` ("text" + `text(l)`, "track" +
  `tracker`, "site" + `site`) gets a `.fbtn` in its header; `#fmenu`
  (radio modes from `FILTERS`, a text box for "has") sets
  `colFilters[id] = {mode, q}`; `passesFilters(l)` ANDs them in
  render's row filter (a filter on a column that's gone is ignored;
  DNP lines fail tracker filters). Not saved across reloads. A rename or
  tracker removal moves or drops its filter.
  BOM notes: each References cell has `.nbtn` (+ Notes, or 📝 N from
  `/bom/{key}/notes` = `notebook.counts_by_part`, max over the line's
  refs). The Notes pane (`#panenotes`, `shownotes` in PANES; + Notes
  shows it in the PCB's place) is an iframe of `/bom-notes/{notes key}?
  bom={job key}&pane=1` (`NOTESKEY` = `project_key(board folder)`, the
  same key as kigit's Notebook), loaded on first show; ↗ opens the same
  page without pane=1 in a tab and blanks the iframe (one copy of a note
  open). They talk over `BroadcastChannel("kigit-bom")`, messages carry
  `job`: page -> notes `line` {line: {key, refs, value, footprint, mpn,
  manufacturer}, open} (+ Notes: open=true opens the newest note about
  its parts; a row click: open=false); notes -> page `hello` (on load, the
  page answers with the current line) and `notes` (a note made or
  (un)pinned: recount). The notes page is `notebook_page(key, bom, compact)`
  (route in app.py): `NotebookPanel` with `bom` set shows `bom_view` (the
  line, `notebook.notes_for_parts`, New note = `notebook.bom_note` in
  reviews/BOM/ pinned with `part_anchors` (sch parts, seen HEAD..working
  tree) and a template with `commit_ref`, Pin this line, Commit =
  `commit_dialog` from `kigit.history`, appended as "- Commit `abc1234`
  (date · subject)"); `compact` is one column. `set_pinned` posts
  `notes`. Tests: test_notebook (helpers), test_app `test_bom_notes_page`.
  Renaming columns (`renameColumn`, double-click a `th[data-rename]` or
  ✎ in Columns): only added fields (`custom`, no `kind`) and trackers.
  Tracker or a field with no schematic values: `rename_tracker` /
  `rename_column` in kigit-bom.json (drafts move with it). A field with
  values: `/bom/{key}/write` {cells: [], renames: [{from, to}]} -> a
  `--write` edit {refs: every BOM ref, field, rename}: `FieldEdit.rename`
  replaces only the property's name atom (parts without it are skipped;
  refused if the part already has the new name, or the same batch also
  sets it); same_design gets both names as edited, and the read-back
  expects the value under the new name and the old one gone. Hidden
  state and width move to the new column id.
- 3D diff (beta, `board3d_diff.py`): separate from the 3D view, which
  stays as it is. The header's "3D diff" button (`diff3d_btn`, a "beta"
  badge; shown with `dock_btn`) opens a blank tab in its click
  (`window.kigitDiffTab`; a later `window.open` is a blocked pop-up), then
  `open_3d_diff` makes a `Job` (`board3d_diff.jobs`, in memory) and points
  the tab at `/board3d-diff/{key}`: a waiting page polling
  `/board3d-diff/{key}/status` while `build_models` makes both models (the
  3D view's cache names, so shared) and `kigit.diff_json` writes
  `kigit --json` for the pair (`--files` for `disk:` pairs) into CACHE.
  The page: the new model, unchanged parts merged by material (and faded),
  changed parts tinted by `footprints[].st` (1 added, 2 removed, 3 or
  `moved` moved, else changed), removed and moved parts' old places as
  ghosts from the old model, parts without a model outlined from their
  pads, and tracks/arcs/vias with `s` 1/2/5 (and 3/4) as flat strips just
  above/below the board (SVG `d` paths, arcs flattened). KiCad's glb is in
  the board's own coordinates: x = X/1000, z = Y/1000 (checked on blinky
  and CM5), so no alignment is needed. GPU: `WEBGL_debug_renderer_info`'s
  renderer, classed good / built-in ("meh") / none (SwiftShader, llvmpipe,
  Basic Render); none or built-in drops the pixel ratio to 1 (none also
  drops antialiasing). `window.kigit3dDiff` has the counts. Render
  stats (S, `?stats=1`): the 3D view's, copied in (`redraw` goes through
  `stats.draw()`), plus `diff` (`window.kigit3dDiffLoad`: changed parts,
  ghosts, strip meshes, load ms split into data / models / build).
  Hover (`hover`): each part's world box is taken before merging (`picks`:
  unchanged, changed, ghosts, pad outlines); pointermove (once per frame,
  not while a button is held) tests the ray against the boxes (slab test),
  takes the smallest box among those the ray is in at once, and drops parts
  on the board's far side. Value and footprint come from
  `schematic.new/old.symbols`, changes from `footprints[]`. A white
  `Box3Helper` outlines it. `window.kigit3dPick(x, y)` gives the reference
  (for checks). `test_board3d_diff` runs `node --check` on the page's
  script (skipped without Node): a bad escape in the Python string only
  shows in a browser otherwise.
- Landing page: `open_folder(folder, startup=True)` (from `index()`)
  shows it instead of an error when the start folder has no project with a
  board (none at all, or only a .kicad_pro, like this repo's fixtures); an
  explicit Open still says why. Also the header's "kigit"
  (`show_landing`). `sessions.py` keeps `<app data>/kigit/sessions.json`
  (atomic write, max 30, one entry per board, broken entries skipped):
  `opened()` from `load_history`, `compared()` from `run_diff` (revisions
  as compared, labels and the newer commit's subject). Cards: Open
  (`open_folder(dir, prefer=board)` picks that board when the folder has
  several), Resume (then `run_diff(last.old, last.new)`), forget. The
  scroll area needs an explicit height (NiceGUI's default is 256 px).
  Pictures: `kigit --render -o x.png` (`run_render` in board3d.cpp:
  `kicad-cli pcb render --side top`, 480x480 so wide and tall boards both
  fit, transparent, made in a temp folder and moved) of the board on disk,
  kept as `thumbnails/<sha1(board)[:16]>.png` next to sessions.json and
  served at `/session-thumb/{key}.png`. `take_snapshots` renders one at a
  time in the background after `load_history` and for stale cards on the
  landing page (`thumb_fresh`: picture newer than the board), then fills
  the card's slot; no kicad-cli turns it off for the session. GUI tests set
  `KIGIT_KICAD_CLI` to a missing file and fake `kigit.render`.
  GUI tests point `KIGIT_LOG_DIR` at a temp folder (conftest), so they
  never write the real sessions or build times.
- Notebook (`notebook.py` + `notebook_panel.py`): your notes are any
  Markdown in `reviews/` that isn't kigit's (the same set the Reviews site
  shows; folders with only non-Markdown files, like images/, are left out).
  Pins: `<!-- kigit-pins [...] -->` at the end of the file (`PINS`), read
  off and written back; nothing else in the file is touched, and a note is
  only written when its text or pins change. `about(anchor)`: pinned
  (`same_component`: footprint = part by reference, nets and buses by name)
  then mentioned (whole word). `log()`: `- HH:MM line (pin · at abc1234)`
  under `## 16th November 2026` in the folder's `Logs.md`. The panel
  browses one folder at a time (`listing`, `go`, ⬆ and a clickable path);
  each row's ⋮ renames (`rename`, `rename_folder`) or deletes (`delete`,
  after a warning from `contents` and `unsaved_in_git`); only your notes
  and folders (`_inside`), never reviews/ itself or kigit's files. Its
  dialogs go in `NotebookPanel.host`, not inside the row that opened them.
  Its own tab: `/notebook/{key}` (`notebook_page`, registered in app.py
  so the test harness sees it), `standalone=True`, a wide two-column view.
  Tabs talk through a `BroadcastChannel("kigit-notebook")` in the browser,
  messages carrying the project key: kigit's tab posts `pinned` (on every
  pin change, `tell_pinned`), the Notebook's posts `hello` (on load) and
  `go` (show a pin; kigit's tab runs `go_to`). Messages go out through the
  panel's own client (`self.client.run_javascript`), not the current slot.
  The panel is a seamless right-hand dialog (the viewer still takes clicks), autosaves
  0.8 s after typing stops, and N (`kigit_quick_note`) makes a note about
  what's pinned. A pin is shown in the comparison on screen
  (`focus_if_shown`), else its `seen` comparison is opened. Reviews site:
  a page per folder at any depth (`notes/<path>/`, obj = its path),
  `_subtabs` (a row per level), `_sidebar` a `<details>` tree; note pages
  show their pins.
- Activity (`activity.py`): kept in the project, for git:
  `reviews/activity/<person>/<computer>.json` (`{"days": {date: {kind:
  n}}}`; person = git user.name, computer = host name, both slugged), so
  each computer writes only its own file (no merge conflicts) and
  `load()` adds up a person's files (`person="*"`: everyone).
  `activity.use(project, person)` is set when a project opens (no project:
  nothing counted). `record(kind)` (compare, review, discussion, reply, 3d,
  note): atomic write, never raises; called from run_diff, the 3D views,
  ReviewPanel.write, Discussions and the Notebook. `show_activity` (the
  header's calendar button, You / Everyone) draws `heatmap_svg` (53 week
  columns, Sunday on top, `<title>` tooltips, 5 levels scaled to the
  busiest day) and `stats` (total, by kind, streaks, busiest day).
- Pictures (`lightbox.py`): clicking an `<img>` in rendered Markdown
  (`.kigit-md-view` in the GUI, `main .md` on the Reviews site) opens a
  full-size overlay (Esc or a click closes it; pictures inside links stay
  links). `md_editor.rewrite_assets` turns Obsidian `![[pic.png|300]]`
  into an `<img>` served by `/reviews-doc/{key}/files/` (found by name
  anywhere in reviews/), so the GUI shows them like the site does.
- The owl (`owl.py`, an easter egg; keep it out of the docs and the
  shortcuts list): a snowy owl in SVG, all JS/CSS in the page, off by
  default. Its door is a small owl face in the header, between the kigit
  logo and the folder box (`owl.door()`, `#kigit-owl-door`, title "hoo?";
  the page script listens on the document, since the header is drawn
  after it runs). On/off in localStorage `kigit.owl`. Perched it blinks,
  tilts/turns its head, follows the mouse with its pupils, ruffles, hops;
  every 30-70 s it flies to a perch: the bottom edge, the right half of the
  header, or a panel's top edge lower down. Shaking the mouse over it (4
  direction changes within 0.9 s, worked out from pointermove, as it takes
  no pointer events) startles it and it flies at least 300 px away.
  `pointer-events: none` throughout. `window.kigitOwl()` reports its state.
- Shortcuts (`shortcuts.py`): the header's keyboard button and "?"
  (outside text boxes, `kigit_shortcuts`) show `GROUPS`. Each shortcut
  names where it's handled (`where`: file, code); `test_shortcuts` fails
  when that code is gone, so add or change the entry when you add or
  change a shortcut. The dialog sets its own width (Quasar caps dialogs at
  560 px).
- Notifications (`notices.py`): `notices.add(level, title, detail,
  headers, rows)` keeps up to 200 per GUI process (newest first); `notify()`
  adds warnings and errors it shows (`notice=False` when the caller adds a
  fuller one). The header bell polls `notices.version` each second and
  shows a red "!" badge while `unread_problems()`; opening it marks all
  read. Notices with rows are also written to the log. Pages for their own
  tab: `/notices` (polls `/notices.json`) and `/log` (polls `/log.txt`,
  the session log's tail; Follow and a filter), both every 2 s. `kigit
  --3d` lists parts without a model on stderr as `missing 3D model:
  REF<tab>PATH` (parsed from kicad-cli's "Could not add 3D model for X." +
  "File not found: P" pairs); `kigit.board3d` returns `Made3d(warnings,
  missing)` and `build_models` makes one notice with the table.
- Reviews (GUI only): pick one commit and press Review; it's diffed against
  its `parent` and a right drawer opens. One Markdown file per commit in
  `<board folder>/reviews/`, named `<id>.md` (a random 8-hex ID given on
  the first Write, also in the `id:` header; found by the `commit:` header),
  pasted/dropped images in `reviews/assets/<sha256[:16]>.<ext>`.
  `reviews/index.md` (a table: ID, full hash, commit date, author, subject,
  note count, written) is rebuilt from the review files on every Write;
  never parsed back. Note times (`review.stamp`, on every save): `created`
  when a note is first written, `edited` when a later write changes its
  title, text, tags or anchor, compared with the file on disk. Notes from
  older files have no times and get none. Writing a review with no summary
  and no notes deletes its file (`review.remove`); the commit list's mark
  is `review.reviewed_commits` (non-empty reviews only).
  A note is a `## title` line followed by
  `<!-- kigit-note {"id", "anchor", "tags", "created", "edited"} -->`; anything before the first
  note is the summary. Anchors are `{tab, kind, name, seen}`: pcb
  net/footprint, sch net/part/bus, by name. `seen` is
  `{old, new, side}`: the two full hashes compared when it was pinned
  (`meta.old.hash`/`meta.new.hash` in the page) and `side: "old"` when that
  comparison removed it (shown as "· removed"). Commits don't change, so that
  comparison always has it, deleted or not. When a removed and an added item
  share a name, focus picks the one on the anchor's side. Older anchors
  without `seen` still load. Nothing is saved until Write (or Ctrl+S).
  Unwritten edits of a review you leave stay as a draft for the session
  (`ReviewPanel.drafts`), and the page warns before closing while anything
  is unwritten (an element with class `kigit-unsaved`). Comparing a commit with its parent opens its review
  too.
- Discussions (PR-style "needs attention", `threads.py` + `discussions.py`):
  one file per discussion in `reviews/threads/<id>.md` (frontmatter: id,
  title, opened, by, commit it was opened on, anchor JSON), then messages,
  each a bold line for people and `<!-- kigit-msg {author, time, head,
  kind} -->` (kind: comment, done, accepted, reopened); the status is the
  last status message's (open/done/accepted). Messages are appended and
  written at once (no Write); `threads.add` re-reads the file first.
  `threads.edit` changes your own message's text in place (by index,
  checked against author and time; `edited` in its meta and the bold line).
  The discussion dialogs are created in `Discussions.host`, not where
  they're opened from: the review panel's list is redrawn on every send.
  Several anchors: notes and discussions keep the first in `anchor` (what
  older files and code read) and the rest in `more` (`"more": [...]` in
  the note's meta, a `more:` line in a discussion's header); `.anchors` is
  all of them, `Note.set_anchors` sets them, `review.same_thing` compares
  by tab/kind/name. `threads.repoint(..., anchors)` (opener only) adds a
  `repointed` message (no status change). `threads.rename` (opener only)
  adds a `renamed` message holding the old title.
  `threads.delete` removes your own comment (not a status change). Links:
  `threads.link_markdown` gives `[title](threads/<id>.md)` (relative to
  reviews/); the panel's link click handler (review_panel `_PAGE_JS`)
  emits `kigit_open_thread` for such hrefs (`Discussions.open_link`).
  `Discussions.check_links` warns about links to missing discussions
  (`notices.warn`: pop-up, log, bell) once per place and discussion per
  session: on opening a review or discussion, Write, send, edit, request.
  The Reviews site sends them to `discussions/<id>`, or a `.wl.missing`.
  Mentions (`mentions.py`): `all_mentions(project)` scans discussion
  messages and reviews (summary, notes) for discussion and review links,
  keyed `thread:<id>` / `review:<id>` (self-links skipped); computed each
  time, never written into the linked file. The chat shows them by time
  (`Discussions._mention`), the site as "Mentioned in". `new_for_me`
  (called from `threads_changed`, which `watch_threads` triggers on any
  discussion or review file change) returns others' mentions of
  discussions you opened or wrote in, not yet seen; seen keys per project
  in `<app data>/kigit/mentions-seen.json` (a project's first look is a
  quiet baseline). They're `mention` notices: the bell shows "@" (purple)
  unless problems ("!") are unread.
  Review links: `review.review_link` gives `[subject](<id>.md)`; the click
  handler emits `kigit_open_review` (`open_review_link` in app.py runs
  that commit's review). The commit list's right-click menu is a
  `ui.context_menu` on `table_box` (a QTable doesn't render children);
  `rowContextmenu` (`[event, row, index]`) says which row it's for.
  Author: git `user.name` (`kigit --log` now gives `user` and `head`).
  GUI: Request in the review panel (`Discussions.request`), the header's
  Discussions list with a badge (red while any is open), a chat dialog with
  Mark as done / Accept / Reopen; the review panel lists this commit's and
  those still open from other commits; commit rows get a `thread` flag.
  `watch_threads` polls the folder's mtimes every 4 s (a pull shows up).
  The Reviews page has a Discussions section; `own_notes` skips threads/.
  Commit hashes in the chat are links (`Discussions.jump_pair`): a
  message's compares the opening commit with it; the opening commit's own
  compares it with HEAD (else the anchor's `seen` pair); `compare_and_show`
  in app.py runs the diff and posts the focus once the iframe loads.
- Rewritten commits (`rewritten.py`): after each history load the GUI asks
  `kigit --rewritten` about reviews whose commit isn't listed; those on no
  branch are "strays" (`state["strays"]`), shown in a bar above the list.
  Fix moves a stray to its match (`review.move`: `retarget` sets the
  commit, parent, subject, date and author, and moves anchors whose `seen`
  was the commit's own comparison; it merges into an existing review of the
  target with `absorb`). Rows with unwritten edits are skipped. Squashes
  can't be matched: the review panel's Bring in reviews absorbs strays into
  the open review (ticked when the commit message names their hash or
  subject, `squashed_into`); their files are in `Review.absorbed` and
  deleted by `review.save`, so nothing changes until Write.
- Reviews site (`review_doc.py`): the header's Reviews button opens
  `/reviews-doc/{key}/` in a new tab: a docs site, one page each, built
  from `reviews/` on every request (`build()` -> `Book` of `Page`s; nothing
  cached). Addresses under the base: `""` home, `reviews` (the timeline,
  by month), `reviews/<id>`, `discussions`, `discussions/<id>`,
  `notes/<folder>/` and `notes/<path without .md>` for your own notes (any
  other `.md` in `reviews/`, not `index.md`, `assets/`, `threads/` or hidden
  folders), `tags`, `tags/<tag>`. Tabs: Home, Reviews, Discussions (if
  any), one per top folder of notes, Notes (loose files), Tags (if any).
  Left: the tab's pages (`_sidebar`); right: "On this page" (notes, or the
  note's h2/h3, given ids by `_with_ids`); prev/next (Newer/Older for
  reviews). Search: `/reviews-doc/{key}/search.json` (`search_index`: every
  review, discussion and note, plus each note in a review with its
  `#n-<id>`), fetched by the page on first use; all words must match, title
  hits first. Routes: `files/` and `search.json` are registered before the
  `{page:path}` catch-all. Obsidian `[[name|text]]` links resolve to notes
  (title, file name or path) and reviews (ID, file name, commit subject);
  `![[pic.png|200]]` finds the picture by name in `reviews/`; pictures are
  served from `files/` in the GUI (data URLs without `files_url`). Relative
  pictures are read only from inside `reviews/`. Links: bare
  `https://`/`www.` addresses are linked (`review.autolink`); relative
  `[text](x.md)` to a note or review goes to its page; links to other files
  in `reviews/` (and `[[file.pdf]]`) go to `/reviews-doc/{key}/files/...`
  (pictures, PDFs and text shown, anything else a download); links leaving
  the site open in a new tab. `_PAGE` is one template with `%%NAME%%`
  placeholders (plain CSS/JS braces). Colours are CSS variables, dark by
  default, light under `prefers-color-scheme` or `data-theme` (the Theme
  button, `kigit.docTheme` in localStorage). Notes in reviews have a
  PCB/SCH badge on the anchor and a left border by their first known tag
  (`_TAG_KINDS`); #tags in your own notes show as `.itag` (not in code).
- Markdown rendering for reviews: `review.to_html` (the panel's preview and
  the page both use it): bare links, then `$inline$` / `$$block$$` LaTeX
  converted to MathML by latex2mathml (browsers draw it; no JavaScript, works
  offline), then markdown2. Math follows Pandoc/Obsidian: no space just
  inside `$...$`, no digit after the closing `$` ("$5 and $10" is text),
  `\$` is a dollar sign, code untouched. Math is swapped for `KIGITMATH<n>X`
  tokens before Markdown and back after. A formula that fails shows as
  `<code class="math-error">` with the error as its title.
- Note tags (`ReviewPanel._tags_select`): a multiple `ui.select` with input,
  options from `review.known_tags` (built-in `TAGS`, then tags used in the
  project's reviews) plus this review's; typed tags go through
  `review.clean_tag` (lower case, spaces to `-`, no `#`). Custom `option`
  and `selected-item` slots draw tick boxes and coloured chips
  (`TAG_COLORS`, the reviews page's colours). The slot templates sit inside
  double-quoted Vue attributes: single quotes only.
- Review editor links: each text box has a link button (and Ctrl+K) that
  asks for an address and text (the selection, read with
  `window.kigitSelection`) and puts `review.link_markdown(text, url)` in its
  place, from Python (so it's testable without a browser). Built from the
  files on each request (drafts aren't in it); markdown2 renders the
  Markdown and assets/ images are inlined as data URLs, so a saved copy
  stands alone. Light and dark follow the system.
- Viewer bridge: inside the GUI, `pcb.js`/`sch.js` post
  `{kigit: "pinned", anchor}` to the parent on every pin change; the GUI
  posts `{kigit: "focus", anchor}` and `shell.js` switches tab, calls
  `window.kigitFocus[tab]` and answers `{kigit: "focused", found}`. Images
  are uploaded over HTTP (`/review-image/{key}`, not the websocket) and
  served from `/review-files/{key}/`; `key` is a random per-project token.
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

`KIGIT_PORTABLE=ON` links libstdc++/libgcc statically on Linux, so the
binary only needs glibc (the libraries are always built in from the
submodules). `kigit gui` looks for uv next to the exe, then in
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

- Reviews: the working tree (notes before committing), reviews across a
  range, showing reviews in the HTML page (`--review`), note markers on the
  canvas.
- Schematic to PCB cross-probing.
- A net filter on the schematic tab.
- Fab and courtyard layers.
- Pour outlines.
- Linux packages; macOS support (CI and packages) if it's wanted again.
