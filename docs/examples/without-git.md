# Without Git

Compare two copies of a board directly, e.g. two saved versions of the same project. No git repository needed; the older file goes first:

```sh
kigit --files owl_v1_old/owl_v1.kicad_pcb owl_v1/owl_v1.kicad_pcb
kigit old.kicad_pcb new.kicad_pcb              # two board files = --files
```

The schematic next to each board is compared too. The viewer labels the two sides by file name, or by folder name when both files have the same name.

## In the GUI

Press **Compare folders** in the header and pick each copy's folder. kigit finds the board in each (and the schematic next to it), and the viewer opens as usual. **3D** in the header shows the boards in 3D beside it, as for commits: **New**, **Old** or **Both** (KiCad makes each from the board file in that folder, with the 3D models in the folder).

Opening a project that isn't in git offers the same thing, with that project already filled in.

## BOM without git

**BOM** in the header works without git too, from the files on disk:

- With a project open that isn't in git, it's that project's BOM.
- While two folders are compared, it's the **newer** folder's BOM, even if you had a git project open before.

Everything on the BOM page works as usual: lookups, writing part numbers into the schematic (with a backup in `.kigit/bom-backup/`), builds, carts and the inventory. Only what needs git is missing: there are no commits to pick, and a note's **Commit** button has nothing to list.
