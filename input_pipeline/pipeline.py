"""
PERSON 1 — The full flow: photo in -> Item out.

    photo -> remove background -> crop -> main colors -> tags -> Item

Try it on its own:
    python -m input_pipeline.pipeline path/to/photo.jpg
"""
import sys
import concurrent.futures
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image

from input_pipeline.background import crop_to_content, remove_background
from input_pipeline.colors import dominant_colors
from input_pipeline.tagger import tag_item
from shared.schema import Item

ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "data" / "images"
DEFAULT_NAME = "New item"


def process_photo_with_meta(photo: Image.Image, name: Optional[str] = None,
                            item_id: Optional[str] = None) -> tuple[Item, bool, dict]:
    """Returns (item, needs_review, tag_meta).

    tag_meta = {source, confidence, needs_review, suggested_name} (plus `updated`,
    which the database adds when the row is read).
    A name the user typed always wins; the tagger's name is only used when they
    left it blank (or as the form default), and is always kept as suggested_name.
    Pass item_id to get a stable id (the pretag script does); otherwise it's random.
    """
    photo.load()
    # Run background removal (CPU) and vision tagging (network I/O) concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        bg_future = pool.submit(lambda: crop_to_content(remove_background(photo)))
        tag_future = pool.submit(lambda: tag_item(photo))
        cutout = bg_future.result()
        tags = tag_future.result()

    item_id = item_id or uuid.uuid4().hex[:8]
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    cutout.save(IMAGES_DIR / f"{item_id}.png")
    typed = (name or "").strip()
    item = Item(
        id=item_id,
        name=typed if typed and typed != DEFAULT_NAME else tags["name"],
        image=f"images/{item_id}.png",
        category=tags["category"],
        colors=dominant_colors(cutout),
        pattern=tags["pattern"],
        formality=tags["formality"],
        seasons=tags["seasons"],
        warmth=tags["warmth"],
    )
    meta = {
        "source": tags["source"],
        "confidence": tags["confidence"],
        "needs_review": tags["needs_review"],
        "suggested_name": tags["name"],
    }
    return item, tags["needs_review"], meta


def process_photo(photo: Image.Image, name: str = DEFAULT_NAME) -> tuple[Item, bool]:
    """Backward-compatible: returns (item, needs_review)."""
    item, needs_review, _ = process_photo_with_meta(photo, name)
    return item, needs_review


if __name__ == "__main__":
    item, review, meta = process_photo_with_meta(Image.open(sys.argv[1]), name=Path(sys.argv[1]).stem)
    print(item.model_dump_json(indent=2))
    print(f"\nsource: {meta['source']}  confidence: {meta['confidence']}  needs_review: {review}")
    if meta["source"] == "placeholder":
        print("(Placeholder tags - add a key to keys.env, or install requirements-ml.txt for CLIP.)")
