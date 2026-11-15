# Command Line

## Choosing revisions

```sh
kigit                      # HEAD vs the working tree
kigit HEAD~3               # HEAD~3 vs the working tree
kigit c46da63..HEAD        # two commits
kigit v1.0 v1.1 board.kicad_pcb
```

If you give the newer revision first, kigit swaps them so "added" always means "added in the newer revision".

## Choosing the project

Run it inside a project folder, or point at one from anywhere with `--kicad-repo` (short: `-C`):

```sh
kigit -C ~/boards/owl HEAD~1                 # finds the board in subfolders
kigit -C path/to/board.kicad_pro HEAD~1      # a .kicad_pro or .kicad_pcb works too
```

## Common options

| Option | What it does |
| --- | --- |
| `-o FILE` | Write the page here (`-o -` for stdout) |
| `-n` | Don't open a browser |
| `-s`, `--stats` | Print every changed net (and cosmetic schematic changes) |
| `--json` | Write the data as JSON instead of the page |
| `--silkscreen` | Compare and draw silkscreen |
| `--source` | Add the [source panel](source-panel.md) |
| `--files OLD NEW` | Compare two files, no git needed |
| `--3d [REV] -o FILE.glb` | The board at REV (default: working tree) as a 3D model, made by KiCad ([3D View](3d-view.md#from-the-command-line)) |
| `--render -o FILE.png` | A picture of the board on disk, made by KiCad |
| `-V` | Print the log to the console, with debug lines |
| `--log-dir DIR`, `--no-log` | Where the log goes, or no log |

Run `kigit --help` for the full list.

## The example project

```sh
kigit example [DIR]
```

Makes the [example project](../example.md) (a git repository) in DIR (default: `./kigit-example`) and prints its project folder. It won't write over an existing folder.

## The GUI

```sh
kigit gui [FOLDER] [--port N] [--native | --browser]
```

Starts the [GUI](gui.md) in FOLDER (default: here). Started outside a KiCad project, it opens on your recent projects. `--port N` picks the port (default: 8765 or the next free one); `--native` / `--browser` choose a window of its own or your browser.

## Scripting

What the GUI uses, if you want to build on it:

```sh
kigit --projects [--depth N]    # KiCad projects in the folder and below, as JSON
kigit --log [--max N] [--since DATE] [--until DATE] [--kicad-only]
                                # commits (+ uncommitted changes), as JSON
kigit --3d [REV] -o board.glb  # the board at REV (default: working tree) in 3D,
                                # made by kicad-cli (KiCad 8+); prints the path
kigit --render -o board.png    # a picture of the board on disk (top view), by kicad-cli
kigit --rewritten HASH...       # still on a branch? if not, commits with the same
                                # author and date (where a rebase put it), as JSON
kigit -n -o - A..B              # the viewer page on stdout
kigit -n --json -o - A..B       # the data on stdout
```

## Logs

Every run keeps a log named after when it started, in the `log/` folder of kigit's [app folder](../app-folder.md):

| Platform | Default folder |
| --- | --- |
| Linux | `~/.local/state/kigit/log/` |
| Windows | `%LOCALAPPDATA%\kigit\log\` |

`--log-dir DIR` (or the `KIGIT_LOG_DIR` environment variable) puts them elsewhere; `--no-log` writes none; `-V` also prints the log to the console.
