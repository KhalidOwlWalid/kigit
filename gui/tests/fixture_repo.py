"""Builds the demo git repo for the GUI tests (same history as the C++ tests'
make_fixture_repo in tests/cpp/helpers.cpp). Works on Windows, Linux, macOS."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


def make_fixture_repo(dest: Path) -> Path:
    """Creates the repo in `dest`; returns the project folder (dest/board)."""
    def git(*args: str, date: str | None = None) -> None:
        env = dict(os.environ)
        if date:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{date}T12:00:00"
        subprocess.run(["git", "-C", str(dest), *args], check=True, capture_output=True, env=env)

    def copy(src: str, to: str) -> None:
        (dest / to).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / src, dest / to)

    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    git("init", "-q")
    git("checkout", "-q", "-b", "main")
    git("config", "user.email", "tests@kigit.invalid")
    git("config", "user.name", "kigit tests")
    git("config", "commit.gpgsign", "false")
    git("config", "core.autocrlf", "false")

    copy("demo.kicad_pro", "hw/demo.kicad_pro")
    copy("v1/demo.kicad_pcb", "hw/demo.kicad_pcb")
    copy("v1/demo.kicad_sch", "hw/demo.kicad_sch")
    git("add", "-A")
    git("commit", "-q", "-m", "v1: first board", date="2025-01-10")

    (dest / "README.md").write_text("Demo project for the kigit tests.\n")
    git("add", "-A")
    git("commit", "-q", "-m", "docs only", date="2025-02-01")

    copy("v2/demo.kicad_pcb", "hw/demo.kicad_pcb")
    copy("v2/demo.kicad_sch", "hw/demo.kicad_sch")
    git("add", "-A")
    git("commit", "-q", "-m", "v2: add C1, move R2, widen a track", date="2025-03-01")

    git("mv", "hw", "board")
    git("commit", "-q", "-m", "move project folder", date="2025-04-01")
    return dest / "board"
