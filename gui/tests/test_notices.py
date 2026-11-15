"""The notification centre and the pages that open in their own tab (notices.py)."""

import asyncio
import json

import pytest

from kigit_gui import notices


@pytest.fixture(autouse=True)
def empty() -> None:
    notices.clear()


def test_unread_problems_and_reading() -> None:
    notices.add("info", "Compared")
    assert notices.unread_problems() == 0  # info alone: no red "!"
    notices.add("warning", "12 parts without a 3D model", "KiCad couldn't find them.", ("Part", "Model file"),
                [("U405", "${KICAD10_3DMODEL_DIR}/x.step"), ("R1 <odd>", "a&b.wrl")])
    notices.add("error", "Couldn't make the 3D board")
    assert notices.unread_problems() == 2
    assert [n.level for n in notices.items] == ["error", "warning", "info"]  # newest first
    v = notices.version
    notices.mark_read()
    assert notices.unread_problems() == 0 and notices.version != v
    table = notices.html_table(notices.items[1])
    assert "<th>Part</th>" in table and "R1 &lt;odd&gt;" in table and "a&amp;b.wrl" in table
    notices.clear()
    assert notices.items == [] and notices.unread_problems() == 0


def test_tab_pages() -> None:
    notices.add("warning", "w", rows=[("a", "b")], headers=("Part", "Model file"))
    data = json.loads(asyncio.run(notices._notices_json()).body)  # noqa: SLF001
    assert data["items"][0]["rows"] == [["a", "b"]] and data["items"][0]["level"] == "warning"
    page = asyncio.run(notices._notices_page()).body.decode()  # noqa: SLF001
    assert 'const KIND = "notices"' in page and "/notices.json" in page
    log_page = asyncio.run(notices._log_page()).body.decode()  # noqa: SLF001
    assert 'const KIND = "log"' in log_page and "%%" not in log_page
    assert asyncio.run(notices._log_text()).status_code == 200  # noqa: SLF001


def test_keeps_the_newest() -> None:
    for i in range(notices.KEEP + 5):
        notices.add("info", str(i))
    assert len(notices.items) == notices.KEEP and notices.items[0].title == str(notices.KEEP + 4)
