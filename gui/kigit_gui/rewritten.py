"""Reviews of rewritten commits.

Rebase, amend and squash replace commits with new ones (new hashes), so a
review can end up pointing at a commit no branch has any more: a stray.
kigit --rewritten says which commits are gone and which live commits have
the same author and author date (rebase and amend keep both), so most strays
can be moved for you. A squash makes a new author date, so its reviews are
brought into the squashed commit's review by hand (ReviewPanel).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import kigit, logs, review
from .review import Review


@dataclass
class Stray:
    path: Path
    review: Review
    exists: bool              # git still has the old commit
    matches: list[kigit.Moved]


async def find(project_dir: Path, listed: set[str]) -> list[Stray]:
    """Reviews whose commit is on no branch, tag or HEAD. `listed`: commits
    known to be live (the commit list), not asked about again."""
    files = review.all_reviews(project_dir)
    ask = [h for h in files if h not in listed]
    if not ask:
        return []
    try:
        found = await kigit.rewritten(str(project_dir), ask)
    except kigit.KigitError:
        return []  # already logged as a warning; nothing to offer
    strays = []
    for r in found:
        if r.live:
            continue
        try:
            strays.append(Stray(files[r.hash], review.load(files[r.hash]), r.exists, r.matches))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
    if strays:
        logs.log.info("%d review(s) of commits on no branch: %s", len(strays),
                      ", ".join(s.review.commit[:7] for s in strays))
    return strays


def move_all(project_dir: Path, moves: list[tuple[Stray, kigit.Moved]]) -> list[Path]:
    """Moves each stray's review to its new commit. Returns the files written."""
    mapping = {s.review.commit: m.hash for s, m in moves}
    written = []
    for s, m in moves:
        written.append(review.move(project_dir, s.path, m.hash, m.parent, m.subject, m.date[:16], m.author, mapping))
        logs.log.info("moved review %s: %s -> %s", s.path.name, s.review.commit[:7], m.short)
    return written


def squashed_into(stray: Stray, message: str) -> bool:
    """Whether a squashed commit's message names the stray's commit: git
    merge --squash lists each commit's hash, GitHub lists their subjects."""
    r = stray.review
    if r.commit[:7] in message:
        return True
    subject = review.one_line(r.subject)
    return bool(subject) and any(subject in review.one_line(line) for line in message.splitlines())
