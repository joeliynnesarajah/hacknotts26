"""Tests for the photoreal try-on (input_pipeline/tryon_render.py + its endpoints) and the
random "Dress me" pick. No network: requests.post is faked; renders go to conftest's temp dir."""
import base64
import io
import json
import random
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import backend.main as main
from input_pipeline import tryon_render
from outfit_logic.scorer import pick_outfit
from shared.schema import Item, Weather

client = TestClient(main.app)
SAMPLE = {i["id"]: Item(**i) for i in json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "sample_items.json").read_text())}


def png_b64(color="red") -> str:
    buf = io.BytesIO()
    Image.new("RGB", (16, 24), color).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload if payload is not None else {"data": [{"b64_json": png_b64()}]}

    def json(self):
        return self._payload


@pytest.fixture
def fake_post(monkeypatch):
    calls, queue = [], []

    def post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "json": json})
        return queue.pop(0) if queue else FakeResponse()

    monkeypatch.setattr(tryon_render.requests, "post", post)
    monkeypatch.setattr(tryon_render, "_sleep", lambda s: None)
    monkeypatch.setenv("POLLINATIONS_API_KEY", "sk_test")
    monkeypatch.setenv("TRYON_MODELS", "model-a,model-b")
    post.calls, post.queue = calls, queue
    return post


@pytest.fixture(autouse=True)
def clean_renders():
    shutil.rmtree(tryon_render.RENDER_DIR, ignore_errors=True)
    tryon_render.RENDER_DIR.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture
def person(tmp_path):
    p = tmp_path / "person.png"
    Image.new("RGBA", (40, 80), (200, 160, 140, 255)).save(p)
    return p


def outfit(*ids):
    return [SAMPLE[i] for i in ids]


# ---- prompt, key, inputs ----
def test_prompt_numbers_garments_after_the_person():
    items = tryon_render.ordered(outfit("s1", "b1", "t1", "o1"))
    assert [it.category.value for it in items] == ["outerwear", "top", "bottom", "shoes"]
    prompt = tryon_render.build_prompt(items)
    assert "Image 1 shows a person" in prompt
    assert "jacket or coat from image 2" in prompt and "shoes from image 5" in prompt


def test_render_key_depends_on_person_and_items(person, tmp_path):
    k1 = tryon_render.render_key(person, outfit("t1", "b1", "s1"))
    assert k1 == tryon_render.render_key(person, outfit("s1", "b1", "t1"))  # order doesn't matter
    assert k1 != tryon_render.render_key(person, outfit("t2", "b1", "s1"))
    other = tmp_path / "other.png"
    Image.new("RGBA", (40, 80), (10, 10, 10, 255)).save(other)
    assert k1 != tryon_render.render_key(other, outfit("t1", "b1", "s1"))


def test_garments_are_cropped_and_flattened():
    uri = tryon_render.garment_uri(Path(tryon_render.ROOT / "data" / "images" / "s1.png"))
    img = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    assert img.mode == "RGB" and img.width > img.height * 2  # shoe strip, not a padded square


# ---- render ----
def test_render_success_saves_jpeg_and_status(fake_post, person):
    items = outfit("t1", "b1", "s1")
    key = tryon_render.render_key(person, items)
    status = tryon_render.render(key, person, items)
    assert status["status"] == "done" and status["model"] == "model-a"
    assert Image.open(tryon_render.image_path(key)).format == "JPEG"
    assert tryon_render.read_status(key)["status"] == "done"
    body = fake_post.calls[0]["json"]
    assert len(body["image"]) == 4 and body["image"][0]["image_url"].startswith("data:image/jpeg;base64,")


def test_budget_exhausted_falls_through_to_next_model(fake_post, person):
    fake_post.queue.append(FakeResponse(402, {"error": {"code": "KEY_BUDGET_EXHAUSTED"}}))
    items = outfit("d1", "s2")
    status = tryon_render.render(tryon_render.render_key(person, items), person, items)
    assert status["status"] == "done" and status["model"] == "model-b"
    assert [c["json"]["model"] for c in fake_post.calls] == ["model-a", "model-b"]


def test_everything_failing_records_why(fake_post, person):
    fake_post.queue.extend([FakeResponse(400, {"error": {"code": "content_blocked"}}),
                            FakeResponse(402, {"error": {"code": "INSUFFICIENT_BALANCE"}})])
    items = outfit("t1", "b1", "s1")
    key = tryon_render.render_key(person, items)
    status = tryon_render.render(key, person, items)
    assert status["status"] == "failed"
    assert "content_blocked" in status["reason"] and "INSUFFICIENT_BALANCE" in status["reason"]
    assert not tryon_render.image_path(key).exists()


