"""Plan 1 §5.4 — the pipeline adapter is the seam between Plan 1 and Plan 2."""
from PIL import Image

from input_pipeline import pipeline
from shared.schema import Item


def _photo():
    return Image.new("RGB", (120, 120), "#1f3a5f")


def test_process_photo_with_meta_returns_item_flag_and_meta():
    item, needs_review, meta = pipeline.process_photo_with_meta(_photo(), name="Navy top")
    assert isinstance(item, Item)
    assert isinstance(needs_review, bool)
    assert set(meta) == {"source", "confidence", "needs_review", "suggested_name"}
    assert meta["needs_review"] is needs_review
    assert item.name == "Navy top"
    assert item.image.startswith("images/")


def test_seasons_and_warmth_come_from_the_tagger(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "tag_item",
        lambda img: {
            "category": "top",
            "pattern": "solid",
            "formality": 3,
            "seasons": ["winter"],
            "warmth": 5,
            "confidence": 0.9,
            "needs_review": False,
            "source": "pollinations",
            "name": "Chunky knit",
        },
    )
    item, needs_review, meta = pipeline.process_photo_with_meta(_photo())
    assert [s.value for s in item.seasons] == ["winter"]
    assert item.warmth == 5
    assert needs_review is False
    assert meta["source"] == "pollinations"
    assert meta["suggested_name"] == "Chunky knit"
    assert meta["confidence"] == 0.9


def test_process_photo_still_returns_two_values():
    item, needs_review = pipeline.process_photo(_photo(), name="Wrapper")
    assert isinstance(item, Item)
    assert isinstance(needs_review, bool)
