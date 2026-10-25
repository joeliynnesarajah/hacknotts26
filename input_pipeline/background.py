"""
PERSON 1 — Background removal.

Uses rembg if installed (pip install -r requirements-ml.txt).
Without it, falls back to a simple trick that only works on photos
with a plain white/light background (like shop product photos).

TODO (Person 1):
  - [ ] Test rembg on messy real photos (clothes on a bed, on a hanger)
  - [ ] Crop to the item's bounding box and pad to a square
"""
import os
from functools import lru_cache

import numpy as np
from PIL import Image

MAX_SIDE = 512  # phone photos are ~4000px; shrinking first makes every later step much faster
DEFAULT_REMBG_MODEL = "u2netp"  # ~4.7 MB portable model (5x faster than 176 MB u2net)


@lru_cache(maxsize=1)
def _rembg_session():
    """Load rembg's model once and reuse it. Uses the lightweight u2netp model by default
    (~0.1-0.2s on CPU) or any model specified in REMBG_MODEL."""
    from rembg import new_session  # heavy, optional
    model = os.getenv("REMBG_MODEL", DEFAULT_REMBG_MODEL)
    return new_session(model)


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


def fit_to_frame(img: Image.Image, width: int = 360, height: int = 840) -> Image.Image:
    """Cut-out person -> transparent width x height canvas (the try-on figure's 180:420 shape).

    Scaled so the head starts ~2.5% from the top and the feet end ~2% from the bottom,
    centred — the same placement as frontend/cher-silhouette.svg, so the clothes boxes
    line up as well as they can for a photo taken in a normal standing pose."""
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    top, bottom = round(height * 0.025), round(height * 0.02)
    scale = min(width * 0.96 / img.width, (height - top - bottom) / img.height)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(img, ((width - img.width) // 2, height - bottom - img.height), img)
    return canvas


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
