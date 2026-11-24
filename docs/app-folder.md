# App Folder

kigit keeps a few files of its own (logs, your recent projects, the GUI's Python environment) in one folder per user, the **app folder**. Nothing in it is part of your projects, and it's safe to delete.

## Where it is

=== "Windows"

    ```text
    %LOCALAPPDATA%\kigit
    ```

    Usually `C:\Users\<you>\AppData\Local\kigit`. To open it, press ++win+r++, type `%LOCALAPPDATA%\kigit` and press Enter.

=== "Linux"

    ```text
    ~/.local/state/kigit
    ```

    Or `$XDG_STATE_HOME/kigit` if you've set `XDG_STATE_HOME`. To open it:

    ```sh
    xdg-open ~/.local/state/kigit
    ```

In the GUI, the :material-receipt-text: log button shows the log's full path and has an **Open folder** button.

## What's in it

| Path | What it is | Written by |
| --- | --- | --- |
| `log/` | A log for every run, named after when it started (`kigit_2026-11-15_14-03-12_1234.log`, `kigit-gui_...`). Old logs are kept. | the command line and the GUI |
| `sessions.json` | Your [recent projects](how-to-use/gui.md#landing-page): each project opened and the last two commits compared there | the GUI |
| `thumbnails/` | The board pictures on the landing page, one per project | the GUI (with KiCad) |
| `mentions-seen.json` | Which [mentions](how-to-use/reviews.md#mentions) of your discussions you've been told about, per project (for the bell) | the GUI |
| `3d-build-times.json` | How long each board's [3D model](how-to-use/3d-view.md#making-the-model) took to make, for the progress bar | the GUI |
| `parts-keys.json` | For [part lookups](how-to-use/bom.md#keys): Digi-Key's site and currency. Your keys themselves are in your system's keyring; only without one are they here (readable only by you, not encrypted) | `kigit bom --set-key` |
| `parts-cache.json` | Mouser's, Digi-Key's and LCSC's answers to part lookups, used for a day (dropped after a week) | `kigit bom --lookup` |
| `parts-lcsc/` | The LCSC parts data from [jlcparts](how-to-use/bom.md#lcsc-with-no-key): `search-index.tsv.gz` (about 10 MB, downloaded once a day) and `shards/` (the details of parts you looked up). Safe to delete | `kigit bom --lookup`, `--lcsc-refresh` |
| `inventory.json` | Where your [inventory](how-to-use/bom.md#inventory) CSV is, and a copy of what was last read. The inventory itself is your CSV, wherever you keep it: not in here | the GUI |
| `bom-columns.json` | Which columns the [BOM page](how-to-use/bom.md) shows in Buy and in Assemble, if you changed them (**Columns** → **Reset to default** goes back) | the GUI |
| `gui-env/` | The GUI's Python and packages, set up the first time you run `kigit gui` | the installed kigit |
| `example/` | The [example project](example.md), if you tried it from the GUI | the GUI |

`gui-env/` is only there for an installed kigit (the Windows installer or zip, the Linux download); one built from source uses `gui/.venv` in the source folder instead.

## Moving it

- `KIGIT_LOG_DIR` (an environment variable) moves the **logs** to that folder. The GUI then keeps `sessions.json`, `thumbnails/` and `3d-build-times.json`, and the command line its `parts-*.json`, in the folder *above* it, so `KIGIT_LOG_DIR=D:\kigit\log` puts them in `D:\kigit`.
- `--log-dir DIR` moves only the logs, for that run. `--no-log` writes none.

## Deleting it

`kigit uninstall --purge` deletes it (after listing what's in it and asking). Everything in the app folder can go. Deleting it forgets your recent projects, their pictures, the 3D build times, your parts API keys and the logs; `gui-env/` is set up again the next time you start the GUI (that takes about a minute, as on the first start). Your projects and their [reviews](how-to-use/reviews.md) aren't in it. One thing to keep in mind: the [example project](example.md), if you made it from the GUI, lives in here (`example/`), so anything you wrote in it goes too; copy it somewhere else first to keep it.

## What isn't in it

| What | Where |
| --- | --- |
| Your [activity](how-to-use/gui.md#your-activity) (the heatmap) | `reviews/activity/<you>/<computer>.json` in each project |
| Comparison pages made by the command line | `.kigit/` next to the board (or wherever `-o` says) |
| [Reviews](how-to-use/reviews.md) | `reviews/` next to the board, in your project |
| The GUI's comparison pages and 3D models | a temporary folder (`kigit-gui-...` in your system's temp folder), for that session |
| Panel widths, "Wrap messages" and other display settings | your browser's storage for the GUI's page, one set per [port](how-to-use/gui.md) |
