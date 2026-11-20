# Changelog

All notable changes to kigit, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Bill of materials**: `kigit bom` and the GUI's **BOM** button, only when you ask. Parts grouped into lines with their part numbers (read from the usual field names: MPN, Manufacturer, DigiKey, Mouser, LCSC Part #...), DNP and excluded parts handled, and Digi-Key, Mouser and LCSC search links per line (by part number, or "10k 0603 resistor" for passives). Beside the list, the board in 2D (from the board file) and in 3D: hover a line and its parts light up on both; hover a part on either and its line lights up. Export a CSV for Digi-Key's or Mouser's BOM upload, times the number of boards you're building (Build qty). Also `--csv` and `--json`.
- **Stock and prices from Mouser**: `kigit bom --lookup` (only when you run it). For each line: stock, price for the parts you need (`--boards N`, with Mouser's minimums, multiples and price breaks), lead time and lifecycle; **SHORT** when Mouser has too few. A line with a part number gets that exact part; one without gets up to five ranked choices (kigit doesn't pick a part for you). Your Mouser API key is saved with `kigit bom --set-key mouser` in the app folder, passed to curl on stdin (never on a command line) and kept out of the logs. Answers are kept a day (`--refresh` asks again). On the BOM page: **Look up** (it asks for the key the first time) adds Mouser and Price columns for Build qty boards, a total in the header, and **Use** on a choice to make it the line's MPN draft. Digi-Key comes next.
- **Stock and prices from Digi-Key** too: Look up asks every site you have a key for (Digi-Key: a free app's client ID and secret, prices from the Digi-Key site and currency you pick). Each packaging is its own offer (cut tape, a whole reel), and a part that's short or ending gets Digi-Key's suggested **substitutes** (Direct, Upgrade...) with **Use**. Each site has its own columns and summary. `kigit bom --set-key digikey`, `--site`, `--keys`.
- **Filter by any column** on the BOM page (**▾** in its header), and combine them: trackers (done, not done, partly), text columns (contains, empty, not empty), each site's column (found, short, ending, to choose, not found). **Clear filters** shows everything again. (The tracker entries in **Show** went: the trackers' own filters do it.)
- **Rename columns** you added on the BOM page (double-click the title, or ✎ in Columns): a tracker or a field with only drafts is renamed in `kigit-bom.json`; a field already in the schematic is renamed on its parts too (only the name changes; checked, backed up, Undo). `kigit bom --write` takes `{"rename": ...}` edits.
- **Trackers on the BOM page**: **+ Tracker** adds your own tick columns (Carted, Placed...) to follow a build. Ticks are kept per part in `kigit-bom.json` (never in the schematic), counted in the header, filterable, and in the CSV.
- **BOM page layout**: hide any panel (the list, PCB or 3D) from the header or the pane's own **Hide**, and any column (**Columns**; References stays). Resize columns by dragging a header's edge (double-click: that one back; **Reset widths**: all). Long part numbers wrap in their cells. All remembered.
- **Part numbers into the schematic**: the BOM page edits part information fields (MPN, manufacturer, distributor numbers, fields you add), as drafts in `kigit-bom.json` until you **Write to schematic**, with **Undo**. `kigit bom --write` / `--restore` on the command line. Only those fields, ever: KiCad's own fields are refused, the board and wiring are never touched, each edit is the smallest change to the file, and kigit checks the schematic is the same design before saving (or writes nothing).

## [0.2.3] - 2026-11-18

### Added

