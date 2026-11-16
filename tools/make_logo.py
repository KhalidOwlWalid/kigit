"""Draws kigit's logo: the mark the Reviews page shows (an amber rounded
square with the dark "K|" strokes), as files for the app:

    packaging/icons/kigit.svg   the source shape (also the GUI's favicon)
    packaging/icons/kigit.png   256x256
    packaging/icons/kigit.ico   16-256 px, for kigit.exe and the installer

    uv run --no-project --with pillow python tools/make_logo.py

Each size is drawn at 8x and scaled down, so small icons stay crisp.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "packaging" / "icons"
AMBER, DARK = (232, 184, 77, 255), (26, 20, 5, 255)

# On a 24-unit grid, as in the page's SVG: a rounded square, then strokes.
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="256" height="256">
  <rect x="2" y="2" width="20" height="20" rx="5" fill="#e8b84d"/>
  <path d="M7 7v10M7 12l5-5M7 12l5 5M15 7v10" stroke="#1a1405" stroke-width="2" stroke-linecap="round" fill="none"/>
</svg>
"""
STROKES = [((7, 7), (7, 17)), ((7, 12), (12, 7)), ((7, 12), (12, 17)), ((15, 7), (15, 17))]


def draw(size: int) -> Image.Image:
    big = size * 8
    u = big / 24  # one grid unit
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Small icons use more of the square (less margin) so they read better.
    pad = 2 if size > 32 else 1
    d.rounded_rectangle([pad * u, pad * u, (24 - pad) * u, (24 - pad) * u], radius=5 * u, fill=AMBER)
    width = 2 * u if size > 24 else 2.6 * u
    for (x1, y1), (x2, y2) in STROKES:
        d.line([(x1 * u, y1 * u), (x2 * u, y2 * u)], fill=DARK, width=round(width))
        for x, y in ((x1, y1), (x2, y2)):  # round ends
            r = width / 2
            d.ellipse([x * u - r, y * u - r, x * u + r, y * u + r], fill=DARK)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "kigit.svg").write_text(SVG, encoding="utf-8")
    draw(256).save(OUT / "kigit.png", optimize=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [draw(s) for s in sizes]
    images[-1].save(OUT / "kigit.ico", sizes=[(s, s) for s in sizes], append_images=images[:-1])
    print(f"wrote {OUT}/kigit.svg, kigit.png, kigit.ico")


if __name__ == "__main__":
    main()
