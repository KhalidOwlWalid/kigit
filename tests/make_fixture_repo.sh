#!/bin/sh
# Builds a throwaway git repo with the demo KiCad project, for the tests.
#
#   make_fixture_repo.sh DEST
#
# History (fixed dates, so date filters are testable):
#   2025-01-10  v1: first board        hw/demo.kicad_{pro,pcb,sch} (v1)
#   2025-02-01  docs only              README.md
#   2025-03-01  v2: board changes      hw/ -> v2 files
#   2025-04-01  move project folder    hw/ -> board/
set -eu

dest=$1
fixtures=$(cd "$(dirname "$0")/fixtures" && pwd)

rm -rf "$dest"
mkdir -p "$dest"
cd "$dest"
git init -q
git checkout -q -b main 2>/dev/null || true
git config user.email "tests@kigit.invalid"
git config user.name "kigit tests"
git config commit.gpgsign false

commit() { # DATE MESSAGE
    GIT_AUTHOR_DATE="$1T12:00:00" GIT_COMMITTER_DATE="$1T12:00:00" git commit -q -m "$2"
}

mkdir hw
cp "$fixtures/demo.kicad_pro" hw/
cp "$fixtures/v1/demo.kicad_pcb" "$fixtures/v1/demo.kicad_sch" hw/
git add -A
commit 2025-01-10 "v1: first board"

echo "Demo project for the kigit tests." > README.md
git add -A
commit 2025-02-01 "docs only"

cp "$fixtures/v2/demo.kicad_pcb" "$fixtures/v2/demo.kicad_sch" hw/
git add -A
commit 2025-03-01 "v2: add C1, move R2, widen a track"

git mv hw board
commit 2025-04-01 "move project folder"
