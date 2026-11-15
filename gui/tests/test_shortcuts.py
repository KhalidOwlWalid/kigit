"""The shortcuts list (shortcuts.py) matches the code that handles them."""

from pathlib import Path

from kigit_gui import shortcuts

REPO = Path(__file__).resolve().parents[2]


def test_every_shortcut_is_still_handled_where_it_says() -> None:
    """A shortcut renamed or removed in the code fails here, so the list in
    the header stays true."""
    for title, _, items in shortcuts.GROUPS:
        for sc in items:
            file, code = sc.where
            assert file and code, f"{title}: {sc.keys} says nowhere where it's handled"
            assert code in (REPO / file).read_text(encoding="utf-8"), f"{title}: {sc.keys} not in {file}: {code}"


def test_keys_html() -> None:
    sc = shortcuts.Shortcut(("Ctrl+S", "<x>"), "Write")
    assert shortcuts.keys_html(sc) == '<kbd>Ctrl+S</kbd> <span class="or">or</span> <kbd>&lt;x&gt;</kbd>'
