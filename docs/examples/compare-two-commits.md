# Compare Two Commits

Review what the last commit changed on the board:

```sh
cd ~/boards/owl_v1
kigit HEAD~1..HEAD
```

kigit prints a summary and opens the page:

```
schematic: parts +1 -0, 8 changed electrically, 1 fields only, 0 only moved; 3 nets changed, 0 renamed, 1 only redrawn
```

Then:

1. On the **PCB** tab, hover a green or red trace to see its whole net and how its length changed.
2. Click to pin the net, and `Esc` to let go.
3. Switch to the **Schematic** tab and hover an amber part to see what changed on it.

## Before you commit

Without a range, kigit compares HEAD with your working tree, so you can check your own changes before committing:

```sh
kigit
```

## With the file text

```sh
kigit --source HEAD~1..HEAD
```

adds the [source panel](../how-to-use/source-panel.md): hover anything to see its lines in the old and new file.
