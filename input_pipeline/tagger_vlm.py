"""
PERSON 1 — Tagging with a hosted vision model (Pollinations first, then Gemini).

One photo -> one HTTP call -> JSON tags (name, category, pattern, formality,
seasons, warmth, confidence). No SDK: both providers are plain `requests.post`.

Every function here returns None on ANY failure (no key, out of credit, rate
limited, timeout, bad JSON...) and never raises. tagger.py relies on that to
fall through to the next provider.

Keys go in keys.env (see shared/env.py):
    POLLINATIONS_API_KEY=sk_...      https://enter.pollinations.ai/keys
    GEMINI_API_KEY=...               https://aistudio.google.com/apikey
Optional overrides: POLLINATIONS_MODEL, GEMINI_MODEL

Try it on one image:
    python -m input_pipeline.tagger_vlm data/images/t2.png
"""
import base64
import io
import json
import logging
import os
import random
import sys
import threading
import time
from typing import Callable, Optional

import requests
from PIL import Image

from shared.env import load_env
from shared.schema import Category, Pattern, Season

load_env()
log = logging.getLogger(__name__)

POLLINATIONS_URL = "https://gen.pollinations.ai/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_LEGACY_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_POLLINATIONS_MODEL = "google/gemini-3.5-flash-lite"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

REVIEW_BELOW = 0.55   # confidence under this -> needs_review
# Third-party community routes are uncalibrated, so demand more confidence before
# showing their tags unflagged. Measured on 18 sample images: the Gemini community
# route scored 0.10 and 0.30 on its two wrong tags and 0.90-0.95 on correct ones,
# so a higher bar flags the errors without flagging every upload.
COMMUNITY_REVIEW_BELOW = 0.80
MAX_ATTEMPTS = 3      # first try + 2 retries
MAX_WAIT_S = 8        # cap on any single backoff / Retry-After
_SEM = threading.Semaphore(1)  # one call at a time, so bulk uploads don't trip rate limits
_sleep = time.sleep            # swapped out in tests

PROMPT = """You are tagging a single clothing item for a wardrobe app.
Look only at the garment in the image. Ignore the background, hangers, and props.

Return JSON matching the schema exactly.

Rules:
- category: top, bottom, dress, shoes, outerwear, or accessory. Trousers are bottom, not top. A jacket is outerwear, not top.
- pattern: solid if there is no visible print; otherwise stripe, plaid, floral, graphic, or other.
- formality: 1 = loungewear/gym, 2 = casual, 3 = smart casual, 4 = business, 5 = formal evening.
- seasons: list every season the item suits, based on fabric weight and coverage.
- warmth: 1 = very light (linen, mesh), 5 = very warm (heavy coat, thick knit).
- confidence: 0-1. Lower it for blurry, cropped, or ambiguous images.
- name: short and specific, max 40 chars (e.g. "Navy Oxford shirt").

If the image does not contain one clear garment, return your best guess with confidence <= 0.3."""

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short human name, max 40 chars"},
        "category": {"type": "string", "enum": [c.value for c in Category]},
        "pattern": {"type": "string", "enum": [p.value for p in Pattern]},
        "formality": {"type": "integer", "minimum": 1, "maximum": 5},
        "seasons": {"type": "array", "items": {"type": "string", "enum": [s.value for s in Season]}},
        "warmth": {"type": "integer", "minimum": 1, "maximum": 5},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["name", "category", "pattern", "formality", "seasons", "warmth", "confidence"],
    "additionalProperties": False,
}


class _EndpointMissing(Exception):
    """The provider returned 404 — used to switch Gemini to its legacy endpoint."""


