# GUI

```sh
kigit gui                  # start in the current folder
kigit gui ~/path/to/board  # or any folder
```

On Windows the GUI opens in its own window (Edge WebView2, built into Windows 10/11); on Linux it opens in your web browser. `--native` and `--browser` choose; if a window can't be opened, it says why and uses the browser. It only listens on 127.0.0.1, so it isn't reachable from the network.

## Steps

### 1. Open a project

Type a folder or press **Browse** (folders holding KiCad files are marked). kigit looks for a project in that folder and up to two levels below. It tells you if it finds none, if the project has no `.kicad_pcb`, or if it isn't in a git repository; if it finds several, it asks which one.

### 2. Pick two commits

All commits are listed, newest first, tagged **PCB** / **SCH** when they changed the board or schematic. The top entry is your working tree: HEAD plus any uncommitted changes. Hover a message to read all of it.

- **Filter commits:** how many to list, a date range, and "only commits that changed the board or schematic". If the project folder was renamed or moved, its history is followed through the old folders too.
- **Diff commits manually:** type any two revisions git understands (hash, `HEAD~3`, branch, tag, or `LOCAL`), for when the commit you want isn't in the list.

### 3. Compare

kigit diffs the two and the viewer opens on the schematic, with the PCB one tab away.

### 4. Review a commit

Pick **one** commit and press **Review**. It's compared with the commit before it, and a review panel opens on the right, for writing down why the commit changed what it changed.

- **Summary:** the commit as a whole.
- **Notes:** click a net, footprint, part or bus in the viewer, then press **+ Note**: the note points at it. Click the note's tag later to show it again in the viewer. Without anything pinned, the note is a general one.
- Text is Markdown (links, lists, code). Paste or drop an image into a note to add it. Notes can have tags (reason, todo, question, risk, or your own).

Reviews are saved as you type, one Markdown file per commit in `reviews/` next to the board, with images in `reviews/assets/`. They read fine on their own (GitHub, any editor) and can be committed with the project. Reviewed commits get a :material-rate-review: mark in the list. Comparing a commit with its parent opens its review as well.

## Options

| Option | What it does |
| --- | --- |
| Include silkscreen | Compare and draw F/B silkscreen (bigger pages) |
| Include source | Add the [source panel](source-panel.md) (bigger pages) |
| Compare folders | Compare two copies of a project without git |

!!! tip
    The **log** button in the header shows the session's log file and its latest lines, handy for bug reports.
