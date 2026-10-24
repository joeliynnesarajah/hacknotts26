import io

from fastapi.testclient import TestClient
from PIL import Image

from backend import main

client = TestClient(main.app)


def _png_bytes():
    image = Image.new("RGB", (32, 48), "red")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_upload_get_and_delete_avatar(tmp_path, monkeypatch):
    avatar_path = tmp_path / "images" / "avatar.png"
    monkeypatch.setattr(main, "AVATAR_PATH", avatar_path)
    monkeypatch.setattr(main, "remove_background", lambda image: image)

    assert client.get("/api/avatar").json() == {"url": None}

    response = client.post("/api/avatar", files={"file": ("avatar.png", _png_bytes(), "image/png")})
    assert response.status_code == 200
    assert response.json() == {"url": "/images/avatar.png"}
    assert avatar_path.is_file()
    with Image.open(avatar_path) as saved:
        assert saved.format == "PNG"
        assert saved.mode == "RGBA"

    assert client.get("/api/avatar").json() == {"url": "/images/avatar.png"}
    assert client.delete("/api/avatar").json() == {"url": None}
    assert not avatar_path.exists()
    assert client.delete("/api/avatar").status_code == 200


def test_upload_avatar_rejects_non_image():
    response = client.post("/api/avatar", files={"file": ("avatar.txt", b"not an image", "text/plain")})
    assert response.status_code == 400


def test_try_on_page_is_served():
    response = client.get("/try-on.html")
    assert response.status_code == 200
    assert "Try-On" in response.text
    assert "/static/try-on.js" in response.text