def test_rate_limit_is_retried_once(fake_post, person):
    fake_post.queue.extend([FakeResponse(429, {}), FakeResponse()])
    items = outfit("t1", "b1", "s1")
    assert tryon_render.render(tryon_render.render_key(person, items), person, items)["status"] == "done"
    assert len(fake_post.calls) == 2


def test_no_key_fails_without_calling(fake_post, person, monkeypatch):
    monkeypatch.setenv("POLLINATIONS_API_KEY", "")
    items = outfit("t1", "b1", "s1")
    status = tryon_render.render(tryon_render.render_key(person, items), person, items)
    assert status["status"] == "failed" and "no POLLINATIONS_API_KEY" in status["reason"]
    assert fake_post.calls == []


def test_stale_pending_counts_as_failed(person):
    key = tryon_render.render_key(person, outfit("t1", "b1", "s1"))
    tryon_render.mark_pending(key)
    assert tryon_render.read_status(key)["status"] == "pending"
    data = json.loads(tryon_render._status_path(key).read_text())
    data["updated"] = time.time() - tryon_render.STALE_AFTER_S - 5
    tryon_render._status_path(key).write_text(json.dumps(data))
    assert tryon_render.read_status(key)["status"] == "failed"


# ---- endpoints ----
def test_render_endpoint_pending_then_done_then_cached(fake_post):
    body = {"item_ids": ["t1", "b1", "s1"], "person": "stock"}
    first = client.post("/api/try-on/render", json=body).json()
    assert first["status"] == "pending"  # the background task runs after the reply
    done = client.get(f"/api/try-on/render/{first['key']}").json()
    assert done["status"] == "done" and done["url"] == f"/renders/{first['key']}.jpg"
    assert client.get(done["url"]).status_code == 200
    again = client.post("/api/try-on/render", json=body).json()
    assert again["status"] == "done" and len(fake_post.calls) == 1  # cache hit, no second call


def test_render_endpoint_modes(fake_post, monkeypatch):
    body = {"item_ids": ["t1", "b1", "s1"]}
    monkeypatch.setenv("TRYON_MODE", "off")
    assert client.post("/api/try-on/render", json=body).json() == {"status": "off"}
    monkeypatch.setenv("TRYON_MODE", "cache-only")
    reply = client.post("/api/try-on/render", json=body).json()
    assert reply["status"] == "failed" and "cache-only" in reply["reason"]
    assert fake_post.calls == []


def test_render_endpoint_validates():
    assert client.post("/api/try-on/render", json={"item_ids": ["nope"]}).status_code == 404
    assert client.post("/api/try-on/render", json={"item_ids": []}).status_code == 422
    assert client.get("/api/try-on/render/not-a-key").status_code == 404
    assert client.get("/api/try-on/render/" + "0" * 24).status_code == 404


# ---- "Dress me": random good matches ----
def test_pick_outfit_only_picks_matches_and_varies():
    items = list(SAMPLE.values())
    picks = [pick_outfit(items, Weather(temperature_c=18), rng=random.Random(seed)) for seed in range(30)]
    assert all(p.verdict == "MATCH" for p in picks)
    assert len({tuple(sorted(p.item_ids)) for p in picks}) > 5  # actually random


def test_pick_outfit_avoids_the_outfit_on_screen():
    items = list(SAMPLE.values())
    avoid = ["t1", "b1", "s1"]
    for seed in range(40):
        pick = pick_outfit(items, Weather(temperature_c=3), avoid=avoid, rng=random.Random(seed))
        assert not set(avoid) <= set(pick.item_ids)  # not the same look, not even plus a coat


def test_pick_outfit_falls_back_when_nothing_matches():
    clashing = [Item(id="a", name="a", image="", category="top", colors=["#c0392b"], formality=1, pattern="stripe"),
                Item(id="b", name="b", image="", category="bottom", colors=["#3e8e41"], formality=5, pattern="plaid"),
                Item(id="c", name="c", image="", category="shoes", colors=["#7b4fa0"], formality=1)]
    pick = pick_outfit(clashing, rng=random.Random(0))
    assert pick is not None and pick.verdict == "MISMATCH"
    assert pick_outfit([], rng=random.Random(0)) is None


