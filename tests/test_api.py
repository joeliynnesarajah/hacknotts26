"""Person 4's tests — run with:  pytest"""
import io

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from backend.main import app

client = TestClient(app)


def test_list_items():
    r = client.get("/api/items")
    assert r.status_code == 200
    assert len(r.json()) >= 10


def test_score():
    r = client.post("/api/score", json={"item_ids": ["t1", "b1", "s1"]})
    assert r.status_code == 200
    assert r.json()["verdict"] in ("MATCH", "MISMATCH")


def test_unknown_item():
    assert client.post("/api/score", json={"item_ids": ["nope"]}).status_code == 404


def test_suggest():
    r = client.get("/api/suggest", params={"temperature_c": 18, "avoid_recent": False})
    assert r.status_code == 200
    assert r.json(), "expected at least one suggestion"


def test_upload_photo():
    # A red square on a white background, like a product photo
    img = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(img).rectangle([50, 50, 150, 150], fill="#c0392b")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    r = client.post("/api/items/upload", files={"photo": ("red.png", buf.getvalue(), "image/png")},
                    data={"name": "Test red top"})
    assert r.status_code == 200
    item = r.json()["item"]
    assert item["colors"][0].startswith(("#c", "#b"))  # red detected (~#c0392b / #be392b)
    client.delete(f"/api/items/{item['id']}")


# ---- Plan 1 §5.4: tag metadata, PATCH, and the 400/404 paths ----


def _red_square() -> bytes:
    img = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(img).rectangle([50, 50, 150, 150], fill="#c0392b")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _upload(name: str = "Test red top"):
    return client.post("/api/items/upload",
                       files={"photo": ("red.png", _red_square(), "image/png")},
                       data={"name": name})


def test_upload_returns_tag_meta_without_provider_key():
    r = _upload()
    assert r.status_code == 200
    body = r.json()
    assert body["needs_review"] is True
    assert set(body["tag_meta"]) == {"source", "confidence", "needs_review",
                                     "suggested_name", "updated"}
    assert body["tag_meta"]["source"] == "placeholder"
    assert body["tag_meta"]["needs_review"] is True
    item = body["item"]
    assert set(item) == {"id", "name", "image", "category", "colors",
                         "pattern", "formality", "seasons", "warmth"}
    assert item["seasons"] == ["spring", "summer", "autumn", "winter"]
    assert item["warmth"] == 2
    client.delete(f"/api/items/{item['id']}")


def test_bulk_tag_meta_contains_uploaded_item():
    item = _upload("Bulk meta top").json()["item"]
    meta = client.get("/api/tag-meta").json()
    assert item["id"] in meta
    assert meta[item["id"]]["source"] == "placeholder"
    client.delete(f"/api/items/{item['id']}")


def test_patch_updates_item_and_clears_needs_review():
    item = _upload("Patch me").json()["item"]
    r = client.patch(f"/api/items/{item['id']}", json={"category": "bottom", "formality": 4})
    assert r.status_code == 200
    assert r.json()["category"] == "bottom"
    assert r.json()["formality"] == 4
    assert client.get(f"/api/items/{item['id']}/tag-meta").json()["needs_review"] is False
    client.delete(f"/api/items/{item['id']}")


def test_patch_rejects_out_of_range_formality():
    assert client.patch("/api/items/t1", json={"formality": 9}).status_code == 422


def test_patch_unknown_item():
    assert client.patch("/api/items/nope", json={"name": "x"}).status_code == 404


def test_tag_meta_unknown_item():
    assert client.get("/api/items/nope/tag-meta").status_code == 404


def test_upload_rejects_non_image():
    r = client.post("/api/items/upload",
                    files={"photo": ("x.txt", b"not an image", "text/plain")})
    assert r.status_code == 400


def test_upload_rejects_truncated_image():
    # Image.open is lazy: only img.load() catches a cut-off file, and a 500 here
    # would be worse than a 400 during a live demo.
    r = client.post("/api/items/upload",
                    files={"photo": ("cut.png", _red_square()[:200], "image/png")})
    assert r.status_code == 400


def test_score_rejects_empty_outfit():
    assert client.post("/api/score", json={"item_ids": []}).status_code == 422


def test_try_on_page():
    r = client.get("/try-on")
    assert r.status_code == 200
    assert "Wardrobe — Try On" in r.text


def test_avatar_lifecycle():
    # Clean state
    client.delete("/api/avatar")
    assert client.get("/api/avatar").json() == {"url": None}

    # Upload avatar
    img = Image.new("RGB", (100, 200), "white")
    ImageDraw.Draw(img).rectangle([20, 20, 80, 180], fill="#336699")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    r = client.post("/api/avatar", files={"file": ("person.png", buf.getvalue(), "image/png")})
    assert r.status_code == 200
    assert r.json() == {"url": "/images/avatar.png"}

    # Get avatar
    r2 = client.get("/api/avatar")
    assert r2.status_code == 200
    assert r2.json() == {"url": "/images/avatar.png"}

    # Delete avatar
    r3 = client.delete("/api/avatar")
    assert r3.status_code == 200
    assert client.get("/api/avatar").json() == {"url": None}


def test_avatar_rejects_invalid_file():
    r = client.post("/api/avatar", files={"file": ("bad.txt", b"not an image", "text/plain")})
    assert r.status_code == 400

