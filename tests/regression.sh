#!/bin/sh
# Optional regression check on real KiCad projects: kigit's schematic nets
# must match KiCad's own netlist (kicad-cli) exactly.
#
#   KIGIT_REGRESSION_PROJECTS="~/boards/a/a.kicad_pcb:~/boards/b/b.kicad_pcb" ctest -L regression
#
# Each entry is a .kicad_pcb (or its folder) inside a git repo; the working
# tree is checked. Skipped (exit 77) if the variable is unset or kicad-cli
# isn't installed.
set -u
kigit=$1
[ -n "${KIGIT_REGRESSION_PROJECTS:-}" ] || { echo "KIGIT_REGRESSION_PROJECTS not set, skipping"; exit 77; }
command -v kicad-cli >/dev/null 2>&1 || { echo "kicad-cli not found, skipping"; exit 77; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
failed=0
old_ifs=$IFS
IFS=:
for project in $KIGIT_REGRESSION_PROJECTS; do
    IFS=$old_ifs
    project=$(eval echo "$project") # expand ~
    case $project in
        *.kicad_pcb) board=$project ;;
        *) board=$(ls "$project"/*.kicad_pcb 2>/dev/null | head -1) ;;
    esac
    sch="${board%.kicad_pcb}.kicad_sch"
    echo "== $board"
    if ! (cd "$(dirname "$sch")" && kicad-cli sch export netlist -o "$tmp/net" "$(basename "$sch")" >/dev/null 2>&1); then
        echo "   kicad-cli couldn't export the netlist"; failed=1; continue
    fi
    if "$kigit" --check-netlist "$tmp/net" -C "$board" | tail -1 | grep -q " 0 same pins but different name, 0 different"; then
        "$kigit" --check-netlist "$tmp/net" -C "$board" | tail -1
    else
        "$kigit" --check-netlist "$tmp/net" -C "$board"; failed=1
    fi
done
exit $failed
