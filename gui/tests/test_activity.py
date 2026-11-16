"""Your activity (activity.py): counted per day and kind, shown as a year's
heatmap with streaks."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from kigit_gui import activity

TODAY = date(2026, 11, 16)  # a Monday


@pytest.fixture(autouse=True)
def project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(activity, "machine", lambda: "laptop-1")
    activity.use(tmp_path, "Author A")
    yield tmp_path
    activity.use(None, "")


def test_record_and_load() -> None:
    assert activity.load() == {}
    activity.record("compare", TODAY)
    activity.record("compare", TODAY)
    activity.record("review", TODAY)
    activity.record("nonsense", TODAY)  # not a kind: ignored
    activity.record("3d", TODAY - timedelta(days=1))
    assert activity.load() == {"2026-11-16": {"compare": 2, "review": 1}, "2026-11-15": {"3d": 1}}


def test_kept_in_the_project_per_person_and_computer(tmp_path: Path, monkeypatch) -> None:
    """Each computer writes its own file in reviews/activity/<person>/, so
    laptops never conflict in git; they add up."""
    activity.record("compare", TODAY)
    assert activity.path() == tmp_path / "reviews" / "activity" / "Author-A" / "laptop-1.json"
    monkeypatch.setattr(activity, "machine", lambda: "work-laptop")
    activity.record("compare", TODAY)
    activity.record("review", TODAY)
    assert sorted(p.name for p in (tmp_path / "reviews" / "activity" / "Author-A").iterdir()) == \
        ["laptop-1.json", "work-laptop.json"]
    assert activity.load() == {"2026-11-16": {"compare": 2, "review": 1}}  # both laptops
    activity.use(tmp_path, "Author B")
    activity.record("reply", TODAY)
    assert activity.load() == {"2026-11-16": {"reply": 1}}  # just Author B's
    assert activity.load(person="*") == {"2026-11-16": {"compare": 2, "review": 1, "reply": 1}}  # everyone
    assert activity.people(tmp_path) == ["Author-A", "Author-B"]


def test_nothing_without_a_project() -> None:
    activity.use(None, "Author A")
    activity.record("compare", TODAY)
    assert activity.path() is None and activity.load() == {}


def test_unreadable_file_is_an_empty_year(tmp_path: Path) -> None:
    activity.path().parent.mkdir(parents=True)
    activity.path().write_text("{not json")
    assert activity.load() == {}
    activity.record("compare", TODAY)  # and it starts again
    assert activity.load() == {"2026-11-16": {"compare": 1}}


def test_stats_streaks_and_busiest() -> None:
    d = lambda n: (TODAY - timedelta(days=n)).isoformat()  # noqa: E731
    days = {d(1): {"compare": 1}, d(2): {"review": 2}, d(3): {"reply": 1},  # 3 in a row up to yesterday
            d(10): {"compare": 5}, d(11): {"compare": 1}, d(12): {"compare": 1}, d(13): {"compare": 1},
            d(400): {"compare": 9}}  # over a year ago: not counted
    st = activity.stats(days, TODAY)
    assert st["current"] == 3  # today has nothing yet: the streak up to yesterday
    assert st["longest"] == 4 and st["busiest"] == (d(10), 5) and st["active_days"] == 7
    assert st["total"] == 12 and st["by_kind"]["compare"] == 9 and st["by_kind"]["review"] == 2
    assert activity.stats({}, TODAY)["busiest"] is None


def test_levels() -> None:
    assert [activity.level(n, 3) for n in (0, 1, 2, 3)] == [0, 1, 2, 3]
    assert [activity.level(n, 20) for n in (0, 1, 10, 20)] == [0, 1, 2, 4]


def test_heatmap() -> None:
    svg = activity.heatmap_svg({TODAY.isoformat(): {"compare": 2, "review": 1}}, TODAY)
    assert svg.count("<rect") == 365 + (TODAY - timedelta(days=364)).weekday() + 1  # back to a Sunday, up to today
    assert 'data-day="2026-11-16"' in svg and 'data-day="2026-11-17"' not in svg  # nothing after today
    assert "3 on Mon 16 Nov 2026: 2 comparisons, 1 review written" in svg
    assert "Nothing on Sun 15 Nov 2026" in svg and ">Nov</text>" in svg and ">Mon</text>" in svg
