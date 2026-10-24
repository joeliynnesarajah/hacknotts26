"""
PERSON 1 — Background removal.

Uses rembg if installed (pip install -r requirements-ml.txt).
Without it, falls back to a simple trick that only works on photos
with a plain white/light background (like shop product photos).

TODO (Person 1):
  - [ ] Test rembg on messy real photos (clothes on a bed, on a hanger)
  - [ ] Crop to the item's bounding box and pad to a square
"""
from functools import lru_cache

import numpy as np
from PIL import Image

MAX_SIDE = 1024  # phone photos are ~4000px; shrinking first makes every later step much faster


@lru_cache(maxsize=1)
def _rembg_session():
    """Load rembg's model once and reuse it. Calling rembg.remove() without a session
    reloads the 176 MB model on every call (~40s per upload instead of ~0.5s)."""
    from rembg import new_session  # heavy, optional
    return new_session("u2net")


def remove_background(img: Image.Image) -> Image.Image:
    img = img.copy()
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    try:
        from rembg import remove
        return remove(img.convert("RGBA"), session=_rembg_session())
    except ImportError:
        return _remove_light_background(img)


def _remove_light_background(img: Image.Image, threshold: int = 235) -> Image.Image:
    rgba = np.array(img.convert("RGBA"))
    light = (rgba[..., :3] > threshold).all(axis=-1)
    rgba[light, 3] = 0
    return Image.fromarray(rgba)


def crop_to_content(img: Image.Image, pad: int = 10) -> Image.Image:
    bbox = img.getbbox()  # bounding box of non-transparent pixels
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    img = img.crop((max(0, x0 - pad), max(0, y0 - pad), x1 + pad, y1 + pad))
    side = max(img.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return square
