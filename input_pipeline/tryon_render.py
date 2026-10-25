"""
PERSON 1 — Photoreal try-on: dress a person in an outfit with a hosted image-editing model.

    person photo + garment cutouts -> Pollinations POST /v1/images/edits -> one photo of
    the person wearing the outfit

The person is the stock model (data/images/stock_model.png, made once by
scripts/make_stock_model.py) or the user's uploaded avatar (data/images/avatar.png).

Renders are cached on disk in data/renders/<key>.jpg next to <key>.json (status), keyed by
the person image + each garment image + the prompt version + the model list. A repeat look
is instant and free; scripts/prerender.py fills the cache before a demo.

Settings (.env):
    TRYON_MODELS   comma-separated models to try in order
                   (default: openai/gpt-image-1-mini, then black-forest-labs/flux.2-klein-4b)
    TRYON_MODE     live (default) | cache-only (never call the API) | off (paper doll only)

Nothing here raises to the caller: a failed render records why (no key, budget exhausted,
content blocked, timeout...) and the frontend keeps showing the instant paper doll.
"""
import base64
import hashlib
import io
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from PIL import Image

from shared.env import load_env
from shared.schema import Category, Item

load_env()
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
RENDER_DIR = Path(os.getenv("TRYON_RENDER_DIR") or ROOT / "data" / "renders")
STOCK_MODEL_PATH = ROOT / "data" / "images" / "stock_model.png"
AVATAR_PATH = ROOT / "data" / "images" / "avatar.png"

EDITS_URL = "https://gen.pollinations.ai/v1/images/edits"
GENERATIONS_URL = "https://gen.pollinations.ai/v1/images/generations"
DEFAULT_MODELS = "openai/gpt-image-1-mini,black-forest-labs/flux.2-klein-4b"
PROMPT_VERSION = 2    # bump when the prompt changes, so old cached renders aren't reused
SIZE = "1024x1536"    # 2:3 portrait, full body
TIMEOUT = (10, 90)    # connect, read (seconds)
STALE_AFTER_S = 300   # a "pending" render older than this was lost (e.g. server restart)

_lock = threading.Lock()        # one render at a time: protects the budget and rate limits
_sleep = time.sleep             # swapped out in tests

# How each slot is described to the model, in the order garments are sent
SLOT_ORDER = [Category.outerwear, Category.top, Category.dress, Category.bottom, Category.shoes]
SLOT_WORDS = {
    Category.top: "top", Category.bottom: "bottoms", Category.dress: "dress",
    Category.shoes: "shoes", Category.outerwear: "jacket or coat", Category.accessory: "accessory",
}


def mode() -> str:
    m = (os.getenv("TRYON_MODE") or "live").strip().lower()
    return m if m in ("live", "cache-only", "off") else "live"


def models() -> List[str]:
    raw = os.getenv("TRYON_MODELS") or DEFAULT_MODELS
    return [m.strip() for m in raw.split(",") if m.strip()]


def person_path(person: str) -> Optional[Path]:
    """'avatar' -> the uploaded photo if there is one, otherwise (and for 'stock') the stock model."""
    if person == "avatar" and AVATAR_PATH.is_file():
        return AVATAR_PATH
    return STOCK_MODEL_PATH if STOCK_MODEL_PATH.is_file() else None


