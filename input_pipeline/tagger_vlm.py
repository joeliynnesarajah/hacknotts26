"""
Hosted vision taggers: Pollinations (primary) and direct Gemini (stub).

`tag_item_pollinations` returns a complete tag dict or None. It never raises —
the fallback chain in `input_pipeline.tagger` depends on None.

Smoke test one image:
    python -m input_pipeline.tagger_vlm data/images/t2.png

The API key, the base64 payload, and the request body are never logged. Only a
status code plus a short reason is.
"""
import base64
import io
import json
import logging
import os
import random
import re
import threading
import time
from typing import Any, Literal

import requests
from PIL import Image
from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger(__name__)

URL = "https://gen.pollinations.ai/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-3.5-flash-lite"
ALL_SEASONS = ["spring", "summer", "autumn", "winter"]
REAL_SOURCES = ("pollinations", "gemini")
REVIEW_THRESHOLD = 0.55

# One in-flight request per process; the API is cheap but not free.
_SEM = threading.Semaphore(1)

# Community models wrap JSON in ```json ... ``` fences; strip them before parsing.
_FENCE_START = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_FENCE_END = re.compile(r"\s*```\s*$")

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Short human name, max 40 chars"},
        "category": {
            "type": "string",
            "enum": ["top", "bottom", "dress", "shoes", "outerwear", "accessory"],
        },
        "pattern": {
            "type": "string",
            "enum": ["solid", "stripe", "plaid", "floral", "graphic", "other"],
        },
        "formality": {"type": "integer", "minimum": 1, "maximum": 5},
        "seasons": {
            "type": "array",
            "items": {"type": "string", "enum": ["spring", "summer", "autumn", "winter"]},
        },
        "warmth": {"type": "integer", "minimum": 1, "maximum": 5},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["name", "category", "pattern", "formality", "seasons", "warmth", "confidence"],
    "additionalProperties": False,
}

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


class TagOut(BaseModel):
    """Mirror of SCHEMA. Unknown enum values are a validation failure."""

    name: str = Field(max_length=40)
    category: Literal["top", "bottom", "dress", "shoes", "outerwear", "accessory"]
    pattern: Literal["solid", "stripe", "plaid", "floral", "graphic", "other"]
    formality: int = Field(ge=1, le=5)
    seasons: list[Literal["spring", "summer", "autumn", "winter"]]
    warmth: int = Field(ge=1, le=5)
    confidence: float = Field(ge=0, le=1)


def _encode(img: Image.Image) -> str:
    """RGB, max 768 px per side, JPEG q85, base64."""
    img = img.convert("RGB")
    img.thumbnail((768, 768))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _strip_fence(raw: str) -> str:
    text = _FENCE_START.sub("", raw.strip())
    return _FENCE_END.sub("", text).strip()


def _clamp_1_to_5(value: Any) -> Any:
    """Clamp formality/warmth into 1-5. Non-numeric values pass through and fail validation."""
    try:
        return max(1, min(5, int(value)))
    except (TypeError, ValueError):
        return value


