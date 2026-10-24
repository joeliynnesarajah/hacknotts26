"""
PERSON 1 — Auto-tagging category, pattern and formality with CLIP (zero-shot).

CLIP compares the image to text labels like "a photo of jeans" and picks the
closest. No training needed. Requires: pip install -r requirements-ml.txt

Without CLIP installed, returns placeholder tags marked needs_review=True,
so the user fixes them on the review screen.

TODO (Person 1):
  - [ ] Measure accuracy on the Kaggle sample (compare to its labels)
  - [ ] Improve label wording — CLIP is sensitive to phrasing
  - [ ] Alternative: send the image to a vision LLM API and ask for JSON tags
"""
from functools import lru_cache
from typing import Dict, List

from PIL import Image

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


def tag_item(img: Image.Image) -> Dict:
    try:
        cat = _best(img, list(CATEGORY_LABELS), "a photo of")
        pat = _best(img, list(PATTERN_LABELS), "a photo of")
        form = _best(img, list(FORMALITY_LABELS), "a photo of")
        return {"category": CATEGORY_LABELS[cat], "pattern": PATTERN_LABELS[pat],
                "formality": FORMALITY_LABELS[form], "needs_review": False}
    except ImportError:
        return {"category": "top", "pattern": "solid", "formality": 2, "needs_review": True}