# ---- inputs ----
def _jpeg_data_uri(img: Image.Image, max_side: int, background: str) -> str:
    """Flatten transparency onto `background`, shrink, JPEG, base64 data URI (small requests)."""
    img = img.convert("RGBA")
    flat = Image.new("RGB", img.size, background)
    flat.paste(img, mask=img.getchannel("A"))
    flat.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    flat.save(buf, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def garment_uri(path: Path) -> str:
    """Crop the cutout to the garment (they're padded squares), on white, <=768px."""
    img = Image.open(path).convert("RGBA")
    bbox = img.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    return _jpeg_data_uri(img, 768, "white")


def person_uri(path: Path) -> str:
    return _jpeg_data_uri(Image.open(path), 1024, "white")  # matches the pure-white output the spec asks for


def ordered(items: List[Item]) -> List[Item]:
    return sorted(items, key=lambda it: SLOT_ORDER.index(it.category) if it.category in SLOT_ORDER else 99)


# The team's try-on specification, used word for word. build_prompt() puts the per-request
# details (which image is the person, which image is which garment) in front of it.
TRYON_SPEC = """Edit the provided reference image into a photorealistic, full-body portrait of the same person, using the provided clothing and styling references.

**IDENTITY PRESERVATION — HIGHEST PRIORITY**

The person in the output must be recognisably the exact same individual as in the reference photo. Preserve their actual facial identity, including eye shape and spacing, eyebrows, nose shape, lips, smile or neutral expression, cheeks, jawline, forehead, skin tone, and natural facial proportions. Preserve their characteristic hairstyle, hairline, hair length, texture, and colour as shown in the reference images.

Do not assume or invent the person's gender, race, ethnicity, age, or other physical characteristics. Use the reference images as the source of truth. Do not beautify, idealise, reinterpret, or replace the face with a generic lookalike. The result should look like a real photograph of the same person.

**CLOTHING AND STYLING**

Use the clothing, accessories, jewellery, footwear, hairstyle, makeup, and other styling explicitly provided in the supplied reference images or instructions. Reproduce these details as faithfully as possible, including colours, patterns, materials, fit, layering, accessories, and distinctive design elements.

Do not assume a particular style of clothing based on the person's appearance, perceived gender, or perceived ethnicity. Do not add culturally specific clothing, jewellery, makeup, or accessories unless they are explicitly requested or shown in the supplied references.

If no clothing reference is provided, retain the clothing in the original photograph or ask for a clothing reference rather than inventing a style.

**POSE AND COMPOSITION**

Create a vertical 2:3 full-body photograph. Show the same person standing naturally and facing the camera, with a relaxed posture and an expression consistent with the reference images. Their entire body must be visible from the top of their head to their feet, without cropping.

Preserve realistic body proportions and the person's natural build. Ensure hands, fingers, limbs, and facial features are anatomically plausible. Keep the face clearly visible and sufficiently detailed to preserve the person's likeness.

**BACKGROUND — PURE WHITE**

Use a completely plain, solid white background (#FFFFFF), extending seamlessly across the entire image. The background must be uniformly white, with no visible room, furniture, walls, corners, floor lines, props, patterns, gradients, or decorative elements.

Create a clean, minimal studio-style appearance. Keep the person clearly separated from the white background, with natural, soft, even lighting and subtle, realistic shadows directly beneath the feet where appropriate. The background must remain pure white, not cream, grey, off-white, or beige.

**PHOTOGRAPHIC STYLE**

Make the final result look like a genuine, high-quality photograph. Use natural lighting, realistic shadows on the person, authentic skin texture, accurate colours, and believable fabric detail. Avoid excessive smoothing, artificial skin, exaggerated cinematic effects, or an unnecessarily polished fashion-editorial appearance.

**STRICT CONSTRAINTS**

Preserve the person's identity above all else. Change only the elements requested, such as clothing, pose, framing, or background. Keep all unrequested characteristics consistent with the reference images.

Do not introduce assumptions about gender, race, ethnicity, body type, or personal style. Avoid distorted anatomy, extra fingers, unrealistic proportions, artificial-looking skin, unintended text, logos, or watermarks.

The final image should look like a realistic, full-body photograph of the same person, wearing the specified clothing and styling, against a completely plain, pure white background."""


def build_prompt(items: List[Item]) -> str:
    """Image 1 is the person; images 2.. are the garments, in `ordered()` order."""
    refs = "\n".join(f"- Image {i}: the {SLOT_WORDS[it.category]} ({it.name})" for i, it in enumerate(items, start=2))
    return (
        "**REFERENCE IMAGES**\n\n"
        "Image 1 is the reference photo of the person. The remaining images are the clothing references:\n"
        f"{refs}\n\n"
        "Dress the person in exactly these garments, replacing all of the clothing they are wearing in image 1. "
        "Use only the garments themselves: ignore any hanger, label, mannequin or background in the clothing photos.\n\n"
        + TRYON_SPEC
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_key(person: Path, items: List[Item]) -> str:
    h = hashlib.sha256()
    h.update(f"v{PROMPT_VERSION}|{','.join(models())}|{_sha(person)}".encode())
    for it in sorted(items, key=lambda i: i.id):
        h.update(f"|{it.id}:{it.category.value}:{_sha(ROOT / 'data' / it.image)}".encode())
    return h.hexdigest()[:24]


# ---- cache / status on disk ----
def _status_path(key: str) -> Path:
    return RENDER_DIR / f"{key}.json"


def image_path(key: str) -> Path:
    return RENDER_DIR / f"{key}.jpg"


def _atomic_write(path: Path, data: bytes) -> None:
    """Write to a temp file and swap it in, so a poll never reads a half-written file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _write_status(key: str, **status) -> Dict:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    status = {"key": key, "updated": time.time(), **status}
    _atomic_write(_status_path(key), json.dumps(status).encode("utf-8"))
    return status


def _load_status(key: str) -> Optional[Dict]:
    try:
        return json.loads(_status_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_status(key: str) -> Optional[Dict]:
    """done / pending / failed, or None if this key was never rendered."""
    if image_path(key).is_file():
        return {**(_load_status(key) or {}), "key": key, "status": "done"}
    if not _status_path(key).is_file():
        return None
    status = _load_status(key)
    if status is None:  # unreadable status file: treat as still working; it goes stale like any other
        return {"key": key, "status": "pending"}
    if status.get("status") == "pending" and time.time() - status.get("updated", 0) > STALE_AFTER_S:
        status.update(status="failed", reason="render was interrupted")
    return status


def person_kind(person: Path) -> str:
    return "avatar" if person.resolve() == AVATAR_PATH.resolve() else "stock"


# Only the most recently requested look gets rendered: if the user moved on while a render was
# queued behind the lock, that render is skipped instead of costing money and delaying the new one.
_latest_wanted: Optional[str] = None


def mark_pending(key: str, person: Optional[Path] = None) -> Dict:
    global _latest_wanted
    _latest_wanted = key
    return _write_status(key, status="pending", person=person_kind(person) if person else "stock")


def purge_person(kind: str = "avatar") -> int:
    """Delete every cached render of one person (e.g. when their photo is reset or replaced).
    Renders of someone's own photo shouldn't outlive the photo."""
    removed = 0
    for status_file in RENDER_DIR.glob("*.json"):
        key = status_file.stem
        if (_load_status(key) or {}).get("person") == kind:
            image_path(key).unlink(missing_ok=True)
            status_file.unlink(missing_ok=True)
            removed += 1
    return removed


# ---- provider ----
def _error_reason(r: requests.Response) -> str:
    """'HTTP 402 KEY_BUDGET_EXHAUSTED' etc. Never raises, whatever shape the body has."""
    try:
        err = r.json().get("error", {})
        code = err.get("code") if isinstance(err, dict) else err
        return f"HTTP {r.status_code} {str(code or '')[:80]}".strip()
    except Exception:
        return f"HTTP {r.status_code}"


def _post(url: str, body: Dict) -> Tuple[Optional[bytes], str]:
    """One call. Returns (image bytes, '') or (None, reason). Never logs the key or images."""
    key = os.getenv("POLLINATIONS_API_KEY")
    if not key:
        return None, "no POLLINATIONS_API_KEY"
    reason = "no attempt made"
    for attempt in range(2):  # one retry for rate limits / server errors
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=TIMEOUT)
        except requests.RequestException as exc:
            return None, type(exc).__name__
        if r.status_code == 429 or r.status_code >= 500:
            reason = _error_reason(r)
            log.warning("try-on %s: %s, retrying", body.get("model"), reason)
            _sleep(2 + attempt * 3)
            continue
        if not r.ok:
            return None, _error_reason(r)
        try:
            b64 = (r.json().get("data") or [{}])[0].get("b64_json")
            return (base64.b64decode(b64), "") if b64 else (None, "no image in response")
        except Exception as exc:
            return None, f"unreadable response ({type(exc).__name__})"
    return None, reason


def whiten_background(img: Image.Image) -> Image.Image:
    """Make the background exactly #FFFFFF, as the try-on spec requires. Image models return
    'nearly white' (light grey, darker corners), so: rembg finds the person and everything else
    becomes pure white, except a soft contact shadow kept directly under and around the feet
    (no floor line or corner shading survives). Without rembg the image is unchanged."""
    import numpy as np
    try:
        from rembg import remove
        from input_pipeline.background import _rembg_session
        mask = remove(img, session=_rembg_session(), only_mask=True)
    except ImportError:
        return img
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32)
    alpha = np.asarray(mask.convert("L").resize(img.size), dtype=np.float32)[..., None] / 255.0
    luma = rgb.mean(axis=2)
    h, w = luma.shape
    person = alpha[..., 0] > 0.5
    new_bg = np.full((h, w), 255.0, dtype=np.float32)

    # Contact shadow: only in a window around the feet, and only where it's clearly darker
    # than the background right next to it (so vignettes and floor gradients are dropped).
    feet_rows = np.where(person[int(h * 0.8):].any(axis=1))[0]
    if feet_rows.size:
        foot_top = int(h * 0.8) + int(feet_rows.min())
        foot_bottom = int(h * 0.8) + int(feet_rows.max())
        cols = np.where(person[foot_top:foot_bottom + 1].any(axis=0))[0]
        x0, x1 = int(cols.min()), int(cols.max())
        y0, y1 = max(foot_bottom - int(h * 0.04), 0), min(foot_bottom + int(h * 0.03), h)
        pad = int(w * 0.06)
        wx0, wx1 = max(x0 - pad, 0), min(x1 + pad, w)
        window = luma[y0:y1, wx0:wx1]
        window_bg = ~person[y0:y1, wx0:wx1]
        # Reference level: background just outside the window, on the same rows
        side = np.concatenate([luma[y0:y1, max(wx0 - pad, 0):wx0].ravel(), luma[y0:y1, wx1:min(wx1 + pad, w)].ravel()])
        ref = float(np.median(side)) if side.size else float(np.median(window[window_bg])) if window_bg.any() else 255.0
        strength = np.clip((ref - window) / 40.0, 0.0, 1.0) * window_bg  # 40 levels darker = full shadow
        strength[strength < 0.08] = 0.0
        # Fade out towards the window's edges so there's no visible box
        yy = np.linspace(0, np.pi, y1 - y0)[:, None]
        xx = np.linspace(0, np.pi, wx1 - wx0)[None, :]
        strength *= np.sin(yy) ** 0.5 * np.sin(xx) ** 0.5
        new_bg[y0:y1, wx0:wx1] = 255.0 * (1.0 - 0.35 * strength)
    new_bg = new_bg[..., None]
    out = alpha * rgb + (1.0 - alpha) * new_bg
    return Image.fromarray(np.clip(out + 0.5, 0, 255).astype(np.uint8), "RGB")


def _save_jpeg(raw: bytes, path: Path) -> None:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    for attempt in range(2):  # retry once: it can fail transiently (e.g. memory pressure while loading rembg)
        try:
            img = whiten_background(img)
            break
        except Exception as exc:  # cosmetic step: never lose a paid render over it
            log.warning("try-on background whitening failed (attempt %d): %r", attempt + 1, exc)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    _atomic_write(path, buf.getvalue())


def render(key: str, person: Path, items: List[Item], only_if_latest: bool = False) -> Dict:
    """Render and cache one look, trying each model in turn. Always returns (and records) a
    final status; never raises. only_if_latest=True (the web app) skips the render if a newer
    look was requested while this one waited for the lock."""
    kind = person_kind(person)
    try:
        with _lock:
            if image_path(key).is_file():  # someone else rendered it while we waited
                return read_status(key)
            if only_if_latest and _latest_wanted not in (None, key):
                return _write_status(key, status="failed", person=kind, reason="superseded by a newer look")
            _write_status(key, status="pending", person=kind)  # restart the stale timer: queue time doesn't count
            items = ordered(items)
            images = [{"image_url": person_uri(person)}] + [
                {"image_url": garment_uri(ROOT / "data" / it.image)} for it in items]
            prompt = build_prompt(items)
            reasons = []
            for model in models():
                started = time.perf_counter()
                raw, reason = _post(EDITS_URL, {"model": model, "prompt": prompt, "image": images,
                                                "size": SIZE, "n": 1, "response_format": "b64_json"})
                if raw:
                    try:
                        _save_jpeg(raw, image_path(key))
                    except Exception as exc:
                        reasons.append(f"{model}: unreadable image ({type(exc).__name__})")
                        continue
                    took = round(time.perf_counter() - started, 1)
                    log.info("try-on rendered with %s in %ss", model, took)
                    return _write_status(key, status="done", person=kind, model=model, seconds=took,
                                         item_ids=[it.id for it in items])
                log.warning("try-on %s failed: %s", model, reason)
                reasons.append(f"{model}: {reason}")
                if reason == "no POLLINATIONS_API_KEY":
                    break
            return _write_status(key, status="failed", person=kind, reason="; ".join(reasons) or "no models configured")
    except Exception as exc:  # e.g. an item image deleted mid-render: record it instead of staying "pending"
        log.exception("try-on render crashed")
        return _write_status(key, status="failed", person=kind, reason=f"render crashed ({type(exc).__name__})")


def generate_stock_model(path: Path = STOCK_MODEL_PATH) -> Tuple[bool, str]:
    """One text-to-image call for the default try-on person. Used by scripts/make_stock_model.py."""
    prompt = (
        "Full-body fashion catalogue photo of a fictional young adult woman with long straight blonde hair, "
        "standing straight and facing the camera, arms relaxed slightly away from her body, feet hip-width apart, "
        "head to toe in frame with a little space above and below. She wears a plain fitted light grey t-shirt, "
        "plain light grey leggings and plain white sneakers. Plain light grey studio background, soft even "
        "lighting, photorealistic, neutral friendly expression."
    )
    raw, reason = _post(GENERATIONS_URL, {"model": models()[0], "prompt": prompt, "size": SIZE, "n": 1,
                                          "response_format": "b64_json"})
    if not raw:
        return False, reason
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.open(io.BytesIO(raw)).convert("RGB").save(path, format="PNG", optimize=True)
    return True, ""
