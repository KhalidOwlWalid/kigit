"""Finding where a squashed commit's reviews went (rewritten.py)."""

from pathlib import Path

from kigit_gui import rewritten
from kigit_gui.review import Review


def stray(commit: str, subject: str) -> rewritten.Stray:
    return rewritten.Stray(Path("x.md"), Review(commit=commit, subject=subject), True, [])


def test_squashed_into_reads_the_message() -> None:
    c = "0123456789abcdef0123456789abcdef01234567"
    # git merge --squash lists the hashes; GitHub lists "* subject" lines.
    assert rewritten.squashed_into(stray(c, "x"), "Squashed commit of the following:\n\ncommit " + c)
    assert rewritten.squashed_into(stray(c, "v2: add C1"), "Board rev B (#12)\n\n* v2: add  C1\n* tidy")
    assert not rewritten.squashed_into(stray(c, "v2: add C1"), "Something else")
    assert not rewritten.squashed_into(stray(c, ""), "anything")