- **3D diff (beta)**: a new header button beside **3D**, while a comparison shows. It opens the comparison in 3D in its own tab: parts added (green), changed (amber), moved (blue, with a ghost of the old place) and removed (a red ghost), and added, removed and changed tracks and vias as coloured strips. It says which graphics chip draws it and warns when that's built-in laptop graphics or none (the CPU draws it all). Hover a part to see what it is (reference, value, footprint) and what changed. Render stats with S, as in the 3D view. Separate from the 3D view, which is unchanged.
- **3D for Compare folders**: the 3D dock works without git too, showing each folder's board as it is on disk (New, Old or Both). `kigit --3d --disk BOARD.kicad_pcb` does the same from the command line.
- Click a picture in a review, note or discussion to see it full size (in kigit and on the Reviews page). Obsidian's `![[picture.png]]` pictures now show in kigit too, not just on the Reviews page.
- Somewhere in the GUI there's a door. Something lives behind it. Hoo knows.
- **Notebook**: your own notes, as Markdown in `reviews/` (an Obsidian vault works as it is), in folders as deep as you like. A panel beside the viewer (or a tab of its own, still in touch with kigit's tab for pins): your folders browsed like files (in, and back up), search, rename and delete (deleting warns what goes and whether git still has it), the note (saved as you type), pins to parts not tied to a commit, the notes about whatever's pinned (counted on its button), N for a quick note about it, and Today's log (a line under today's date in `Logs.md`). On the Reviews page, nested folders are rows of sub-tabs.

### Changed

