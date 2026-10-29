# Without Git

Compare two copies of a board directly, e.g. two saved versions of the same project. No git repository needed; the older file goes first:

```sh
kigit --files owl_v1_old/owl_v1.kicad_pcb owl_v1/owl_v1.kicad_pcb
kigit old.kicad_pcb new.kicad_pcb              # two board files = --files
```

The schematic next to each board is compared too. The viewer labels the two sides by file name, or by folder name when both files have the same name.

## In the GUI

Press **Compare folders** in the header and pick each copy's folder. kigit finds the board in each (and the schematic next to it), and the viewer opens as usual.

Opening a project that isn't in git offers the same thing, with that project already filled in.
