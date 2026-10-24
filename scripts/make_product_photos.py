"""
Replace the drawn placeholder images with realistic product photos of each sample item.

    python scripts/make_product_photos.py              # every item in data/sample_items.json
    python scripts/make_product_photos.py t1 s2        # just these ids

For each item: one Pollinations image (~1 cent, openai/gpt-image-1-mini) of the garment alone,
on a background chosen to contrast with it (dark for light clothes, light for dark ones) so
rembg can cut it out cleanly, then the same cutout format as the rest of the app:
background removed, cropped, padded to a transparent 400x400 square in data/images/<id>.png.
Items are also added to the database if they're missing (e.g. newly added sample items).

The images are generated, not photos of real products, so there are no rights issues.
"""
import argparse
import colorsys
import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import db  # noqa: E402
from input_pipeline import tryon_render  # noqa: E402
from input_pipeline.background import crop_to_content, remove_background  # noqa: E402
from shared.schema import Item  # noqa: E402

SAMPLE_PATH = ROOT / "data" / "sample_items.json"
IMAGES_DIR = ROOT / "data" / "images"
SIZE = 400

COLOUR_WORDS = {  # main colours used in sample_items.json -> words the image model understands
    "#f4f4f2": "white", "#1f3a5f": "navy blue", "#c0392b": "red", "#8a8d91": "mid grey",
    "#f2c94c": "mustard yellow", "#6fa86b": "sage green", "#1b1b1b": "black", "#3b5b8c": "mid-wash blue denim",
    "#d6c4a3": "beige", "#c9a227": "golden yellow", "#9a9da1": "heather grey", "#2e6b4f": "forest green",
    "#6b4226": "brown", "#c8a27a": "tan", "#b88a5a": "camel", "#5b7fae": "light-wash blue denim",
    "#7a1f2b": "burgundy",
}
PATTERN_WORDS = {
    "solid": "plain solid colour", "stripe": "horizontal stripes", "plaid": "tartan plaid check",
    "floral": "small floral print", "graphic": "graphic print", "other": "subtle textured pattern",
}


def luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)[1]


def prompt_for(item: Item) -> str:
    colours = [COLOUR_WORDS.get(c.lower(), c) for c in item.colors]
    colour_text = colours[0] + (f" and {colours[1]}" if len(colours) > 1 else "")
    pattern = PATTERN_WORDS[item.pattern.value]
    # Contrast for clean background removal: dark backdrop for light garments, light for dark ones
    backdrop = "plain dark charcoal grey (#2e2e2e)" if luminance(item.colors[0]) > 0.62 else "plain very light grey (#ececec)"
    if item.category.value == "shoes":
        view = ("a single shoe on its own, seen from the side in profile with the toe pointing to the right, "
                "the whole shoe in frame")
    else:
        view = ("the garment laid perfectly flat and symmetrical, seen straight from the front, neatly arranged with "
                "sleeves (if any) relaxed at the sides, the whole garment in frame with space around it")
    return (
        f"Professional e-commerce product photograph of {item.name.lower()}: {colour_text}, {pattern}. "
        f"Show {view}. Realistic fabric texture, accurate colours, soft even studio lighting, no harsh shadows. "
        f"Uniform {backdrop} seamless background. No person, no mannequin, no hanger, no tags, no text, no logos, "
        "no props, only this one item."
    )


def make_cutout(raw: bytes) -> Image.Image:
    cut = crop_to_content(remove_background(Image.open(io.BytesIO(raw)).convert("RGB")))
    return cut.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*", help="item ids (default: all sample items)")
    args = ap.parse_args()

    items = [Item(**raw) for raw in json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))]
    if args.ids:
        items = [it for it in items if it.id in set(args.ids)]
    conn = db.connect()
    db.init(conn)
    known = {it.id for it in db.list_items(conn)}

    failed = []
    for item in items:
        raw, reason = tryon_render._post(tryon_render.GENERATIONS_URL, {
            "model": tryon_render.models()[0], "prompt": prompt_for(item), "size": "1024x1024",
            "n": 1, "response_format": "b64_json"})
        if not raw:
            failed.append(item.id)
            print(f"{item.id} {item.name}: FAILED ({reason})")
            continue
        make_cutout(raw).save(IMAGES_DIR / f"{item.id}.png")
        if item.id not in known:
            db.save_item(conn, item)
        print(f"{item.id} {item.name}: saved")
    if failed:
        sys.exit(f"Failed: {', '.join(failed)} (re-run with those ids)")


if __name__ == "__main__":
    main()
