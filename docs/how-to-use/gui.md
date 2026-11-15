# GUI

```sh
kigit gui                  # start in the current folder
kigit gui ~/path/to/board  # or any folder
kigit gui --port 9000      # on a port of your choice
```

On Windows the GUI opens in its own window (Edge WebView2, built into Windows 10/11); on Linux it opens in your web browser. `--native` and `--browser` choose; if a window can't be opened, it says why and uses the browser. It only listens on 127.0.0.1, so it isn't reachable from the network.

It serves on port 8765, or the next free one when another kigit GUI already has it, so you can run several at once (say, one per project); the address it uses is printed when it starts. `--port N` picks the port yourself, and stops with a message if it's taken. Panel widths and other display settings are remembered per port.

## Steps

### 1. Open a project

Type a folder or press **Browse** (folders holding KiCad files are marked). kigit looks for a project in that folder and up to two levels below. It tells you if it finds none, if the project has no `.kicad_pcb`, or if it isn't in a git repository; if it finds several, it asks which one.

### 2. Pick two commits

All commits are listed, newest first, tagged **PCB** / **SCH** when they changed the board or schematic. The top entry is your working tree: HEAD plus any uncommitted changes. Hover a message to read all of it, or turn on **Wrap messages** (above the list) to show long messages on several lines; the date then sits under the commit hash. The setting is remembered.

- **Filter commits:** how many to list, a date range, and "only commits that changed the board or schematic". If the project folder was renamed or moved, its history is followed through the old folders too.
- **Diff commits manually:** type any two revisions git understands (hash, `HEAD~3`, branch, tag, or `LOCAL`), for when the commit you want isn't in the list.

### 3. Compare

kigit diffs the two and the viewer opens on the schematic, with the PCB one tab away.

### 3D view

Pick **one** commit (or the working tree at the top) and press **3D** to see that commit's board in 3D, as KiCad draws it: the board with its copper, pads, silkscreen, solder mask and the parts' 3D models. It isn't a comparison, just how the board looked then.

- Drag to rotate, right-drag (or Shift-drag) to pan, scroll to zoom.
- **Beside a comparison:** while comparing two commits, press **3D** in the header to dock the board in 3D next to the diff. **New**, **Old** or **Both** (side by side, views linked) picks which. Drag the divider to resize it (double-click resets); the button in its header puts it below the comparison instead of beside it, handy when the commit list and the review panel are open too. The first time it picks whichever leaves the comparison more room; after that it remembers. The :material-open-in-new: button opens it in a browser tab of its own instead (to put on another screen, say); the dock shrinks to a bar under the comparison, where New, Old and Both still choose what that tab shows. Close the tab, or press **Bring back**, and it's docked again where it was. If nothing opens, allow pop-ups for the kigit page.
- **Several at once:** pick up to four commits and press **3D** to see their boards side by side, oldest first. Turn, zoom or pan one and the others follow, so you see each board from the same angle; **Link views** at the bottom (or L) turns that off. Their models are made at the same time.
- If it feels slow, press **S** for render stats: how long after your input a frame is drawn, how long each redraw takes (CPU, and GPU where the browser can time it), the gaps between frames while you drag, dropped frames, draw calls and triangles, each as p50 / p95. **Copy** puts them on the clipboard as JSON, handy for a bug report.
- **Top**, **Bottom** and **3D** jump to those views, **Fit** brings the whole board back into view, and **Parts** hides or shows the parts. **Mask** and **Silk** hide the solder mask and the silkscreen, as KiCad's 3D viewer can: with the mask off the copper lies bare, so traces are easy to follow. Side by side, the other boards follow. Keys: T, B, 3, F, P, M (mask) and K (silk).

KiCad makes the model: kigit takes the board, its project file and any 3D model files in the repository out of that commit, and runs `kicad-cli pcb export glb` on them. That needs KiCad 8 or newer. kigit finds `kicad-cli` on your PATH or where the KiCad installer puts it; if it's somewhere else, set `KIGIT_KICAD_CLI` to its path. A big board takes a while the first time (about half a minute); after that, the same commit opens straight away for the rest of the session. Parts show when KiCad can find their 3D models: models in KiCad's own library, or files in the repository referenced with `${KIPRJMOD}`. A board saved by an older KiCad points at that version's library (`${KICAD8_3DMODEL_DIR}/...wrl`); kigit points those at your KiCad's library in its temporary copy (and at the `.step` models from KiCad 10 on, which has no `.wrl`), so they show too. Parts whose model file can't be found at all, such as an absolute path on someone else's computer, are left out, and kigit says how many.

