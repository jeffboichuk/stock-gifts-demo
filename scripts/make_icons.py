#!/usr/bin/env python3
"""Generate the PWA icons (icons/icon-192.png, icons/icon-512.png).

A chart-line glyph rising left to right on the site's pure-black background,
stroked in the dashboard's teal accent with a gold dot on the final point.
Drawn at 4x and downsampled for smooth edges. Re-run any time the palette
changes: python3 scripts/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

BG = "#000000"      # --bg
TEAL = "#5eead4"    # --teal
GOLD = "#f5b840"    # --gold

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "icons"


def draw_icon(size: int) -> Image.Image:
    scale = 4  # supersample for antialiasing
    s = size * scale
    img = Image.new("RGB", (s, s), BG)
    d = ImageDraw.Draw(img)

    def pt(x: float, y: float) -> tuple[float, float]:
        """Map 0..1 design coords onto the canvas."""
        return (x * s, y * s)

    # Rising chart line with one dip, kept inside a maskable-safe zone.
    points = [pt(0.18, 0.72), pt(0.40, 0.50), pt(0.55, 0.60), pt(0.80, 0.28)]
    w = int(s * 0.055)
    d.line(points, fill=TEAL, width=w, joint="curve")
    # Round the two ends of the stroke.
    for p in (points[0], points[-1]):
        r = w / 2
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=TEAL)
    # Gold dot on the final (highest) point.
    r = int(s * 0.055)
    p = points[-1]
    d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=GOLD)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for size in (192, 512):
        path = OUT / f"icon-{size}.png"
        draw_icon(size).save(path)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