def test_random_outfit_endpoint():
    first = client.get("/api/outfit/random", params={"temperature_c": 18}).json()
    assert first["verdict"] == "MATCH"
    avoid = ",".join(first["item_ids"])
    for _ in range(10):
        nxt = client.get("/api/outfit/random", params={"temperature_c": 18, "avoid": avoid}).json()
        assert set(nxt["item_ids"]) != set(first["item_ids"])


# ---- regressions from the review ----
def test_string_error_body_fails_cleanly_and_tries_next_model(fake_post, person):
    fake_post.queue.append(FakeResponse(400, {"error": "Invalid model"}))  # error is a string, not a dict
    items = outfit("t1", "b1", "s1")
    status = tryon_render.render(tryon_render.render_key(person, items), person, items)
    assert status["status"] == "done" and status["model"] == "model-b"


def test_crash_inside_render_records_failed_not_pending(fake_post, person, monkeypatch):
    items = outfit("t1", "b1", "s1")
    key = tryon_render.render_key(person, items)
    tryon_render.mark_pending(key, person)
    monkeypatch.setattr(tryon_render, "garment_uri", lambda path: (_ for _ in ()).throw(FileNotFoundError(path)))
    status = tryon_render.render(key, person, items)
    assert status["status"] == "failed" and "FileNotFoundError" in status["reason"]
    assert tryon_render.read_status(key)["status"] == "failed"


def test_bad_base64_is_a_failure_not_a_crash(fake_post, person):
    fake_post.queue.extend([FakeResponse(200, {"data": [{"b64_json": "abc"}]}),
                            FakeResponse(200, {"data": [{"b64_json": "abc"}]})])
    items = outfit("d1", "s2")
    status = tryon_render.render(tryon_render.render_key(person, items), person, items)
    assert status["status"] == "failed" and "unreadable" in status["reason"]


def test_superseded_render_is_skipped(fake_post, person):
    old, new = outfit("t1", "b1", "s1"), outfit("d1", "s2")
    old_key, new_key = tryon_render.render_key(person, old), tryon_render.render_key(person, new)
    tryon_render.mark_pending(old_key, person)
    tryon_render.mark_pending(new_key, person)  # the user moved on before old_key got the lock
    assert tryon_render.render(old_key, person, old, only_if_latest=True)["reason"] == "superseded by a newer look"
    assert fake_post.calls == []
    assert tryon_render.render(new_key, person, new, only_if_latest=True)["status"] == "done"
    assert tryon_render.read_status(old_key)["status"] == "failed"  # so asking again re-queues it


def test_half_written_status_reads_as_pending(person):
    key = tryon_render.render_key(person, outfit("t1", "b1", "s1"))
    tryon_render._status_path(key).write_text('{"status": "do', encoding="utf-8")
    assert tryon_render.read_status(key)["status"] == "pending"


def test_purge_removes_only_avatar_renders(fake_post, person, monkeypatch):
    monkeypatch.setattr(tryon_render, "AVATAR_PATH", person)  # pretend this person is the uploaded avatar
    items = outfit("t1", "b1", "s1")
    avatar_key = tryon_render.render_key(person, items)
    tryon_render.mark_pending(avatar_key, person)
    tryon_render.render(avatar_key, person, items)
    stock_key = "f" * 24
    tryon_render._write_status(stock_key, status="done", person="stock")
    assert tryon_render.purge_person("avatar") == 1
    assert tryon_render.read_status(avatar_key) is None and not tryon_render.image_path(avatar_key).exists()
    assert tryon_render._status_path(stock_key).exists()


def test_deleting_avatar_purges_its_renders(fake_post, person, monkeypatch):
    monkeypatch.setattr(tryon_render, "AVATAR_PATH", person)
    items = outfit("t1", "b1", "s1")
    key = tryon_render.render_key(person, items)
    tryon_render.mark_pending(key, person)
    tryon_render.render(key, person, items)
    monkeypatch.setattr(main, "AVATAR_PATH", person.with_name("gone.png"))
    client.delete("/api/avatar")
    assert not tryon_render.image_path(key).exists()


def test_pick_outfit_ignores_coats_when_avoiding():
    items = list(SAMPLE.values())
    on_screen = ["o1", "t6", "b4", "s3"]  # try-on sends the coat too
    for seed in range(40):
        pick = pick_outfit(items, Weather(temperature_c=3), avoid=on_screen, rng=random.Random(seed))
        visible = {i for i in pick.item_ids if SAMPLE[i].category.value != "outerwear"} if all(i in SAMPLE for i in pick.item_ids) else set()
        assert visible != {"t6", "b4", "s3"}  # not the same look with only the coat swapped
