# Bill of Materials

kigit makes your board's bill of materials when you ask for it: in the GUI with **BOM** in the header, or with `kigit bom` on the command line. Nothing runs in the background.

<figure markdown="span">
  ![The BOM page for owl_v1](../img/gui/bom.png)
  <figcaption>The BOM page: a line per part, its part number (or a note that it has none), searches on Digi-Key, Mouser and LCSC, and the part number you chose.</figcaption>
</figure>

## What's on a line

Parts with the same value, footprint, part numbers and DNP state share a line, with their quantity and references (in order: R2 before R10). Left out: power symbols, `#` references and parts marked *Exclude from bill of materials*. A part in several units (U1A, U1B) counts once.

Part numbers are read from the fields most people use, whatever the spelling: `MPN` (or `Manufacturer Part Number`, `MFR PN`...), `Manufacturer`, `DigiKey`, `Mouser` and `LCSC` (`LCSC Part #`...). Do-not-populate parts are those with KiCad's DNP flag, a `DNP` field, or the value `DNP` (as older projects did).

## Finding parts

Each line has **Digi-Key**, **Mouser** and **LCSC** links that open the site's search for:

- the line's own part number at that site, or its MPN;
- otherwise, for chip resistors, capacitors, inductors, ferrites and LEDs, the value and package: "10k 0603 resistor" (`10kR`, `5k1` and `4R7` are written the way distributors search: `10k`, `5.1k`, `4.7 ohm`);
- otherwise the value, which for an IC is usually its part name.

The links only open the sites in your browser: kigit itself doesn't contact anyone.

## Your picks

For a line without a part number, put the one you chose in **Your pick** (MPN, manufacturer, a note). It's saved as you type, in `kigit-bom.json` next to the board: commit it and your team sees the same picks. Picks are kept by value and footprint, so they survive renumbering. A part number in the schematic always wins over a pick.

**Needs a part number** filters to what's left to choose.

## Exporting

**Export CSV** writes a file for Digi-Key's BOM Manager or Mouser's BOM Tool (both let you match up the columns): quantity, manufacturer, MPN, Digi-Key, Mouser and LCSC part numbers, references, value, footprint. **Boards** multiplies the quantities; DNP parts are left out unless you tick **DNP in export**.

## Which revision

The working tree by default (the files on disk, saved or not committed). Tick one commit in the commit list first to get that commit's BOM instead.

## From the command line

```sh
kigit bom                      # the project in this folder, as a table
kigit bom HEAD~3               # at a commit
kigit bom --csv -o bom.csv     # CSV
kigit bom --json               # everything, with the search links
kigit bom path/to/x.kicad_sch  # a schematic, .kicad_pro, .kicad_pcb or folder
```

Without git it reads the files on disk; a revision then is an error.