# ---- shared helpers ----
def _encode(img: Image.Image) -> str:
    """768px max side, JPEG q85, base64. Transparent cutouts go on white, not black."""
    img = img.copy()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.getchannel("A"))
        img = bg
    img = img.convert("RGB")
    img.thumbnail((512, 512))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _validate(raw) -> Optional[dict]:
    """Model output (JSON text or dict) -> clean tags dict, or None if unusable.
    Out-of-range numbers are clamped and missing optional fields defaulted, so a
    slightly-off answer still works. Only a missing/unknown category is fatal."""
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("```"):  # some models wrap JSON in a code fence
            text = text.strip("`").removeprefix("json").strip()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(raw, dict):
        return None

    category = str(raw.get("category", "")).lower().strip()
    if category not in {c.value for c in Category}:
        return None
    pattern = str(raw.get("pattern", "")).lower().strip()
    if pattern not in {p.value for p in Pattern}:
        pattern = Pattern.other.value
    seasons = [s for s in (str(x).lower() for x in raw.get("seasons") or []) if s in {v.value for v in Season}]
    try:
        confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    name = str(raw.get("name") or "").strip()[:40] or "New item"

    return {
        "name": name,
        "category": category,
        "pattern": pattern,
        "formality": _clamp_int(raw.get("formality"), 1, 5, 2),
        "seasons": list(dict.fromkeys(seasons)) or [s.value for s in Season],
        "warmth": _clamp_int(raw.get("warmth"), 1, 5, 2),
        "confidence": round(confidence, 3),
        "needs_review": confidence < REVIEW_BELOW,
    }


def _backoff(attempt: int, retry_after: Optional[str] = None) -> None:
    try:
        wait = float(retry_after) if retry_after else (2 ** attempt) + random.random()
    except ValueError:
        wait = (2 ** attempt) + random.random()
    _sleep(min(wait, MAX_WAIT_S))


def _request(provider: str, url: str, headers: dict, body_for: Callable[[int, float], dict],
             extract: Callable[[dict], str], timeout) -> Optional[dict]:
    """POST with the retry rules from the plan. body_for(fmt, temperature) builds the body;
    fmt 0 = strict JSON schema, 1 = plain JSON mode, 2 = no response format (prompt only).
    Logs status + a short reason only — never the key, the image, or the body."""
    fmt, temperature, retried_bad_json = 0, 0.2, False
    for attempt in range(MAX_ATTEMPTS):
        try:
            with _SEM:
                r = requests.post(url, headers=headers, json=body_for(fmt, temperature), timeout=timeout)
        except requests.RequestException as exc:
            log.warning("%s: %s", provider, type(exc).__name__)
            _backoff(attempt)
            continue

        status = r.status_code
        if status in (401, 403):
            log.warning("%s: unauthorized (%s)", provider, status)
            return None
        if status == 402:
            log.warning("%s: budget exhausted (402)", provider)
            return None
        if status == 404:
            raise _EndpointMissing()
        if status == 429 or status >= 500:
            log.warning("%s: HTTP %s, retrying", provider, status)
            _backoff(attempt, r.headers.get("Retry-After"))
            continue
        if status == 400 and fmt < 2:
            log.warning("%s: 400 with response format %s, relaxing it", provider, fmt)
            fmt += 1
            continue
        if not r.ok:
            log.warning("%s: HTTP %s", provider, status)
            return None

        try:
            tags = _validate(extract(r.json()))
        except (ValueError, KeyError, IndexError, TypeError):
            tags = None
        if tags is None:
            if retried_bad_json:
                log.warning("%s: unusable JSON twice, giving up", provider)
                return None
            log.warning("%s: unusable JSON, retrying at temperature 0", provider)
            retried_bad_json, temperature = True, 0.0
            continue
        return tags
    return None


# ---- Pollinations (OpenAI-compatible chat completions) ----
def _pollinations_text(payload: dict) -> str:
    return payload["choices"][0]["message"]["content"]


