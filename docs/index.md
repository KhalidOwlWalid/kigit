# kigit

**kigit** shows what changed in a KiCad project between two git revisions. It reads the `.kicad_pcb` and `.kicad_sch` files straight out of git, matches every track, via, pad, part, wire and label, and writes a single self-contained HTML page where you can hover a trace to see its whole net: what was added, what was removed, and what moved.

## What you get

<div class="grid cards" markdown>

-   :material-expansion-card: [**PCB Viewer**](how-to-use/pcb-viewer.md)

    ---

    Hover a trace to highlight its net. Added copper in green, removed in red, moved in blue, with each net's length change.

-   :material-sitemap: [**Schematic Viewer**](how-to-use/schematic-viewer.md)

    ---

    Every sheet drawn with the same colours: parts whose value, footprint or connections changed, and pins that joined or left a net.

-   :material-file-compare: [**Source Panel**](how-to-use/source-panel.md)

    ---

    The changed lines of the KiCad files, old and new side by side, for whatever you hover.

-   :material-application: [**GUI**](how-to-use/gui.md)

    ---

    Open a project, pick two commits from its history and compare. No command line needed.

</div>

---

## Demonstration

<!-- TODO: add a screen recording to docs/img/ and embed it here, e.g.
<video autoplay loop muted controls width="100%">
  <source src="img/vid/demo.mp4" type="video/mp4">
</video>
-->

!!! note
    Screenshots and a demo video are coming.

---

## Quick start

```sh
cd path/to/my-board        # a KiCad project in a git repository
kigit HEAD~1               # the last commit vs your working tree
kigit gui                  # or pick commits in the GUI
```

See [Installation](installation.md) to get kigit, and [Overview](how-to-use/overview.md) for how it works.