- Your activity is kept in the project (`reviews/activity/<you>/<computer>.json`) instead of the app folder, so it goes with the project through git and your laptops add up; one file per computer, so they never conflict. The heatmap can show you or everyone. (Activity counted by 0.2.2 in the app folder isn't moved.)

### Fixed

- Schematics saved by KiCad 6 (HackRF One's, say) failed with " is not a KiCad schematic": KiCad 6 named a sheet's properties "Sheet name" / "Sheet file", which kigit didn't read.
- Nets now match KiCad in two more cases: a local label and a global label with the same name on the same sheet are one net, and a `/` in a sheet name is written `{slash}` in net names.
- The GUI tests read and write files as UTF-8, so they pass on Windows too (they failed on a notebook log line).
- A picture added in kigit to a note in a folder (`Design Notes/...`) showed "No page" on the Reviews page: kigit keeps added files in `reviews/assets/`, and the page now looks there when a picture isn't next to the note.

## [0.2.2] - 2026-11-16

### Added

- **Your activity**: a button next to the bell shows a year of what you did in kigit (comparisons, reviews, discussions, replies, 3D views) as a GitHub-style heatmap, with streaks and your busiest day. Kept in the app folder (`activity.json`); `kigit uninstall --purge` deletes it, and says so.
- **Mentions**: a discussion shows where it's linked from ("Author B mentioned this in ..."), among its messages; the Reviews page has a "Mentioned in" list on discussions and reviews. When someone else links to a discussion you're in, the bell shows an @ (pulled mentions too). Worked out from the links, so nothing is written into the linked discussion.

### Fixed

- KiCad 8 works: the 3D view uses only the export options KiCad 8 has (it has no pads, solder mask or silkscreen in 3D, and kigit says so), and the landing page's board pictures are a 2D drawing (KiCad 8 has no 3D render). KiCad 9 and 10 work as before. A board saved by a newer KiCad than the one installed gets a clear message instead of KiCad's error, and KiCad 7 or older a "needs KiCad 8" one.
- On Windows with several KiCads installed, kigit picked by name ("8.0" before "10.0"); it now picks the newest.

## [0.2.1] - 2026-11-16

### Added

- The **Reviews page** is now a small docs site instead of one long page: tabs for Reviews, Discussions, each folder of your own notes in `reviews/`, and Tags; a sidebar of that tab's pages; one page per review, note and discussion with "On this page"; and a search box over everything that shows results as you type. The Reviews tab opens on the timeline, by month.
- Review and discussion text boxes are Markdown editors like GitHub's: Write and Preview tabs, a formatting toolbar (heading, bold, italic, quote, code, link, lists, task list; Ctrl+B, Ctrl+I, Ctrl+K), and any file added by paste, drop or click: pictures show inline, other files (datasheets, logs) become links.

- A note or discussion can be about several parts, nets or footprints, and pointed at something else if it was the wrong one: pin it in the viewer, then add it, or point at it instead (the button next to the note's chips, or the discussion's for whoever opened it); ✕ on a chip removes one.
- Rename a discussion you opened (the pencil by its title; the chat keeps the old title).
- Edit or delete your own messages in a discussion: the pencil on a message you wrote (it's then marked "edited"), and delete for your comments.
- Copy a link to a discussion (in it, or from its row in a review or the Discussions list) and paste it into a review or another discussion; clicking it opens the discussion. Right-click a commit to copy its review's link (which opens the review when clicked), its file path, or the commit hash. A link to a discussion or review that's gone warns you (pop-up, log and notifications).

- `kigit uninstall`: removes the installed kigit (asks first; `--purge` also removes the app folder). On Windows it starts the installer's uninstaller.
- A kigit logo: on `kigit.exe`, the Windows installer and its uninstall entry (`tools/make_logo.py` makes it).

### Changed

- `kigit gui` opens in the browser on Windows too; `--native` still opens its own window.
- Review is greyed out for the working tree and the first commit, with a line saying why (commit your changes first; the first commit has nothing before it).

### Fixed

- The discussion window closed when you pressed Send, if it was opened from the review panel.
- A review emptied of everything kept its file, so the commit list still marked the commit as reviewed. Writing it now removes the file, and empty review files don't count.

## [0.2.0] - 2026-11-15

### Added

- **Hide any panel, or open it in a new tab**: the commit list, the review panel and the comparison's sidebar fold to a rail on their edge (click it to bring the panel back), and the 3D dock folds to its bar; each is remembered. Each panel has a new-tab button too: the project in another kigit tab, the review on the Reviews page, the comparison or 3D view on its own.
- A discussion's **commit hashes are links**: one click compares the commit it was opened on with that commit (or with HEAD, from where it was opened) and shows what it's about in the viewer, even if it was removed since.
- **Commit reviews** in the GUI: pick a commit and press Review to see it against its parent and write down why it changed. A summary plus notes, each pointing at a net, footprint, part or bus pinned in the viewer (click to show it again), in Markdown with pasted images, links (a link button and Ctrl+K), LaTeX math (`$...$`, `$$...$$`) and tags, each stamped with when it was written and last edited. Press Write (or Ctrl+S) to save it as one Markdown file per commit in the `reviews/` folder next to the board, named by the review's ID, with `reviews/index.md` listing every review (ID, commit, date, author, subject); unwritten edits are kept as a draft until then. The **Reviews** button opens all of a project's reviews, and any Markdown notes of your own in `reviews/` (Obsidian links, embeds and tags included), as one page in a new tab, with search and tag filters.
- **Example project**: `kigit example [DIR]` (or **Try the example project** on the GUI's landing page) makes blinky, a small LED board with a git history in which each commit shows off something different: added, moved and changed parts and tracks, value changes, a net rename, a moved project folder, reviews, discussions and an uncommitted change. Shipped with every download; see the new "Try the Example" page.
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
- GUI panels (the commit list, the review panel, the viewer's sidebar and the 3D dock) **resize** by dragging their edge; double-click resets it, and the size is remembered.
- **Wrap messages** switch above the GUI's commit list, for reading long commit messages (remembered).
- `kigit --log` gives each commit's parent.
- Documentation site at [khalidowlwalid.github.io/kigit](https://khalidowlwalid.github.io/kigit/), built with MkDocs (Material): installation, how-to guides for the GUI, command line, PCB and schematic viewers and source panel, examples, and an architecture page.
- Demo videos and GIFs of the PCB and schematic diff.

- `THIRD_PARTY_NOTICES.md`: the licences of the libraries kigit is built with, shipped with it.

### Changed

- README rewritten to match the docs home page, with the detailed usage moved to the docs site, plus badges.

### Fixed

- The GUI's tests failed on Python 3.14 (NiceGUI's vbuild uses `pkgutil.find_loader`, removed in 3.14): the GUI now asks uv for Python 3.10 to 3.13.

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

[Unreleased]: https://github.com/KhalidOwlWalid/kigit/compare/v0.2.3...HEAD
[0.2.3]: https://github.com/KhalidOwlWalid/kigit/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/KhalidOwlWalid/kigit/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/KhalidOwlWalid/kigit/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/KhalidOwlWalid/kigit/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/KhalidOwlWalid/kigit/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/KhalidOwlWalid/kigit/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/KhalidOwlWalid/kigit/releases/tag/v0.1.0
