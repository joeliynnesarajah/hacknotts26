"""
PERSON 1 — The full flow: photo in -> Item out.

    photo -> remove background -> crop -> main colors -> tags -> Item

Try it on its own:
    python -m input_pipeline.pipeline path/to/photo.jpg
"""
import os
import sys
import uuid
from pathlib import Path

from PIL import Image

from input_pipeline.background import crop_to_content, remove_background
from input_pipeline.colors import dominant_colors
from input_pipeline.tagger import tag_item
from shared.schema import Item

ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "data" / "images"


def _images_dir() -> Path:
    """Resolved per call so tests can point WARDROBE_IMAGES_DIR at a temp dir."""
    return Path(os.environ.get("WARDROBE_IMAGES_DIR") or IMAGES_DIR)


def process_photo_with_meta(photo: Image.Image, name: str = "New item") -> tuple[Item, bool, dict]:
    """Returns (item, needs_review, tag_meta).

    tag_meta is what the UI needs to show where the tags came from:
        {"source", "confidence", "needs_review", "suggested_name"}
    """
    cutout = crop_to_content(remove_background(photo))
    item_id = uuid.uuid4().hex[:8]
    images = _images_dir()
    images.mkdir(parents=True, exist_ok=True)
    cutout.save(images / f"{item_id}.png")

    tags = tag_item(cutout)
    item = Item(
        id=item_id,
        name=name,
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
        "confidence": float(tags["confidence"]),
        "needs_review": bool(tags["needs_review"]),
        "suggested_name": tags.get("name"),
    }
    return item, meta["needs_review"], meta


def process_photo(photo: Image.Image, name: str = "New item") -> tuple[Item, bool]:
    """Returns (item, needs_review). Kept for callers that don't need the metadata."""
    item, needs_review, _ = process_photo_with_meta(photo, name=name)
    return item, needs_review


if __name__ == "__main__":
    item, review, meta = process_photo_with_meta(
        Image.open(sys.argv[1]), name=Path(sys.argv[1]).stem
    )
    print(item.model_dump_json(indent=2))
    print(f"\nsource={meta['source']} confidence={meta['confidence']:.2f}")
    if review:
        print("(Tags are guesses — the UI flags these for review.)")
