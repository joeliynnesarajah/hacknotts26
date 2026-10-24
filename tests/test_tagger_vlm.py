"""Plan 2 §4.6 — hosted tagger and fallback chain. No network."""
import copy
import json
import logging

from PIL import Image

from input_pipeline import tagger, tagger_vlm

TAG_KEYS = {
    "name",
    "category",
    "pattern",
    "formality",
    "seasons",
    "warmth",
    "confidence",
    "source",
    "needs_review",
}

VALID = {
    "name": "Navy Oxford shirt",
    "category": "top",
    "pattern": "solid",
    "formality": 3,
    "seasons": ["spring", "summer"],
    "warmth": 2,
    "confidence": 0.9,
}


def _img():
    return Image.new("RGB", (64, 64), "#1f3a5f")


class FakeResponse:
    def __init__(self, status_code, content=None, headers=None):
        self.status_code = status_code
        self._content = content
        self.headers = headers or {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        if self._content is None:
            raise ValueError("no json body")
        return {"choices": [{"message": {"role": "assistant", "content": self._content}}]}


def _install(monkeypatch, responses):
    """Patch requests.post; the last response repeats if called again."""
    calls = []
    queue = list(responses)

    def fake_post(url, **kwargs):
        # Snapshot kwargs: the caller mutates `body` between retries.
        calls.append({"url": url, **copy.deepcopy(kwargs)})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(tagger_vlm.requests, "post", fake_post)
    monkeypatch.setattr(tagger_vlm.time, "sleep", lambda *_: None)
    return calls


def _key(monkeypatch, value="sk_test_secret_value"):
    monkeypatch.setenv("POLLINATIONS_API_KEY", value)
    return value


def test_valid_payload_returns_pollinations_tags(monkeypatch):
    _key(monkeypatch)
    monkeypatch.setenv("POLLINATIONS_MODEL", "google/gemini-3.5-flash-lite")
    calls = _install(monkeypatch, [FakeResponse(200, json.dumps(VALID))])

    tags = tagger_vlm.tag_item_pollinations(_img())

    assert tags is not None
    assert set(tags) == TAG_KEYS
    assert tags["source"] == "pollinations"
    assert tags["category"] == "top"
    assert tags["pattern"] == "solid"
    assert tags["seasons"] == ["spring", "summer"]
    assert tags["needs_review"] is False
    assert len(calls) == 1


def test_low_confidence_marks_needs_review(monkeypatch):
    _key(monkeypatch)
    _install(monkeypatch, [FakeResponse(200, json.dumps(dict(VALID, confidence=0.2)))])

    tags = tagger_vlm.tag_item_pollinations(_img())

    assert tags is not None
    assert tags["needs_review"] is True


def test_community_model_always_needs_review(monkeypatch):
    _key(monkeypatch)
    payload = json.dumps(dict(VALID, confidence=1.0))

    monkeypatch.setenv(
        "POLLINATIONS_MODEL", "community/scriptsnsenses-sys/diffusiongema-26B-free"
    )
    _install(monkeypatch, [FakeResponse(200, payload)])
    community_tags = tagger_vlm.tag_item_pollinations(_img())

    assert community_tags is not None
    assert community_tags["confidence"] == 1.0  # preserved, not rewritten
    assert community_tags["needs_review"] is True

    monkeypatch.setenv("POLLINATIONS_MODEL", "google/gemini-3.5-flash-lite")
    _install(monkeypatch, [FakeResponse(200, payload)])
    google_tags = tagger_vlm.tag_item_pollinations(_img())

    assert google_tags is not None
    assert google_tags["needs_review"] is False


def test_formality_and_warmth_are_clamped(monkeypatch):
    _key(monkeypatch)
    _install(monkeypatch, [FakeResponse(200, json.dumps(dict(VALID, formality=9, warmth=0)))])

    tags = tagger_vlm.tag_item_pollinations(_img())

    assert tags is not None
    assert tags["formality"] == 5
    assert tags["warmth"] == 1


def test_missing_required_field_is_a_failure(monkeypatch):
    _key(monkeypatch)
    data = dict(VALID)
    del data["confidence"]
    calls = _install(monkeypatch, [FakeResponse(200, json.dumps(data))])

    assert tagger_vlm.tag_item_pollinations(_img()) is None
    # one initial attempt plus one temperature-0 retry
    assert len(calls) == 2


def test_fenced_json_parses(monkeypatch):
    _key(monkeypatch)
    fenced = "```json\n" + json.dumps(VALID) + "\n```"
    _install(monkeypatch, [FakeResponse(200, fenced)])

    tags = tagger_vlm.tag_item_pollinations(_img())

    assert tags is not None
    assert tags["name"] == "Navy Oxford shirt"
    assert tags["source"] == "pollinations"


def test_prose_error_in_200_body_retries_once_then_none(monkeypatch):
    _key(monkeypatch)
    prose = "The account behind this API key doesn't have enough credits to run this model."
    calls = _install(monkeypatch, [FakeResponse(200, prose)])

    assert tagger_vlm.tag_item_pollinations(_img()) is None
    assert len(calls) == 2
    assert calls[1]["json"]["temperature"] == 0


def test_402_returns_none_with_exactly_one_call(monkeypatch):
    _key(monkeypatch)
    calls = _install(monkeypatch, [FakeResponse(402)])

    assert tagger_vlm.tag_item_pollinations(_img()) is None
    assert len(calls) == 1


def test_429_exhausts_two_retries_then_none(monkeypatch):
    _key(monkeypatch)
    calls = _install(monkeypatch, [FakeResponse(429)])

    assert tagger_vlm.tag_item_pollinations(_img()) is None
    assert len(calls) == 3  # initial + 2 retries


def test_500_once_then_success(monkeypatch):
    _key(monkeypatch)
    calls = _install(
        monkeypatch,
        [FakeResponse(500), FakeResponse(200, json.dumps(VALID))],
    )

    tags = tagger_vlm.tag_item_pollinations(_img())

    assert tags is not None
    assert tags["source"] == "pollinations"
    assert len(calls) == 2


def test_400_retries_once_with_json_object(monkeypatch):
    _key(monkeypatch)
    calls = _install(
        monkeypatch,
        [FakeResponse(400), FakeResponse(200, json.dumps(VALID))],
    )

    tags = tagger_vlm.tag_item_pollinations(_img())

    assert tags is not None
    assert calls[0]["json"]["response_format"]["type"] == "json_schema"
    assert calls[1]["json"]["response_format"] == {"type": "json_object"}
    assert len(calls) == 2


def test_no_key_returns_none_without_calling(monkeypatch):
    monkeypatch.setenv("POLLINATIONS_API_KEY", "")
    calls = []
    monkeypatch.setattr(tagger_vlm.requests, "post", lambda *a, **k: calls.append(1))

    assert tagger_vlm.tag_item_pollinations(_img()) is None
    assert calls == []


def test_key_and_base64_never_logged(monkeypatch, caplog):
    key = _key(monkeypatch, "sk_super_secret_key_123")
    calls = _install(monkeypatch, [FakeResponse(200, json.dumps(VALID))])
    expected_b64 = tagger_vlm._encode(_img())

    with caplog.at_level(logging.DEBUG):
        tags = tagger_vlm.tag_item_pollinations(_img())

    assert tags is not None
    # Prove the secret and the payload really were in the request...
    sent_uri = calls[0]["json"]["messages"][0]["content"][1]["image_url"]["url"]
    assert expected_b64 in sent_uri
    # ...and never in the logs.
    assert key not in caplog.text
    assert expected_b64 not in caplog.text
    assert "data:image" not in caplog.text


def test_provider_order_placeholder_skips_the_network(monkeypatch):
    monkeypatch.setenv("TAGGER_PROVIDER_ORDER", "placeholder")
    calls = []
    monkeypatch.setattr(tagger_vlm.requests, "post", lambda *a, **k: calls.append(1))

    tags = tagger.tag_item(_img())

    assert calls == []
    assert set(tags) == TAG_KEYS
    assert tags["source"] == "placeholder"
    assert tags["needs_review"] is True
    assert tags["seasons"] == ["spring", "summer", "autumn", "winter"]


def test_gemini_then_placeholder_when_pollinations_raises(monkeypatch):
    monkeypatch.setenv("TAGGER_PROVIDER_ORDER", "gemini,placeholder")

    def boom(img):
        raise RuntimeError("pollinations exploded")

    monkeypatch.setattr(tagger, "tag_item_pollinations", boom)

    tags = tagger.tag_item(_img())

    assert tags["source"] == "placeholder"
    assert tags["needs_review"] is True


def test_provider_order_ignores_unknown_names(monkeypatch):
    monkeypatch.setenv("TAGGER_PROVIDER_ORDER", "nope, gemini ,,")
    assert tagger._provider_order() == ["gemini"]

    monkeypatch.setenv("TAGGER_PROVIDER_ORDER", "")
    assert tagger._provider_order() == tagger.DEFAULT_ORDER


def test_empty_seasons_default_to_all_four():
    tags = tagger_vlm._validate(json.dumps(dict(VALID, seasons=[])))

    assert tags is not None
    assert tags["seasons"] == ["spring", "summer", "autumn", "winter"]


def test_unknown_enum_is_a_failure_not_a_guess():
    assert tagger_vlm._validate(json.dumps(dict(VALID, category="hat"))) is None
    assert tagger_vlm._validate(None) is None


def test_long_name_is_truncated_not_discarded():
    long_name = "Navy blue Oxford cotton button-down shirt with a spread collar"
    assert len(long_name) > 40
    tags = tagger_vlm._validate(json.dumps(dict(VALID, name=long_name)))

    assert tags is not None
    assert len(tags["name"]) == 40
    assert tags["category"] == "top"  # the rest of the tag survives


def test_out_of_range_confidence_is_clamped():
    tags = tagger_vlm._validate(json.dumps(dict(VALID, confidence=1.2)))

    assert tags is not None
    assert tags["confidence"] == 1.0


def test_blank_name_falls_back():
    tags = tagger_vlm._validate(json.dumps(dict(VALID, name="   ")))

    assert tags is not None
    assert tags["name"] == "New item"
