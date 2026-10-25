"""
Draws simple placeholder cut-outs (transparent PNGs) for every item in
data/sample_items.json, so the app has images before real photos exist.

Run:  python scripts/make_placeholders.py [--force]
The sample items now have real product photos (scripts/make_product_photos.py), so existing
images are skipped: this only fills in missing ones. --force redraws everything as placeholders.
"""
import sys
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SIZE = 400


def stripes(draw, box, color, horizontal=True, gap=28):
    x0, y0, x1, y1 = box
    if horizontal:
        for y in range(y0, y1, gap):
            draw.rectangle([x0, y, x1, y + gap // 2], fill=color)
    else:
        for x in range(x0, x1, gap):
            draw.rectangle([x, y0, x + gap // 2, y1], fill=color)


def shape(category):
    """Polygon outline for each category, on a 400x400 canvas."""
    if category in ("top", "outerwear"):
        return [(130, 60), (170, 50), (200, 70), (230, 50), (270, 60), (350, 120), (320, 170),
                (285, 145), (285, 350), (115, 350), (115, 145), (80, 170), (50, 120)]
    if category == "bottom":
        return [(120, 40), (280, 40), (300, 370), (220, 370), (200, 140), (180, 370), (100, 370)]
    if category == "dress":
        return [(160, 30), (240, 30), (260, 130), (330, 370), (70, 370), (140, 130)]
    if category == "shoes":
        return [(60, 220), (180, 200), (240, 240), (340, 260), (350, 310), (60, 310)]
    return [(150, 150), (250, 150), (250, 250), (150, 250)]


def draw_item(item):
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    mask = Image.new("L", (SIZE, SIZE), 0)
    poly = shape(item["category"])
    ImageDraw.Draw(mask).polygon(poly, fill=255)

    fill = Image.new("RGBA", (SIZE, SIZE), item["colors"][0])
    d = ImageDraw.Draw(fill)
    second = item["colors"][1] if len(item["colors"]) > 1 else "#ffffff"
    if item["pattern"] == "stripe":
        stripes(d, (0, 0, SIZE, SIZE), second)
    elif item["pattern"] == "plaid":
        stripes(d, (0, 0, SIZE, SIZE), second, gap=40)
        stripes(d, (0, 0, SIZE, SIZE), second, horizontal=False, gap=40)
    elif item["pattern"] == "floral":
        for x in range(20, SIZE, 60):
            for y in range(20, SIZE, 60):
                d.ellipse([x, y, x + 18, y + 18], fill=second)

    img.paste(fill, (0, 0), mask)
    ImageDraw.Draw(img).polygon(poly, outline=(0, 0, 0, 90), width=3)
    if item["category"] == "outerwear":  # front opening line
        ImageDraw.Draw(img).line([(200, 70), (200, 350)], fill=(0, 0, 0, 110), width=3)
    return img


def main():
    items = json.loads((DATA / "sample_items.json").read_text())
    force = "--force" in sys.argv
    drawn = 0
    for item in items:
        out = DATA / item["image"]
        if out.exists() and not force:  # don't overwrite real product photos
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        draw_item(item).save(out)
        drawn += 1
    print(f"Drew {drawn} placeholder images in {DATA / 'images'} (existing images kept; --force to redraw)")


if __name__ == "__main__":
    main()
