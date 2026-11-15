"""Takes the GUI screenshots for the docs site by driving the real GUI in
headless Chrome, so they can be made again whenever the GUI changes.

    uv run --no-project --with playwright --with pillow python tools/docs_screenshots.py \\
        --project ~/Documents/Kicad/learn/CM5_MINIMA_REV2 \\
        --extra ~/Documents/Kicad/learn/jetson-nano-baseboard

What it does, all in a throwaway folder (your repositories aren't touched):

- clones each project's git repository (so screenshots show neutral paths),
- writes demo reviews into the main clone's reviews/ (on its newest commit
  that changed the board) and a design-decision note,
- amends the clone's HEAD after reviewing it, so the "rewritten commit"
  bar has something to show,
- starts `kigit gui` with its app data (recent projects, logs) in that
  folder, opens the projects, and screenshots each feature into --out.

Needs Google Chrome (Playwright's "chrome" channel) and, for the 3D shots,
KiCad 8+ (kicad-cli). Headless Chrome draws 3D in software: slow, but fine.
Use --only name,name to redo some.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
W, H = 1440, 900


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def clone(src: Path, into: Path) -> Path:
    """Clones src's repository; returns the same project folder in the clone."""
    top = Path(git(src, "rev-parse", "--show-toplevel"))
    dest = into / top.name
    subprocess.run(["git", "clone", "-q", str(top), str(dest)], check=True)
    git(dest, "remote", "remove", "origin")  # its branches would keep amended commits "live"
    git(dest, "config", "user.email", "docs@kigit.invalid")
    git(dest, "config", "user.name", "kigit docs")
    return dest / src.resolve().relative_to(top)


def board_of(project: Path) -> Path:
    boards = [p for p in project.glob("*.kicad_pcb") if not p.name.startswith(("~", "_"))]
    if not boards:
        sys.exit(f"no .kicad_pcb in {project}")
    return boards[0]


def note(title: str, body: str, anchor: dict | None, tags: list[str], created: str, edited: str = "") -> str:
    meta = {"id": os.urandom(4).hex(), "anchor": anchor, "tags": tags, "created": created}
    if edited:
        meta["edited"] = edited
    return f"## {title}\n<!-- kigit-note {json.dumps(meta)} -->\n\n{body.strip()}\n\n"


def review_file(rid: str, commit: str, parent: str, subject: str, date: str, author: str, summary: str,
                notes: str) -> str:
    return (f"---\nid: {rid}\ncommit: {commit}\nparent: {parent}\nsubject: {subject}\ndate: {date}\n"
            f"author: {author}\ncreated: 2026-11-10 09:12\nupdated: 2026-11-12 18:40\n---\n\n{summary.strip()}\n\n{notes}")


