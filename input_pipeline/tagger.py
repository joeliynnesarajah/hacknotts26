"""
PERSON 1 — Auto-tagging with a hosted vision model, with safe fallbacks.

The chain is Pollinations -> Gemini -> placeholder. Override it with
TAGGER_PROVIDER_ORDER (comma-separated), e.g. `TAGGER_PROVIDER_ORDER=placeholder`.
`tag_item` always returns every key the pipeline needs and never raises.

The old zero-shot CLIP helpers are kept below, unused and lazily imported, as a
local option for later. They require `pip install -r requirements-ml.txt`.
"""
import os
from functools import lru_cache
from typing import Dict, List

from PIL import Image

from input_pipeline.tagger_vlm import tag_item_gemini, tag_item_pollinations

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
ALL_SEASONS = ["spring", "summer", "autumn", "winter"]


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


DEFAULT_ORDER = ["pollinations", "gemini", "placeholder"]


def _provider_order() -> List[str]:
    raw = os.getenv("TAGGER_PROVIDER_ORDER", "")
    names = [p.strip() for p in raw.split(",") if p.strip()]
    names = [p for p in names if p in DEFAULT_ORDER]
    return names or list(DEFAULT_ORDER)


def _placeholder() -> Dict:
    return {"name": "New item", "category": "top", "pattern": "solid",
            "formality": 2, "seasons": list(ALL_SEASONS), "warmth": 2,
            "confidence": 0.0, "source": "placeholder", "needs_review": True}


def tag_item(img: Image.Image) -> Dict:
    """Always returns the full tag dict: name, category, pattern, formality,
    seasons, warmth, confidence, source, needs_review.

    Tries providers in order and returns the first non-None result. A provider
    that raises is skipped (defensive only — providers already return None).
    """
    for name in _provider_order():
        try:
            if name == "pollinations":
                tags = tag_item_pollinations(img)
            elif name == "gemini":
                tags = tag_item_gemini(img)
            else:
                return _placeholder()
            if tags is not None:
                return tags
        except Exception:  # noqa: BLE001 - the contract is "never raise"
            continue
    return _placeholder()
