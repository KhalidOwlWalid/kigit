# Moved or Renamed Boards

If the board isn't at the same path in one of the revisions (you moved `hardware/owl.kicad_pcb` to `pcb/owl_v1.kicad_pcb`, say), kigit searches that revision for every `.kicad_pcb` and picks the one sharing the most footprints and nets with the latest version of your board.

```sh
kigit 259cd18..HEAD
```

```
warning: pcb/owl_v1.kicad_pcb doesn't exist in 259cd18, using hardware/owl.kicad_pcb
         instead (98% match: 62 of 63 footprints and 74 of 74 nets are the same ...)
warning: the board was moved or renamed: hardware/owl.kicad_pcb (259cd18) -> pcb/owl_v1.kicad_pcb (f038da9)
```

The same warning shows in the viewer, and the comparison carries on.

!!! warning
    If nothing is at least 25% similar, kigit stops and lists the boards it found instead of guessing.

The GUI follows the move too: the commit list includes the commits from before the folder was renamed.
