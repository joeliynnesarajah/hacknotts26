"""
PERSON 1 — Auto-tagging a clothing photo.

tag_item(img) tries each provider in order and returns the first answer:
    1. pollinations  hosted vision model  (tagger_vlm.py, needs POLLINATIONS_API_KEY)
    2. gemini        hosted vision model  (tagger_vlm.py, needs GEMINI_API_KEY)
    3. clip          local zero-shot CLIP (needs pip install -r requirements-ml.txt)
    4. placeholder   fixed guesses, needs_review=True — always works, even offline

Change the order without editing code, e.g. if Pollinations is down:
    TAGGER_PROVIDER_ORDER=gemini,clip,placeholder

Every result has the same keys:
    name, category, pattern, formality, seasons, warmth, confidence, source, needs_review

TODO (Person 1):
  - [ ] Improve CLIP label wording — CLIP is sensitive to phrasing
"""
import logging
import os
from functools import lru_cache
from typing import Dict, List, Optional

from PIL import Image

from input_pipeline import tagger_vlm
from shared.schema import Season

log = logging.getLogger(__name__)

DEFAULT_ORDER = ["pollinations", "gemini", "clip", "placeholder"]
ALL_SEASONS = [s.value for s in Season]

# label text -> value in our schema
CATEGORY_LABELS = {
    "a t-shirt": "top", "a shirt": "top", "a blouse": "top", "a jumper or sweater": "top",
    "jeans": "bottom", "trousers": "bottom", "a skirt": "bottom", "shorts": "bottom",
    "a dress": "dress",
    "trainers or sneakers": "shoes", "boots": "shoes", "sandals": "shoes", "formal shoes": "shoes",
    "a coat": "outerwear", "a jacket": "outerwear",
    "a bag": "accessory", "a hat": "accessory", "a scarf": "accessory",
}
PATTERN_LABELS = {
    "plain solid-colored fabric": "solid", "striped fabric": "stripe", "plaid or checked fabric": "plaid",
    "floral print fabric": "floral", "fabric with a graphic print or logo": "graphic",
}
FORMALITY_LABELS = {
    "loungewear or gym clothes": 1, "casual everyday clothes": 2, "smart casual clothes": 3,
    "business clothes": 4, "formal evening wear": 5,
}


def placeholder() -> Dict:
    return {"name": "New item", "category": "top", "pattern": "solid", "formality": 2,
            "seasons": list(ALL_SEASONS), "warmth": 2, "confidence": 0.0,
            "source": "placeholder", "needs_review": True}


# ---- CLIP (zero-shot, local) ----
@lru_cache(maxsize=1)
def _load_clip():
    from transformers import CLIPModel, CLIPProcessor
    name = "openai/clip-vit-base-patch32"
    return CLIPModel.from_pretrained(name), CLIPProcessor.from_pretrained(name)


def _best(img: Image.Image, labels: List[str], prefix: str) -> str:
    model, processor = _load_clip()
    inputs = processor(text=[f"{prefix} {l}" for l in labels], images=img.convert("RGB"),
                       return_tensors="pt", padding=True)
    probs = model(**inputs).logits_per_image.softmax(dim=1)[0]
    return labels[int(probs.argmax())]


def tag_item_clip(img: Image.Image) -> Optional[Dict]:
    """CLIP can't judge seasons/warmth, so those stay at defaults and it always needs review."""
    try:
        cat = _best(img, list(CATEGORY_LABELS), "a photo of")
        pat = _best(img, list(PATTERN_LABELS), "a photo of")
        form = _best(img, list(FORMALITY_LABELS), "a photo of")
    except ImportError:
        return None  # CLIP not installed — normal, not worth a warning
    except Exception as exc:
        log.warning("clip: %s", type(exc).__name__)
        return None
    return {"name": "New item", "category": CATEGORY_LABELS[cat], "pattern": PATTERN_LABELS[pat],
            "formality": FORMALITY_LABELS[form], "seasons": list(ALL_SEASONS), "warmth": 2,
            "confidence": 0.5, "source": "clip", "needs_review": True}


# ---- the chain ----
def _provider_order() -> List[str]:
    raw = os.getenv("TAGGER_PROVIDER_ORDER", "")
    order = [p.strip().lower() for p in raw.split(",") if p.strip().lower() in DEFAULT_ORDER]
    return order or list(DEFAULT_ORDER)


def tag_item(img: Image.Image) -> Dict:
    """Always returns a full tags dict; never raises."""
    for provider in _provider_order():
        if provider == "placeholder":
            break
        try:
            if provider == "pollinations":
                tags = tagger_vlm.tag_item_pollinations(img)
            elif provider == "gemini":
                tags = tagger_vlm.tag_item_gemini(img)
            else:
                tags = tag_item_clip(img)
        except Exception as exc:  # providers shouldn't raise, but never let one break an upload
            log.warning("%s raised %s", provider, type(exc).__name__)
            tags = None
        if tags is not None:
            return tags
    return placeholder()
