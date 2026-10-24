"""
PERSON 1 — The full flow: photo in -> Item out.

    photo -> remove background -> crop -> main colors -> tags -> Item

Try it on its own:
    python -m input_pipeline.pipeline path/to/photo.jpg
"""
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


def process_photo(photo: Image.Image, name: str = "New item") -> tuple[Item, bool]:
    """Returns (item, needs_review)."""
    cutout = crop_to_content(remove_background(photo))
    item_id = uuid.uuid4().hex[:8]
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    cutout.save(IMAGES_DIR / f"{item_id}.png")

    tags = tag_item(cutout)
    item = Item(
        id=item_id,
        name=name,
        image=f"images/{item_id}.png",
        category=tags["category"],
        colors=dominant_colors(cutout),
        pattern=tags["pattern"],
        formality=tags["formality"],
    )
    return item, tags["needs_review"]


if __name__ == "__main__":
    item, review = process_photo(Image.open(sys.argv[1]), name=Path(sys.argv[1]).stem)
    print(item.model_dump_json(indent=2))
    if review:
        print("\n(Tags are placeholders — install requirements-ml.txt for CLIP tagging.)")