def tag_item_pollinations(img: Image.Image) -> Optional[dict]:
    key = os.getenv("POLLINATIONS_API_KEY")
    if not key:
        return None
    try:
        data_uri = "data:image/jpeg;base64," + _encode(img)
        model = os.getenv("POLLINATIONS_MODEL") or DEFAULT_POLLINATIONS_MODEL

        def body_for(fmt: int, temperature: float) -> dict:
            body = {
                "model": model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_uri, "detail": "low"}},
                ]}],
                "temperature": temperature,
                "max_tokens": 512,
            }
            if fmt == 0:
                body["response_format"] = {"type": "json_schema", "json_schema": {
                    "name": "item_tags", "strict": True, "schema": SCHEMA}}
            elif fmt == 1:
                body["response_format"] = {"type": "json_object"}
            return body

        tags = _request("pollinations", POLLINATIONS_URL, {"Authorization": f"Bearer {key}"},
                        body_for, _pollinations_text, timeout=(5, 25))
    except Exception as exc:  # includes 404: no fallback endpoint for Pollinations
        log.warning("pollinations: %s", type(exc).__name__)
        return None
    if not tags:
        return None
    tags = {**tags, "source": "pollinations"}
    if model.startswith("community/") and tags["confidence"] < COMMUNITY_REVIEW_BELOW:
        tags["needs_review"] = True
    return tags


# ---- Gemini (Interactions API, legacy generateContent if that 404s) ----
def _gemini_text(payload: dict) -> str:
    for step in payload.get("steps", []):
        if step.get("type") == "model_output":
            for part in step.get("content", []):
                if part.get("type") == "text":
                    return part["text"]
    raise ValueError("no model_output text")


def _gemini_legacy_text(payload: dict) -> str:
    return payload["candidates"][0]["content"]["parts"][0]["text"]


def tag_item_gemini(img: Image.Image) -> Optional[dict]:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    headers = {"x-goog-api-key": key}
    try:
        b64 = _encode(img)
        model = os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        schema = {k: v for k, v in SCHEMA.items() if k != "additionalProperties"}

        def body_for(fmt: int, temperature: float) -> dict:
            body = {
                "model": model,
                "input": [{"type": "text", "text": PROMPT},
                          {"type": "image", "data": b64, "mime_type": "image/jpeg"}],
                "generation_config": {"thinking_level": "minimal", "temperature": temperature,
                                      "max_output_tokens": 512},
                "store": False,
            }
            if fmt < 2:
                body["response_format"] = {"type": "text", "mime_type": "application/json"}
                if fmt == 0:
                    body["response_format"]["schema"] = schema
            return body

        def legacy_body_for(fmt: int, temperature: float) -> dict:
            config = {"temperature": temperature}
            if fmt < 2:
                config["responseMimeType"] = "application/json"
                if fmt == 0:
                    config["responseSchema"] = schema
            return {"contents": [{"parts": [{"text": PROMPT},
                                            {"inline_data": {"mime_type": "image/jpeg", "data": b64}}]}],
                    "generationConfig": config}

        try:
            tags = _request("gemini", GEMINI_URL, headers, body_for, _gemini_text, timeout=(5, 20))
        except _EndpointMissing:
            log.warning("gemini: interactions endpoint 404, trying generateContent")
            tags = _request("gemini", GEMINI_LEGACY_URL.format(model=model), headers,
                            legacy_body_for, _gemini_legacy_text, timeout=(5, 20))
    except Exception as exc:
        log.warning("gemini: %s", type(exc).__name__)
        return None
    return tags and {**tags, "source": "gemini"}


def tag_item_vlm(img: Image.Image) -> Optional[dict]:
    """Pollinations, then Gemini. First non-None wins."""
    return tag_item_pollinations(img) or tag_item_gemini(img)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: python -m input_pipeline.tagger_vlm path/to/photo")
    if not (os.getenv("POLLINATIONS_API_KEY") or os.getenv("GEMINI_API_KEY")):
        sys.exit("No provider key: set POLLINATIONS_API_KEY or GEMINI_API_KEY in keys.env")
    result = tag_item_vlm(Image.open(sys.argv[1]))
    if result is None:
        print("None - every provider failed (see the log lines above)")
    else:
        print(json.dumps({"source": result["source"], "tags": result}, indent=2))
