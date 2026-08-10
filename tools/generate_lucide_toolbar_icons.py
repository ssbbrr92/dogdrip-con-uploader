"""Generate the small Lucide-style toolbar PNG set bundled by the app.

The geometry follows Lucide's 24px, 2px-stroke icon conventions.  Keeping this
script makes the raster assets reproducible without shipping an SVG renderer.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "assets" / "lucide"
SCALE = 4
NAVY = "#2e486b"


def canvas():
    image = Image.new("RGBA", (24 * SCALE, 24 * SCALE), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def line(draw, points, width=2):
    draw.line([(x * SCALE, y * SCALE) for x, y in points], fill=NAVY, width=width * SCALE, joint="curve")


def save(name, painter):
    image, draw = canvas()
    painter(draw)
    image.resize((20, 20), Image.Resampling.LANCZOS).save(OUTPUT / f"{name}.png")


def text_icon(name, character, font_name="arial.ttf"):
    image, draw = canvas()
    try:
        font = ImageFont.truetype(font_name, 18 * SCALE)
    except OSError:
        font = ImageFont.load_default(size=18 * SCALE)
    bounds = draw.textbbox((0, 0), character, font=font)
    draw.text(((96 - (bounds[2] - bounds[0])) / 2, (96 - (bounds[3] - bounds[1])) / 2 - bounds[1]), character, fill=NAVY, font=font)
    image.resize((20, 20), Image.Resampling.LANCZOS).save(OUTPUT / f"{name}.png")


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    text_icon("bold", "B", "arialbd.ttf")
    text_icon("italic", "I", "ariali.ttf")
    text_icon("underline", "U", "arial.ttf")
    for name, spans in {
        "align-left": [(4, 5, 20), (4, 10, 16), (4, 15, 20), (4, 20, 14)],
        "align-center": [(4, 5, 20), (6, 10, 18), (4, 15, 20), (7, 20, 17)],
        "align-right": [(4, 5, 20), (8, 10, 20), (4, 15, 20), (10, 20, 20)],
    }.items():
        save(name, lambda draw, spans=spans: [line(draw, [(x1, y), (x2, y)]) for x1, y, x2 in spans])
    save("minus", lambda draw: line(draw, [(5, 12), (19, 12)]))
    # link.png is rasterized directly from the official link.svg asset.
    save("image", lambda draw: (
        draw.rounded_rectangle((3*SCALE, 4*SCALE, 21*SCALE, 20*SCALE), radius=2*SCALE, outline=NAVY, width=2*SCALE),
        draw.ellipse((7*SCALE, 8*SCALE, 9*SCALE, 10*SCALE), fill=NAVY),
        line(draw, [(4, 17), (9, 12), (13, 16), (16, 13), (20, 17)]),
    ))


if __name__ == "__main__":
    main()
