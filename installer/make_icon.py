"""Generates installer/assets/icon.ico -- a simple line-chart glyph on a rounded square."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT_PATH = Path(__file__).resolve().parent / "assets" / "icon.ico"
SIZE = 256
BG = (30, 41, 59)       # slate-800
ACCENT = (56, 189, 248)  # sky-400
LINE = (248, 250, 252)   # near-white


def draw_base(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = size * 0.06
    radius = size * 0.18
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin], radius=radius, fill=BG,
    )

    pad = size * 0.20
    points = [
        (pad, size * 0.62),
        (size * 0.36, size * 0.42),
        (size * 0.52, size * 0.56),
        (size * 0.78, size * 0.26),
    ]
    width = max(2, round(size * 0.045))
    draw.line(points, fill=ACCENT, width=width, joint="curve")
    dot_r = size * 0.03
    for x, y in points:
        draw.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r], fill=LINE)

    baseline_y = size - pad
    draw.line([(pad, baseline_y), (pad, size * 0.30)], fill=LINE, width=max(2, round(size * 0.025)))
    draw.line([(pad, baseline_y), (size - pad, baseline_y)], fill=LINE, width=max(2, round(size * 0.025)))
    return img


def main() -> None:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    base = draw_base(SIZE)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base.save(OUT_PATH, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
