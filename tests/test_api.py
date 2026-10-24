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
    assert item["colors"][0].startswith("#c")  # red detected
    client.delete(f"/api/items/{item['id']}")