### 4. Review a commit

Pick **one** commit and press **Review**. It's compared with the commit before it, and a review panel opens on the right, for writing down why the commit changed what it changed.

- **Summary:** the commit as a whole.
- **Notes:** click a net, footprint, part or bus in the viewer, then press **+ Note**: the note points at it. Click the note's tag later to show it again in the viewer. Without anything pinned, the note is a general one.
- Text is Markdown (links, lists, code). Paste or drop an image into a note to add it. To add a link, select the words to link and press the :material-link: button in the text box (or Ctrl+K), then give the address; web addresses typed as they are (`https://...`) become links by themselves. Notes can have tags: pick them from the Tags dropdown (reason, todo, question, risk, and any tag used elsewhere in the project), or type a new one and press Enter. A new tag becomes one lower-case word ("Needs Review" is saved as `needs-review`), as Obsidian expects.
- Math is LaTeX, as in Obsidian: `$f_c = \frac{1}{2\pi RC}$` in a line, or `$$ ... $$` on lines of its own for a displayed equation. Prices like "$5 and $10" stay text; write `\$` for a dollar sign next to something that would look like math.
- Each note shows when it was written and, if it was changed afterwards, when it was last edited.

Press **Write** (or Ctrl+S) to save. Until then the panel says "Unsaved changes"; if you switch to another commit first, your edits are kept as a draft for the session, and closing the page asks before throwing them away. Reviews are saved as one Markdown file per commit in the `reviews/` folder next to the board, with images in `reviews/assets/`. Each review gets an ID when first written, which is also its file name (`reviews/3f9a1c0e.md`), and `reviews/index.md` lists every review with its ID, commit, date, author and subject. They read fine on their own (GitHub, any editor) and can be committed with the project. Reviewed commits get a :material-rate-review: mark in the list. Comparing a commit with its parent opens its review as well.

#### After a rebase, amend or squash

These replace commits with new ones (new hashes), so a review can be left pointing at a commit no branch has any more. Its file isn't touched, but the commit list no longer shows it as reviewed. A plain merge (or fast-forward) keeps the commits as they are, so nothing changes then.

When the GUI finds such reviews it says so above the commit list:

- **Fix** lists them. A rebase or amend keeps a commit's author and author date, so the commit it became is found by those and picked for you; press **Move** to point the review at it (notes pinned in that commit follow it too). If that commit has a review already, the two are merged.
- A **squash** makes one new commit with a new date, so it can't be matched. Pick the squashed commit, press **Review**, then **Bring in reviews**: tick the reviews that went into it (those its message names, as `git merge --squash` and GitHub's "Squash and merge" do, are ticked already). Their summaries and notes are added to this review, and their files are removed when you press **Write**.

Git deletes replaced commits after a while (about a month), so a review you never move keeps its text but can no longer be matched automatically; Bring in still works.

**Reviews** in the header opens the project's notes and reviews as one page in a new tab, with a list to jump around, a search box and tag filters. Notes are any Markdown files of your own in `reviews/` (design decisions, test results, ...), for example written in Obsidian: frontmatter shows as properties, `tags:` and `#tags` work with the filter, `[[links]]` and `[text](other-note.md)` jump to other notes or to a review by its ID or commit message, links to other files in `reviews/` (a datasheet PDF, say) open them, and `![[picture.png]]` embeds a picture from `reviews/`. Reviews follow as a timeline, newest commit first, each note marked with what it points at (PCB or schematic, red if it was removed) and coloured by its tag. The page follows your system's light or dark theme, or the Theme button's choice; `/` jumps to the search, and the `#` next to a heading copies a link to it. It includes the pictures, so saving the page from the browser keeps a complete copy.

## Options

| Option | What it does |
| --- | --- |
| Include silkscreen | Compare and draw F/B silkscreen (bigger pages) |
| Include source | Add the [source panel](source-panel.md) (bigger pages) |
| Compare folders | Compare two copies of a project without git |

!!! tip
    The **log** button in the header shows the session's log file and its latest lines, handy for bug reports.
