"""How long KiCad takes to make a board's 3D model, for a progress bar.

kicad-cli prints no progress while it exports (nothing between its first
warnings and "created"), so the bar is time against the last build of the
same board. Kept in <app data>/kigit/3d-build-times.json, next to the logs.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import logs

FILE = logs.default_dir().parent / "3d-build-times.json"
MIN_SECONDS = 2.0  # quicker than this isn't worth remembering (and keeps test runs out)


def _slowdown(n: int) -> float:
    """Several at once share the computer: each takes a bit longer."""
    return 1 + 0.25 * (max(n, 1) - 1)


def _load() -> dict[str, float]:
    try:
        data = json.loads(FILE.read_text(encoding="utf-8"))
        return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}
    except (OSError, ValueError):
        return {}


def estimate(board: str, n: int = 1) -> float | None:
    """Seconds the board's build is likely to take with n running at once,
    or None the first time."""
    seconds = _load().get(str(Path(board)))
    return seconds * _slowdown(n) if seconds else None


def record(board: str, seconds: float, n: int = 1) -> None:
    """Remembers a build's time (averaged with the last one)."""
    if seconds < MIN_SECONDS:
        return
    times = _load()
    one = seconds / _slowdown(n)
    key = str(Path(board))
    times[key] = round((times[key] + one) / 2 if key in times else one, 1)
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        FILE.write_text(json.dumps(times, indent=1), encoding="utf-8")
    except OSError as e:
        logs.log.warning("couldn't save 3D build times: %s", e)


def progress(elapsed: float, expected: float | None) -> tuple[float | None, str]:
    """(bar value 0..1, or None for "no idea yet", and the text under it)."""
    if not expected:
        return None, f"{elapsed:.0f} s so far · the first build of this board, so no estimate yet"
    if elapsed <= expected:
        return min(elapsed / expected, 0.97), f"{elapsed:.0f} s of about {expected:.0f} s (last time)"
    return 0.97, f"{elapsed:.0f} s · taking longer than last time ({expected:.0f} s)"