def seed_reviews(project: Path, kigit: str) -> dict:
    """Demo reviews in the clone. Returns the commits used."""
    board = board_of(project)
    rel = board.name
    log = git(project, "log", "--format=%H|%P|%s|%ci|%an", "--", "*.kicad_pcb").splitlines()
    commit, parents, subject, date, author = log[0].split("|", 4)
    parent = parents.split()[0]
    data = json.loads(subprocess.run([kigit, "--no-log", "-q", "--json", "-o", "-", "-C", str(board),
                                      f"{parent}..{commit}"], capture_output=True, text=True, check=True).stdout)
    fps = data.get("pcb", data).get("footprints", [])
    refs = [f["ref"] for f in fps if f.get("ref") and not f["ref"].startswith("kibuzzard")]
    seen = {"old": parent, "new": commit, "side": "new"}
    a1 = {"tab": "pcb", "kind": "footprint", "name": refs[0], "seen": seen}
    a2 = {"tab": "pcb", "kind": "footprint", "name": refs[1], "seen": seen} if len(refs) > 1 else None
    a3 = {"tab": "sch", "kind": "net", "name": "GND", "seen": seen}
    notes = (note(f"Updated {refs[0]}'s 3D model",
                  "The old model pointed at a library path that only existed on one machine. It now uses "
                  "KiCad's own library, so the 3D view and the STEP export show the part.\n\n"
                  "- [x] checked in the 3D viewer\n- [ ] re-export the STEP for the enclosure",
                  a1, ["reason", "todo"], "2026-11-10 09:20", "2026-11-12 18:40")
             + (note(f"{refs[1]} footprint swapped", "Same pinout, smaller package. Keep the courtyard "
                     "clear of the mounting hole: see [[Mounting holes]].", a2, ["risk"], "2026-11-10 09:31")
                if a2 else "")
             + note("Ground return", "Cut-off of the input filter: $f_c = \\frac{1}{2\\pi RC} \\approx 1.6\\,kHz$ "
                    "with $R = 1\\,k\\Omega$, $C = 100\\,nF$.\n\nDatasheet: https://www.ti.com/lit/ds/symlink/tps62133.pdf",
                    a3, ["question"], "2026-11-11 14:05"))
    rdir = project / "reviews"
    (rdir / "decisions").mkdir(parents=True, exist_ok=True)
    (rdir / "3f9a1c0e.md").write_text(review_file(
        "3f9a1c0e", commit, parent, subject, date[:16], author,
        "Brings every part's 3D model back: the board had library paths from an older KiCad and from one "
        "laptop. Nothing electrical changed.", notes))
    (rdir / "decisions" / "Mounting holes.md").write_text(
        "---\ntags: [decision, mechanical]\nstatus: accepted\n---\n# Mounting holes\n\nM2.5 holes, 3.5 mm "
        "from each edge, to fit the standard carrier spacing. #enclosure\n\n| Hole | X | Y |\n|---|---|---|\n"
        "| H1 | 3.5 | 3.5 |\n| H2 | 61.5 | 3.5 |\n")
    # A reviewed HEAD, then amended: the GUI finds its review a new home.
    head = git(project, "rev-parse", "HEAD")
    if head != commit:
        hp = git(project, "rev-parse", "HEAD~1")
        (rdir / "5be0d2a7.md").write_text(review_file(
            "5be0d2a7", head, hp, git(project, "log", "-1", "--format=%s"), "2026-11-12 10:00", author,
            "Last tidy-up before ordering.", note("BOM checked", "All parts in stock.", None, ["reason"],
                                                   "2026-11-12 10:05")))
        git(project, "commit", "-q", "--amend", "-m", git(project, "log", "-1", "--format=%s") + " (reworded)")
    return {"commit": commit, "parent": parent, "rel": rel}


