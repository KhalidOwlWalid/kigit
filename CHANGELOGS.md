# Changelog

All notable changes to kigit, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Commit reviews** in the GUI: pick a commit and press Review to see it against its parent and write down why it changed. A summary plus notes, each pointing at a net, footprint, part or bus pinned in the viewer (click to show it again), in Markdown with pasted images, links (a link button and Ctrl+K), LaTeX math (`$...$`, `$$...$$`) and tags, each stamped with when it was written and last edited. Press Write (or Ctrl+S) to save it as one Markdown file per commit in the `reviews/` folder next to the board, named by the review's ID, with `reviews/index.md` listing every review (ID, commit, date, author, subject); unwritten edits are kept as a draft until then. The **Reviews** button opens all of a project's reviews, and any Markdown notes of your own in `reviews/` (Obsidian links, embeds and tags included), as one page in a new tab, with search and tag filters.
- **Discussions** (PR-style review): from a commit's review, ask for attention on a part, net or the commit; it's a chat anyone can reply to, mark done and accept, kept open across later commits until accepted, and shared through git (`reviews/threads/`). A header button lists them with a count; commits get a flag.
- **Docs**: new Reviews and 3D View pages, the GUI page reorganised, and screenshots of each feature (made by `tools/docs_screenshots.py`, which drives the GUI, so they can be retaken).
- **Shortcuts list**: a keyboard button in the header (or ?) lists every keyboard and mouse shortcut, by area.
- **Landing page** in the GUI: started outside a KiCad project, `kigit gui` opens on your recent projects (kept in `sessions.json` next to the logs), each with a picture of its board (rendered by KiCad), Open and Resume (compare the last two commits again). `kigit --render -o board.png` makes that picture from the command line. The header's kigit goes back to it.
- **Notifications** in the GUI: a bell in the header keeps the session's warnings and errors (a red ! while unread), with lists where there are some, like the parts KiCad found no 3D model for. The notifications and the session log can each open in a tab of their own that updates by itself.
- **3D view** in the GUI: pick a commit and press 3D to see its board as KiCad draws it in 3D (copper, silkscreen, mask and parts), to rotate, pan and zoom, with top/bottom/3D views and parts on or off. Fast on big boards: KiCad's tens of thousands of small meshes are merged into a few dozen when it loads. Dock the 3D board beside (or below) a comparison while you look at the diff: new, old or both; pop it out into its own browser tab, and closing that tab docks it again. Pick up to four commits to see their boards side by side, with linked views. Mask and Silk buttons hide the solder mask and silkscreen so traces are easy to follow. Building a 3D model shows a progress bar (time against the board's last build, as KiCad reports none). Press S for render stats (input delay, time per redraw, dropped frames, draw calls). KiCad's `kicad-cli` makes the model (KiCad 8+), with boards from older KiCad versions pointed at the current 3D library so their parts show; `kigit --3d [REV] -o board.glb` does the same from the command line.
- A note's **tags** are picked from a dropdown: the built-in tags plus every tag the project already uses, with tick boxes and coloured chips; type a new one and press Enter to add it (saved as one lower-case word).
- The **Reviews page** has a new design: a header with counts, reviews as a timeline, notes marked with PCB/SCH badges and tag colours, nicer Markdown (code, tables, quotes, task lists), a light/dark switch, `/` to search, and copyable heading links. `[[commit subject]]` links to that commit's review.
- Reviews survive **rebase, amend and squash**: the GUI notices reviews of commits no branch has any more, moves them to the commit a rebase or amend made (found by author and author date), and a squashed commit's review can **Bring in** the reviews of the commits squashed into it. `kigit --rewritten HASH...` gives the GUI that information.
- `kigit gui` takes the next free port when 8765 is in use, so several GUIs can run at once, and prints its address; `--port N` picks one (and says so if it's taken).
- **Wrap messages** switch above the GUI's commit list, for reading long commit messages (remembered).
- `kigit --log` gives each commit's parent.
- Documentation site at [khalidowlwalid.github.io/kigit](https://khalidowlwalid.github.io/kigit/), built with MkDocs (Material): installation, how-to guides for the GUI, command line, PCB and schematic viewers and source panel, examples, and an architecture page.
- Demo videos and GIFs of the PCB and schematic diff.

### Changed

- README rewritten to match the docs home page, with the detailed usage moved to the docs site.

## [0.1.2] - 2026-10-28

### Added

- **Source panel** (`--source`, or "Include source" in the GUI; off by default): the old and new text of whatever you hover in the `.kicad_pcb` / `.kicad_sch` files, side by side like a code diff. Changed characters are highlighted, unchanged stretches fold, and each change shows its file and line number. Works on both the PCB and schematic tabs.
- **Native window for the GUI**: on Windows, `kigit gui` opens in its own window (Edge WebView2) instead of the browser. `--native` and `--browser` choose, and if a window can't be opened it says why and falls back to the browser.

### Changed

- The GUI only listens on 127.0.0.1, so it isn't reachable from the network.

## [0.1.1] - 2026-10-28

### Added

- **Linux release**: a portable `kigit-<version>-linux-x86_64.tar.gz` (Ubuntu 22.04+, Debian 12+, Fedora 36+ or similar) to unpack into `~/.local`. It brings its own copy of uv for the GUI.

### Changed

- The libraries (nlohmann_json, spdlog, doctest) are now git submodules in `submodules/` instead of being downloaded at build time. Clone with `--recursive`, or run `git submodule update --init` in an existing clone.

## [0.1.0] - 2026-10-28

The first release.

### Added

#### PCB diff

- Per-net visual diff of a `.kicad_pcb` between two git revisions, written as one self-contained HTML page: added copper in green, removed in red.
- Hover a trace, via or pad to highlight its whole net and see its changes, including how its copper length changed. Click to pin, scroll and drag to zoom and pan, `/` to filter nets.
- Items are matched by KiCad's internal ID first, then by geometry, so moving a footprint or the whole layout shows as **moved** (blue), with an optional ghost at the old position, instead of everything removed and re-added.
- Footprint changes: pads, graphics, fields (value, footprint, 3D model) and position.
- Layer toggles, with select all / deselect all.
- Silkscreen comparison (`--silkscreen`, off by default).
- A terminal summary of the most-changed nets (`-s` for all of them).

#### Schematic diff

- A **Schematic** tab that draws every sheet with the same colours: parts added, removed or changed, nets highlighted on hover, pins that joined or left a net. Double-click a sheet box to open it.
- kigit works out the schematic's nets itself, including hierarchical sheets and KiCad 10's multiple top-level sheets. `--check-netlist` compares them with a netlist exported by KiCad.
- Bus support: vector buses (`D[0..7]`), bus groups and bus aliases. Hovering a bus lists its members.
- Changes are sorted into **electrical**, **fields only** and **cosmetic**, and printed in the terminal.

#### Revisions and files

- Compare two commits, or a commit against your uncommitted changes (`LOCAL`). If the newer revision is given first, they're swapped so "added" always means added in the newer one.
- Boards that were moved or renamed in history are found by comparing footprints and nets with the current board.
- No git needed with `--files OLD NEW`, or by passing two board files.
- `-C` / `--kicad-repo` to run from any folder.

#### GUI

- `kigit gui`: open a project, see every commit (tagged **PCB** / **SCH** when it changed the board or schematic), pick two and compare.
- Commit filters: how many to list, a date range, and only commits that changed the board or schematic. History is followed through renamed project folders.
- Diff any two revisions by hand, and **Compare folders** for projects that aren't in git.

#### Other

- Scripting output: `--json`, `-o -` (to stdout), `--log` (commit history as JSON) and `--projects` (KiCad projects in a folder).
- A log file for every run of the command line and the GUI (`--log-dir`, `--no-log`, `-V`).
- Windows support (MSVC and MinGW), with a Windows installer and a portable zip on every release.
- CI that builds and tests every push on Windows and Linux.

### Fixed

- KiCad 5 pin names containing `/` broke parsing.
- Traces on some layers weren't shown as changed.
- The GUI could freeze on Windows when stopped with Ctrl+C.
- Build fixes for GitHub Actions (CMake policy minimum, doctest warnings on MSVC).

[Unreleased]: https://github.com/KhalidOwlWalid/kigit/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/KhalidOwlWalid/kigit/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/KhalidOwlWalid/kigit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/KhalidOwlWalid/kigit/releases/tag/v0.1.0
