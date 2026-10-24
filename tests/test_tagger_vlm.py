"""Person 1's tests for the hosted vision taggers — no network: requests.post is faked."""
import json
import logging

import pytest
import requests
from PIL import Image

from input_pipeline import tagger_vlm

GOOD = {"name": "Navy Oxford shirt", "category": "top", "pattern": "solid", "formality": 3,
        "seasons": ["spring", "autumn"], "warmth": 2, "confidence": 0.82}
KEY = "sk_test_SECRET_KEY_123"


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.ok = 200 <= status < 300

    def json(self):
        return self._payload


def pollinations_reply(content):
    text = content if isinstance(content, str) else json.dumps(content)
    return FakeResponse(200, {"choices": [{"message": {"role": "assistant", "content": text}}]})


def gemini_reply(content):
    text = content if isinstance(content, str) else json.dumps(content)
    return FakeResponse(200, {"steps": [{"type": "model_output", "content": [{"type": "text", "text": text}]}]})


@pytest.fixture
def img():
    return Image.new("RGBA", (64, 64), (30, 60, 120, 255))


@pytest.fixture
def fake_post(monkeypatch):
    """Queue up responses; records every call's url and body."""
    calls, queue = [], []

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(tagger_vlm.requests, "post", post)
    monkeypatch.setattr(tagger_vlm, "_sleep", lambda s: None)
    post.calls, post.queue = calls, queue
    return post


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("POLLINATIONS_API_KEY", KEY)
    monkeypatch.setenv("GEMINI_API_KEY", KEY)


# ---- validation ----
def test_validate_clamps_and_defaults():
    tags = tagger_vlm._validate({**GOOD, "formality": 9, "warmth": 0, "confidence": 3,
                                 "pattern": "polka", "seasons": ["summer", "monsoon"]})
    assert tags["formality"] == 5 and tags["warmth"] == 1 and tags["confidence"] == 1.0
    assert tags["pattern"] == "other"
    assert tags["seasons"] == ["summer"]


def test_validate_fills_missing_fields():
    tags = tagger_vlm._validate({"category": "shoes"})
    assert tags["formality"] == 2 and tags["warmth"] == 2 and tags["name"] == "New item"
    assert len(tags["seasons"]) == 4
    assert tags["needs_review"] is True  # default confidence 0.5 < 0.55


def test_validate_rejects_unknown_category_and_junk():
    assert tagger_vlm._validate({**GOOD, "category": "hat"}) is None
    assert tagger_vlm._validate("not json") is None
    assert tagger_vlm._validate("```json\n" + json.dumps(GOOD) + "\n```")["category"] == "top"


# ---- Pollinations ----
def test_no_key_means_no_network(fake_post, monkeypatch, img):
    monkeypatch.setenv("POLLINATIONS_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert tagger_vlm.tag_item_pollinations(img) is None
    assert tagger_vlm.tag_item_gemini(img) is None
    assert fake_post.calls == []


def test_pollinations_success(fake_post, keys, img):
    fake_post.queue.append(pollinations_reply(GOOD))
    tags = tagger_vlm.tag_item_pollinations(img)
    assert tags["source"] == "pollinations"
    assert tags["category"] == "top" and tags["formality"] == 3
    assert tags["needs_review"] is False
    body = fake_post.calls[0]["json"]
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_low_confidence_needs_review(fake_post, keys, img):
    fake_post.queue.append(pollinations_reply({**GOOD, "confidence": 0.3}))
    assert tagger_vlm.tag_item_pollinations(img)["needs_review"] is True


def test_402_gives_up_immediately(fake_post, keys, img):
    fake_post.queue.append(FakeResponse(402))
    assert tagger_vlm.tag_item_pollinations(img) is None
    assert len(fake_post.calls) == 1


def test_401_gives_up_immediately(fake_post, keys, img):
    fake_post.queue.append(FakeResponse(401))
    assert tagger_vlm.tag_item_pollinations(img) is None
    assert len(fake_post.calls) == 1


def test_429_retries_then_gives_up(fake_post, keys, img):
    fake_post.queue.extend([FakeResponse(429, headers={"Retry-After": "1"})] * 3)
    assert tagger_vlm.tag_item_pollinations(img) is None
    assert len(fake_post.calls) == 3


def test_429_then_success(fake_post, keys, img):
    fake_post.queue.extend([FakeResponse(429), pollinations_reply(GOOD)])
    assert tagger_vlm.tag_item_pollinations(img)["source"] == "pollinations"


def test_timeout_retries(fake_post, keys, img):
    fake_post.queue.extend([requests.Timeout(), pollinations_reply(GOOD)])
    assert tagger_vlm.tag_item_pollinations(img) is not None


def test_400_relaxes_response_format(fake_post, keys, img):
    fake_post.queue.extend([FakeResponse(400), pollinations_reply(GOOD)])
    assert tagger_vlm.tag_item_pollinations(img) is not None
    assert fake_post.calls[1]["json"]["response_format"] == {"type": "json_object"}


def test_bad_json_retries_once_at_temperature_zero(fake_post, keys, img):
    fake_post.queue.extend([pollinations_reply("oops"), pollinations_reply("still oops")])
    assert tagger_vlm.tag_item_pollinations(img) is None
    assert len(fake_post.calls) == 2
    assert fake_post.calls[1]["json"]["temperature"] == 0.0


def test_secrets_never_logged(fake_post, keys, img, caplog):
    caplog.set_level(logging.DEBUG)
    fake_post.queue.extend([FakeResponse(429), FakeResponse(500), FakeResponse(503)])
    tagger_vlm.tag_item_pollinations(img)
    b64 = tagger_vlm._encode(img)
    assert caplog.records, "expected some log lines"
    assert KEY not in caplog.text and b64[:40] not in caplog.text


# ---- Gemini ----
def test_gemini_success(fake_post, keys, img):
    fake_post.queue.append(gemini_reply(GOOD))
    tags = tagger_vlm.tag_item_gemini(img)
    assert tags["source"] == "gemini"
    body = fake_post.calls[0]["json"]
    assert body["store"] is False and body["input"][1]["mime_type"] == "image/jpeg"
    assert fake_post.calls[0]["headers"] == {"x-goog-api-key": KEY}


def test_gemini_falls_back_to_legacy_endpoint_on_404(fake_post, keys, img):
    legacy = FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}]})
    fake_post.queue.extend([FakeResponse(404), legacy])
    assert tagger_vlm.tag_item_gemini(img)["source"] == "gemini"
    assert fake_post.calls[1]["url"].endswith(":generateContent")


def test_vlm_tries_pollinations_then_gemini(fake_post, keys, img):
    fake_post.queue.extend([FakeResponse(402), gemini_reply(GOOD)])
    assert tagger_vlm.tag_item_vlm(img)["source"] == "gemini"


def test_transparent_cutout_encodes_on_white():
    import base64
    import io
    clear = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    decoded = Image.open(io.BytesIO(base64.b64decode(tagger_vlm._encode(clear))))
    assert decoded.getpixel((5, 5))[0] > 240  # white, not black