class Shots:
    def __init__(self, out: Path, only: set[str]) -> None:
        self.out, self.only, self.taken = out, only, []

    def want(self, name: str) -> bool:
        return not self.only or name in self.only

    def save(self, name: str, take) -> None:
        if not self.want(name):
            return
        path = self.out / f"{name}.png"
        take(path)
        img = Image.open(path)
        img.save(path, optimize=True)  # smaller files, same pixels
        self.taken.append(name)
        print(f"  {name}.png  {img.size[0]}x{img.size[1]}  {path.stat().st_size // 1024} KB", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", required=True, help="KiCad project folder in a git repository (main screenshots)")
    ap.add_argument("--extra", action="append", default=[], help="more projects, for the landing page")
    ap.add_argument("--kigit", default=str(ROOT / "build" / "kigit"))
    ap.add_argument("--out", default=str(ROOT / "docs" / "img" / "gui"))
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--only", default="", help="comma-separated screenshot names to take")
    ap.add_argument("--keep", action="store_true", help="keep the work folder")
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shots = Shots(out, {s for s in a.only.split(",") if s})
    work = Path(tempfile.mkdtemp(prefix="kigit-docs-"))
    print("work folder:", work)
    project = clone(Path(a.project).expanduser(), work)
    extras = [clone(Path(e).expanduser(), work) for e in a.extra]
    seeded = seed_reviews(project, a.kigit)
    (work / "start").mkdir()

    env = dict(os.environ, KIGIT_LOG_DIR=str(work / "state" / "log"))
    gui = subprocess.Popen([a.kigit, "gui", str(work / "start"), "--port", str(a.port), "--no-browser"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    base = f"http://127.0.0.1:{a.port}"
    try:
        for _ in range(120):
            try:
                urllib.request.urlopen(base, timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        drive(base, project, extras, seeded, shots)
    finally:
        os.killpg(gui.pid, signal.SIGTERM)
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    print(f"{len(shots.taken)} screenshots in {out}")


def drive(base: str, project: Path, extras: list[Path], seeded: dict, shots: Shots) -> None:
    short = seeded["commit"][:7]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, color_scheme="dark")
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept())  # "leave with unsaved edits?" when reloading

        def go_home() -> None:
            page.goto(base)
            page.get_by_text("Recent projects", exact=True).wait_for(timeout=60000)

        def open_project(folder: Path) -> None:
            page.get_by_placeholder("KiCad project folder").fill(str(folder))
            page.locator(".q-header").get_by_role("button", name="Open", exact=True).click()
            page.get_by_text("Pick two commits on the left").first.wait_for(timeout=60000)
            page.wait_for_timeout(800)

        def pick(*hashes: str) -> None:
            for h in hashes:
                page.locator("tbody tr", has_text=h[:7]).first.locator(".q-checkbox").click()

        def left(name: str):
            return page.locator(".q-drawer--left").get_by_role("button", name=name, exact=True)

        def viewer_ready(part: str = "/diffs/") -> None:
            page.wait_for_function(f"() => [...document.querySelectorAll('iframe')].some(f => f.src.includes('{part}'))",
                                   timeout=120000)
            page.wait_for_timeout(2500)

        def ready_3d(n: int = 1) -> None:
            page.wait_for_function("""(n) => { const fs = []; const walk = (w) => { for (const f of w.document.querySelectorAll('iframe')) {
                  try { if (f.contentWindow.kigit3dReady) fs.push(f); walk(f.contentWindow); } catch {} } };
                  walk(window); return fs.length >= n; }""", arg=n, timeout=600000)
            page.wait_for_timeout(2000)

        def close_dialog() -> None:
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)

        # ---- every project opened once (the landing page is taken last,
        # once there are comparisons to resume)
        go_home()
        for folder in extras:
            open_project(folder)

        # ---- the project: commits, a comparison
        go_home()
        open_project(project)
        shots.save("commits", lambda f: page.screenshot(timeout=180000, path=f))
        if page.locator("text=on no branch any more").count():
            shots.save("review-strays", lambda f: page.screenshot(timeout=180000, path=f, clip={"x": 0, "y": 56, "width": 480,
                                                                              "height": 560}))
            page.get_by_role("button", name="Fix").click()
            page.get_by_text("Reviews of rewritten commits").wait_for()
            page.wait_for_timeout(600)
            shots.save("review-fix", lambda f: page.locator(".q-dialog .q-card").last.screenshot(timeout=180000, path=f))
            close_dialog()

        pick(seeded["parent"], seeded["commit"])
        left("Compare").click()
        viewer_ready()
        shots.save("compare", lambda f: page.screenshot(timeout=180000, path=f))

        # ---- a review (comparing a commit with its parent opens it)
        frame = page.frame_locator("iframe").first
        frame.locator('[data-tab="pcb"]').click()
        page.wait_for_timeout(1500)
        frame.locator("#fpList [data-fp]").first.click()
        page.wait_for_timeout(1200)
        shots.save("review-panel", lambda f: page.screenshot(timeout=180000, path=f))
        page.locator(".q-drawer--right").get_by_role("button", name="Note", exact=True).click()
        page.wait_for_timeout(600)
        page.locator(".q-drawer--right .q-select", has_text="Tags").last.locator("input").click()
        page.wait_for_timeout(800)
        shots.save("review-tags", lambda f: page.screenshot(timeout=180000, path=f, clip={"x": W - 500, "y": 300, "width": 500,
                                                                            "height": 520}))
        page.keyboard.press("Escape")

        # ---- the reviews page, in its own tab
        with ctx.expect_page() as info:
            page.get_by_role("button", name="Reviews", exact=True).click()
        doc = info.value
        doc.set_viewport_size({"width": W, "height": H})
        doc.wait_for_load_state()
        doc.wait_for_timeout(1500)
        shots.save("reviews-page", lambda f: doc.screenshot(timeout=180000, path=f))
        doc.locator(".review").first.scroll_into_view_if_needed()
        doc.wait_for_timeout(800)
        shots.save("reviews-page-timeline", lambda f: doc.screenshot(timeout=180000, path=f))
        doc.close()

        # ---- 3D: one commit (with its build progress), mask off
        go_home()
        open_project(project)
        pick(seeded["commit"])
        left("3D").click()
        page.wait_for_timeout(5000)
        if page.locator("text=/ s (so far|of about)/").count():
            shots.save("3d-building", lambda f: page.screenshot(timeout=180000, path=f))
        ready_3d()
        shots.save("3d-view", lambda f: page.screenshot(timeout=180000, path=f))
        src3d = page.locator("iframe").first.get_attribute("src")
        f3d = page.frame_locator("iframe").first
        f3d.locator("[data-view=top]").dispatch_event("click")
        f3d.locator("#parts").dispatch_event("click")
        f3d.locator("#mask").dispatch_event("click")
        page.wait_for_timeout(4000)
        shots.save("3d-mask-off", lambda f: page.screenshot(timeout=180000, path=f))

        # ---- notifications (the missing 3D parts, if any) and shortcuts
        page.locator("button:has(i:text('notifications'))").click()
        page.get_by_text("Notifications", exact=True).first.wait_for()
        page.wait_for_timeout(800)
        shots.save("notifications", lambda f: page.locator(".q-dialog .q-card").last.screenshot(timeout=180000, path=f))
        close_dialog()
        page.mouse.click(W // 2, 30)
        page.keyboard.press("?")
        page.get_by_text("Shortcuts", exact=True).first.wait_for()
        page.wait_for_timeout(800)
        shots.save("shortcuts", lambda f: page.locator(".q-dialog .q-card").last.screenshot(timeout=180000, path=f))
        close_dialog()

        # ---- render stats
        stats = ctx.new_page()
        stats.goto(base + src3d + "&stats=1")
        stats.wait_for_function("() => window.kigit3dReady", timeout=600000)
        stats.mouse.move(700, 450)
        stats.mouse.down()
        stats.mouse.move(760, 430, steps=6)
        stats.mouse.up()
        stats.wait_for_timeout(4000)
        shots.save("3d-stats", lambda f: stats.screenshot(timeout=180000, path=f))
        stats.close()

        # ---- two commits side by side
        go_home()
        open_project(project)
        pick(seeded["parent"], seeded["commit"])
        left("3D").click()
        ready_3d(2)
        shots.save("3d-side-by-side", lambda f: page.screenshot(timeout=180000, path=f))

        # ---- the 3D dock beside a comparison, then popped out (a fresh page:
        # the side-by-side boards above keep a software renderer busy)
        go_home()
        open_project(project)
        pick(seeded["parent"], seeded["commit"])
        left("Compare").click()
        viewer_ready()
        page.locator(".q-header").get_by_role("button", name="3D").click()
        page.mouse.move(W // 2, H - 10)  # no tooltip
        ready_3d()
        shots.save("3d-dock", lambda f: page.screenshot(timeout=180000, path=f))
        with ctx.expect_page() as info:
            page.locator("button:has(i:text('open_in_new'))").first.click()
        tab = info.value
        page.bring_to_front()  # a background tab isn't drawn, so it can't be screenshot
        page.get_by_text("in another tab").first.wait_for(timeout=60000)
        page.mouse.move(W // 2, H - 10)  # no tooltip
        page.wait_for_timeout(1500)
        shots.save("3d-popped", lambda f: page.screenshot(timeout=180000, path=f))
        tab.close()
        page.wait_for_timeout(1500)

        # ---- the landing page: started fresh, nothing open behind it
        go_home()
        page.wait_for_function("() => document.querySelectorAll('.q-card img').length >= 1 && "
                               "[...document.querySelectorAll('.q-card img')].every(i => i.complete && i.naturalWidth)",
                               timeout=180000)
        page.mouse.move(W - 20, H - 20)  # no tooltip
        page.wait_for_timeout(1500)
        shots.save("landing", lambda f: page.screenshot(timeout=180000, path=f))

        # ---- the session log in its own tab
        log = ctx.new_page()
        log.goto(base + "/log")
        log.wait_for_timeout(2500)
        log.locator("#q").fill("compare")
        log.wait_for_timeout(800)
        shots.save("log-tab", lambda f: log.screenshot(timeout=180000, path=f, clip={"x": 0, "y": 0, "width": W,
                                                                                      "height": 200}))
        browser.close()


if __name__ == "__main__":
    main()
