"""Person 1's tests for the fallback chain and the photo -> Item pipeline. No network."""
import pytest
from PIL import Image, ImageDraw

from input_pipeline import pipeline, tagger, tagger_vlm

VLM_TAGS = {"name": "Wool coat", "category": "outerwear", "pattern": "solid", "formality": 3,
            "seasons": ["autumn", "winter"], "warmth": 5, "confidence": 0.9, "needs_review": False}


@pytest.fixture
def providers(monkeypatch):
    """Every provider fails unless a test says otherwise; records which ones ran."""
    ran = []

    def make(name, result=None):
        def fn(img):
            ran.append(name)
            if isinstance(result, Exception):
                raise result
            return result and {**result, "source": name}
        return fn

    def set_(name, result=None):
        target = tagger if name == "clip" else tagger_vlm
        monkeypatch.setattr(target, f"tag_item_{name}", make(name, result))

    for name in ("pollinations", "gemini", "clip"):
        set_(name)
    monkeypatch.delenv("TAGGER_PROVIDER_ORDER", raising=False)  # default order
    set_.ran = ran
    return set_


@pytest.fixture
def photo():
    img = Image.new("RGB", (120, 120), "white")
    ImageDraw.Draw(img).rectangle([30, 30, 90, 90], fill="#7a4a2a")
    return img


@pytest.fixture
def no_disk(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "IMAGES_DIR", tmp_path)


def test_pollinations_first(providers, photo):
    providers("pollinations", VLM_TAGS)
    providers("gemini", VLM_TAGS)
    assert tagger.tag_item(photo)["source"] == "pollinations"
    assert providers.ran == ["pollinations"]


def test_gemini_when_pollinations_fails(providers, photo):
    providers("gemini", VLM_TAGS)
    assert tagger.tag_item(photo)["source"] == "gemini"
    assert providers.ran == ["pollinations", "gemini"]


def test_placeholder_when_everything_fails(providers, photo):
    tags = tagger.tag_item(photo)
    assert tags["source"] == "placeholder" and tags["needs_review"] is True
    assert providers.ran == ["pollinations", "gemini", "clip"]


def test_a_raising_provider_does_not_stop_the_chain(providers, photo):
    providers("pollinations", RuntimeError("boom"))
    providers("gemini", VLM_TAGS)
    assert tagger.tag_item(photo)["source"] == "gemini"


def test_provider_order_env(providers, photo, monkeypatch):
    providers("pollinations", VLM_TAGS)
    providers("gemini", VLM_TAGS)
    monkeypatch.setenv("TAGGER_PROVIDER_ORDER", "gemini, nonsense ,placeholder")
    assert tagger.tag_item(photo)["source"] == "gemini"
    assert providers.ran == ["gemini"]


def test_pipeline_keeps_seasons_and_warmth(providers, photo, no_disk):
    providers("pollinations", VLM_TAGS)
    item, needs_review, meta = pipeline.process_photo_with_meta(photo, name="My coat")
    assert item.name == "My coat"  # what the user typed wins
    assert item.warmth == 5 and [s.value for s in item.seasons] == ["autumn", "winter"]
    assert meta == {"source": "pollinations", "confidence": 0.9, "needs_review": False,
                    "suggested_name": "Wool coat"}
    assert needs_review is False


def test_pipeline_uses_suggested_name_when_left_blank(providers, photo, no_disk):
    providers("gemini", VLM_TAGS)
    item, _, _ = pipeline.process_photo_with_meta(photo, name="New item")
    assert item.name == "Wool coat"


def test_pipeline_placeholder_still_makes_an_item(providers, photo, no_disk):
    item, needs_review, meta = pipeline.process_photo_with_meta(photo, item_id="fixed-id")
    assert item.id == "fixed-id" and item.category.value == "top"
    assert needs_review is True and meta["source"] == "placeholder"


def test_out_of_range_values_never_crash_item(monkeypatch, photo, no_disk):
    """Bad numbers from a provider are clamped by _validate before they reach Item."""
    raw = {**VLM_TAGS, "formality": 11, "warmth": -2}
    monkeypatch.setattr(tagger_vlm, "tag_item_pollinations",
                        lambda img: {**tagger_vlm._validate(raw), "source": "pollinations"})
    monkeypatch.setenv("TAGGER_PROVIDER_ORDER", "pollinations")
    item, _, _ = pipeline.process_photo_with_meta(photo)
    assert item.formality == 5 and item.warmth == 1


def test_process_photo_is_backward_compatible(providers, photo, no_disk):
    item, needs_review = pipeline.process_photo(photo, name="Thing")
    assert item.name == "Thing" and needs_review is True
