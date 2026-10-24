"""Tests for the try-on page and its avatar endpoints. The avatar file goes to a temp dir,
so a real data/images/avatar.png is never touched."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import backend.main as main
from input_pipeline.background import fit_to_frame

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def temp_avatar(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "AVATAR_PATH", tmp_path / "avatar.png")


def person_photo() -> bytes:
    """A dark 'person' shape standing on a white background."""
    img = Image.new("RGB", (300, 600), "white")
    d = ImageDraw.Draw(img)
    d.ellipse([120, 40, 180, 100], fill="#3a2a20")     # head
    d.rectangle([100, 100, 200, 380], fill="#2b4a7a")  # body
    d.rectangle([110, 380, 190, 560], fill="#2b2b2b")  # legs
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_no_avatar_means_silhouette():
    assert client.get("/api/avatar").json() == {"url": None}


def test_upload_get_delete_avatar():
    r = client.post("/api/avatar", files={"photo": ("me.png", person_photo(), "image/png")})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("/images/avatar.png?v=")
    assert client.get("/api/avatar").json()["url"] == url

    saved = Image.open(main.AVATAR_PATH)
    assert saved.size == (360, 840) and saved.mode == "RGBA"
    assert saved.getpixel((5, 5))[3] == 0  # background removed / transparent corner

    assert client.delete("/api/avatar").json() == {"url": None}
    assert client.get("/api/avatar").json() == {"url": None}
    assert client.delete("/api/avatar").status_code == 200  # deleting twice is fine


def test_avatar_rejects_non_images():
    r = client.post("/api/avatar", files={"photo": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_fit_to_frame_stands_figure_on_the_floor():
    cutout = Image.new("RGBA", (50, 200), (0, 0, 0, 0))
    ImageDraw.Draw(cutout).rectangle([10, 20, 40, 180], fill=(200, 0, 0, 255))
    framed = fit_to_frame(cutout)
    x0, y0, x1, y1 = framed.getbbox()
    assert framed.size == (360, 840)
    assert y0 <= 840 * 0.03 and 840 - y1 <= 840 * 0.03  # head near the top, feet near the bottom
    assert abs((x0 + x1) / 2 - 180) <= 2                 # centred


def test_try_on_page_and_assets_are_served():
    page = client.get("/try-on")
    assert page.status_code == 200 and "DRESSING ROOM" in page.text
    for path in ("/static/try-on.js", "/static/sounds.js", "/static/cher-silhouette.svg"):
        assert client.get(path).status_code == 200, path
