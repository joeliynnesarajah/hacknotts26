"""Person 4's tests for tag metadata and editing items. Uses the throwaway DB from conftest.py."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.main import app
from input_pipeline import tagger_vlm

client = TestClient(app)

VLM_TAGS = {"name": "Green trousers", "category": "bottom", "pattern": "solid", "formality": 3,
            "seasons": ["spring", "autumn"], "warmth": 3, "confidence": 0.8, "needs_review": False}


def png_bytes():
    img = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(img).rectangle([50, 50, 150, 150], fill="#3e8e41")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def upload(name="Test item"):
    r = client.post("/api/items/upload", files={"photo": ("x.png", png_bytes(), "image/png")},
                    data={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def uploaded():
    created = []

    def make(**kw):
        body = upload(**kw)
        created.append(body["item"]["id"])
        return body
    yield make
    for item_id in created:
        client.delete(f"/api/items/{item_id}")


def test_upload_returns_tag_meta(uploaded, monkeypatch):
    monkeypatch.setenv("TAGGER_PROVIDER_ORDER", "pollinations")
    monkeypatch.setattr(tagger_vlm, "tag_item_pollinations", lambda img: {**VLM_TAGS, "source": "pollinations"})
    body = uploaded(name="My trousers")
    assert body["item"]["category"] == "bottom" and body["item"]["warmth"] == 3
    meta = body["tag_meta"]
    assert meta["source"] == "pollinations" and meta["confidence"] == 0.8
    assert meta["needs_review"] is False and meta["suggested_name"] == "Green trousers"
    assert meta["updated"]


def test_upload_with_broken_tagger_still_succeeds(uploaded, monkeypatch):
    def boom(img):
        raise RuntimeError("provider exploded")
    monkeypatch.setenv("TAGGER_PROVIDER_ORDER", "pollinations,placeholder")
    monkeypatch.setattr(tagger_vlm, "tag_item_pollinations", boom)
    body = uploaded()
    assert body["needs_review"] is True and body["tag_meta"]["source"] == "placeholder"


def test_get_tag_meta(uploaded):
    item_id = uploaded()["item"]["id"]
    r = client.get(f"/api/items/{item_id}/tag-meta")
    assert r.status_code == 200
    assert set(r.json()) == {"source", "confidence", "needs_review", "suggested_name", "updated"}
    assert item_id in client.get("/api/tag-meta").json()


def test_tag_meta_404s():
    assert client.get("/api/items/nope/tag-meta").status_code == 404
    assert client.get("/api/items/t1/tag-meta").status_code == 404  # seeded item, never tagged


def test_patch_updates_and_clears_review(uploaded):
    item_id = uploaded()["item"]["id"]
    assert client.get(f"/api/items/{item_id}/tag-meta").json()["needs_review"] is True
    r = client.patch(f"/api/items/{item_id}", json={"category": "shoes", "name": "Renamed", "formality": 4})
    assert r.status_code == 200
    assert r.json()["category"] == "shoes" and r.json()["name"] == "Renamed"
    saved = next(i for i in client.get("/api/items").json() if i["id"] == item_id)
    assert saved["formality"] == 4 and saved["category"] == "shoes"
    assert client.get(f"/api/items/{item_id}/tag-meta").json()["needs_review"] is False


def test_patch_rejects_bad_values_and_unknown_ids():
    assert client.patch("/api/items/nope", json={"formality": 3}).status_code == 404
    assert client.patch("/api/items/t1", json={"formality": 9}).status_code == 422
    assert client.patch("/api/items/t1", json={"category": "hat"}).status_code == 422


def test_delete_removes_tag_meta(uploaded):
    item_id = upload()["item"]["id"]
    client.delete(f"/api/items/{item_id}")
    assert item_id not in client.get("/api/tag-meta").json()