def _clamp_unit(value: Any) -> Any:
    """Clamp confidence into 0-1; models sometimes overshoot. Non-numeric passes through."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return value


def _model_id() -> str:
    return os.getenv("POLLINATIONS_MODEL", DEFAULT_MODEL)


def _validate(raw: str, source: str = "pollinations", model: str | None = None) -> dict | None:
    """Parse model output into a tag dict, or None on any failure.

    Fences are stripped, formality/warmth are clamped, empty seasons default to
    all four (an item with no seasons is filtered out of every suggestion by
    outfit_logic.generate.suits_weather). Unknown enums are a failure, not a guess.

    Community routes are uncalibrated: they return confidence 0.9-1.0 even on
    wrong tags, so they always need review. Their confidence value is preserved.
    """
    if not isinstance(raw, str):
        return None
    model = _model_id() if model is None else model
    try:
        data = json.loads(_strip_fence(raw))
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    for field in ("formality", "warmth"):
        if field in data:
            data[field] = _clamp_1_to_5(data[field])
    # A 41-char name or a confidence of 1.2 must not discard an otherwise good tag,
    # and a blank name would render as an empty suggestion.
    if "name" in data:
        data["name"] = str(data["name"]).strip()[:40] or "New item"
    if "confidence" in data:
        data["confidence"] = _clamp_unit(data["confidence"])

    try:
        out = TagOut.model_validate(data)
    except (ValidationError, TypeError, ValueError):
        return None

    tags = out.model_dump()
    if not tags["seasons"]:
        tags["seasons"] = list(ALL_SEASONS)
    tags["source"] = source
    community = model.startswith("community/")
    tags["needs_review"] = community or not (
        source in REAL_SOURCES and tags["confidence"] >= REVIEW_THRESHOLD
    )
    return tags


def _extract_text(payload: Any) -> str:
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("no assistant content") from exc
    if not isinstance(content, str):
        raise ValueError("no assistant content")
    return content


def _body(data_uri: str, model: str) -> dict:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
                ],
            }
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "item_tags", "strict": True, "schema": SCHEMA},
        },
        "temperature": 0.2,
        "max_tokens": 512,
    }


def _sleep_before_retry(attempt: int, response: requests.Response) -> None:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            time.sleep(float(retry_after))
            return
        except ValueError:
            pass  # HTTP-date or junk; fall back to exponential backoff
    time.sleep((2 ** attempt) + random.random())


def tag_item_pollinations(img: Image.Image) -> dict | None:
    """Tag one image via Pollinations. Never raises; returns None on any failure.

    Retries: 429/5xx up to 2 times, one 400 retry with `json_object`, and one
    temperature-0 retry when the content does not parse/validate. 401/402 are
    terminal (no retry).
    """
    key = os.getenv("POLLINATIONS_API_KEY")
    if not key:
        log.info("pollinations: no API key")
        return None

    try:
        data_uri = "data:image/jpeg;base64," + _encode(img)
    except Exception as exc:  # noqa: BLE001 - this function must never raise
        log.warning("pollinations: could not encode image (%s)", type(exc).__name__)
        return None
    model = _model_id()
    body = _body(data_uri, model)
    backoff_retries = 0
    json_object_retried = False
    parse_retried = False

    while True:
        try:
            with _SEM:
                response = requests.post(
                    URL,
                    headers={"Authorization": f"Bearer {key}"},
                    json=body,
                    timeout=(5, 25),
                )
        except requests.RequestException as exc:
            log.warning("pollinations: request failed (%s)", type(exc).__name__)
            return None

        status = response.status_code

        if status in (401, 402):
            reason = "unauthorized" if status == 401 else "budget exhausted"
            log.warning("pollinations: %s (HTTP %s)", reason, status)
            return None

        if status == 429 or 500 <= status < 600:
            if backoff_retries >= 2:
                log.warning("pollinations: giving up after HTTP %s", status)
                return None
            _sleep_before_retry(backoff_retries, response)
            backoff_retries += 1
            continue

        if status == 400 and not json_object_retried:
            # Model may not support json_schema; the prompt already demands JSON.
            json_object_retried = True
            body["response_format"] = {"type": "json_object"}
            continue

        if not response.ok:
            log.warning("pollinations: HTTP %s", status)
            return None

        try:
            raw = _extract_text(response.json())
        except (ValueError, TypeError):
            raw = None

        tags = _validate(raw, source="pollinations", model=model) if raw else None
        if tags is not None:
            return tags

        if not parse_retried:
            # HTTP 200 with a prose error string is a failure, not a success.
            parse_retried = True
            body["temperature"] = 0
            continue

        log.warning("pollinations: unparseable response (HTTP %s)", status)
        return None


def tag_item_gemini(img: Image.Image) -> dict | None:
    # not wired: GEMINI_API_KEY is still a placeholder
    return None


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    load_dotenv()  # so the smoke command sees the same keys as the server
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from input_pipeline.tagger import _provider_order, tag_item

    path = sys.argv[1] if len(sys.argv) > 1 else "data/images/t2.png"
    try:
        image = Image.open(path)
    except Exception as exc:  # noqa: BLE001 - smoke command must always exit 0
        print(f"could not open {path}: {exc}")
        sys.exit(0)

    tags = tag_item(image)
    if tags["source"] == "placeholder":
        if not (os.getenv("POLLINATIONS_API_KEY") or os.getenv("GEMINI_API_KEY")):
            print("no provider key")
        elif any(p in ("pollinations", "gemini") for p in _provider_order()):
            print("no provider available (see log above)")

    print(json.dumps({"source": tags["source"], "tags": tags}, indent=2))
    sys.exit(0)
