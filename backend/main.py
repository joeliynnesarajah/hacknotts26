"""
PERSON 4 — The API that connects everyone's code.

Run from the project root:
    uvicorn backend.main:app --reload
Then open http://localhost:8000  (the frontend)
and   http://localhost:8000/docs (interactive API docs — try every endpoint here)

Endpoints
  GET    /api/items                   all items
  POST   /api/items                   add an item (JSON in the shared format)
  POST   /api/items/upload            upload a photo -> Person 1's pipeline -> new item + tag_meta
  PATCH  /api/items/{id}              correct an item's tags (marks it reviewed)
  DELETE /api/items/{id}              remove an item
  GET    /api/items/{id}/tag-meta     where one item's tags came from
  GET    /api/tag-meta                item_id -> tag meta, for every item that has some
  POST   /api/score                   score an outfit (list of item ids)
  GET    /api/suggest                 best outfits for today's weather
  GET    /api/weather                 today's weather
  POST   /api/feedback                thumbs up/down (retrains the taste model)
  GET    /api/avatar                  current try-on avatar, if uploaded
  POST   /api/avatar                  upload a photo for try-on
  DELETE /api/avatar                  reset the try-on avatar
  GET    /api/outfit/random           "Dress me": a random good match, different from ?avoid=ids
  POST   /api/try-on/render           photoreal try-on of an outfit (cached; may be pending)
  GET    /api/try-on/render/{key}     poll a pending render

TODO (Person 4):
  - [ ] Users and login if needed
"""
import io
import logging
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from shared.env import load_env

load_env()  # API keys from keys.env, before the tagger reads them

from backend import db  # noqa: E402
from backend.weather import get_weather  # noqa: E402
from input_pipeline.background import fit_to_frame, remove_background  # noqa: E402
from outfit_logic.feedback_model import TasteModel  # noqa: E402
from input_pipeline import tryon_render  # noqa: E402
from outfit_logic.scorer import pick_outfit, rate, suggest  # noqa: E402
from shared.schema import Category, Feedback, Item, Outfit, Pattern, ScoredOutfit, Season, Weather  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

ROOT = Path(__file__).resolve().parent.parent
TASTE_PATH = db.DB_PATH.with_name("taste_model.joblib")  # lives next to the database
AVATAR_PATH = ROOT / "data" / "images" / "avatar.png"

app = FastAPI(title="Wardrobe API")
conn = db.connect()
db.init(conn)


def _warm_up_rembg() -> None:
    """Load rembg's model in the background at startup, so the first upload isn't slow."""
    try:
        from input_pipeline.background import _rembg_session
        _rembg_session()
    except ImportError:
        pass  # rembg not installed: the light-background fallback needs no warm-up


threading.Thread(target=_warm_up_rembg, daemon=True).start()


def retrain() -> None:
    fb = db.list_feedback(conn)
    outfits = [db.get_items(conn, f.item_ids) for f in fb]
    taste.train(outfits, [f.liked for f in fb])
    taste.save(TASTE_PATH)


# Load the saved taste model if there is one; otherwise train from the feedback table
taste = TasteModel.load(TASTE_PATH)
if taste.model is None:
    retrain()


class ItemPatch(BaseModel):
    """Every field optional: send only what you want to change."""
    name: Optional[str] = None
    category: Optional[Category] = None
    colors: Optional[List[str]] = None
    pattern: Optional[Pattern] = None
    formality: Optional[int] = Field(default=None, ge=1, le=5)
    seasons: Optional[List[Season]] = None
    warmth: Optional[int] = Field(default=None, ge=1, le=5)


def get_item_or_404(item_id: str) -> Item:
    found = db.get_items(conn, [item_id])
    if not found:
        raise HTTPException(404, "Unknown item id")
    return found[0]


# ---- items ----
@app.get("/api/items", response_model=List[Item])
def list_items():
    return db.list_items(conn)


@app.post("/api/items", response_model=Item)
def add_item(item: Item):
    db.save_item(conn, item)
    return item


@app.post("/api/items/upload")
async def upload_item(photo: UploadFile = File(...), name: str = Form("New item")):
    from input_pipeline.pipeline import process_photo_with_meta  # Person 1
    try:
        img = Image.open(io.BytesIO(await photo.read()))
        img.load()
    except Exception:
        raise HTTPException(400, "That file isn't an image")
    # The pipeline is slow (background removal + a network call), so keep it off the event loop.
    # Tagger failures never raise — they fall back to placeholder tags with needs_review=True.
    try:
        item, needs_review, meta = await run_in_threadpool(process_photo_with_meta, img, name)
    except Exception as exc:
        logging.getLogger(__name__).exception("pipeline failed")
        raise HTTPException(400, f"Couldn't process that photo ({type(exc).__name__})")
    db.save_item(conn, item)
    db.save_tag_meta(conn, item.id, **meta)
    return {"item": item, "needs_review": needs_review, "tag_meta": db.get_tag_meta(conn, item.id)}


@app.patch("/api/items/{item_id}", response_model=Item)
def update_item(item_id: str, patch: ItemPatch):
    item = get_item_or_404(item_id)
    updated = Item(**{**item.model_dump(), **patch.model_dump(exclude_unset=True, exclude_none=True)})
    db.save_item(conn, updated)
    db.mark_reviewed(conn, item_id)
    return updated


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    for item in db.get_items(conn, [item_id]):
        (ROOT / "data" / item.image).unlink(missing_ok=True)
    db.delete_item(conn, item_id)
    return {"deleted": item_id}


@app.get("/api/items/{item_id}/tag-meta")
def item_tag_meta(item_id: str):
    get_item_or_404(item_id)
    meta = db.get_tag_meta(conn, item_id)
    if meta is None:
        raise HTTPException(404, "No tag metadata for this item")
    return meta


@app.get("/api/tag-meta")
def all_tag_meta() -> Dict[str, Dict]:
    return db.list_tag_meta(conn)


# ---- outfits ----
@app.post("/api/score", response_model=ScoredOutfit)
def score(outfit: Outfit):
    items = db.get_items(conn, outfit.item_ids)
    if len(items) != len(outfit.item_ids):
        raise HTTPException(404, "Unknown item id")
    return rate(items, taste)


@app.get("/api/weather", response_model=Weather)
def weather(lat: Optional[float] = None, lon: Optional[float] = None):
    return get_weather(lat, lon) if lat is not None and lon is not None else get_weather()


@app.get("/api/suggest", response_model=List[ScoredOutfit])
def suggest_outfits(top_n: int = 5, temperature_c: Optional[float] = None):
    w = get_weather()
    if temperature_c is not None:  # handy for testing: /api/suggest?temperature_c=3
        w.temperature_c = temperature_c
    return suggest(db.list_items(conn), w, taste, exclude_ids=set(), top_n=top_n)


@app.get("/api/outfit/random", response_model=ScoredOutfit)
def random_outfit(avoid: str = "", temperature_c: Optional[float] = None, mode: str = "any"):
    """"Dress me": a random good match for today's weather, different from `avoid`
    (comma-separated ids of the outfit on screen). `mode` is the page's mode: "separates",
    "dress", or "any" (dress vs separates chosen 50/50). If the weather rules leave nothing
    (e.g. cold but no coats), it ignores the weather rather than giving up."""
    if mode not in ("separates", "dress", "any"):
        raise HTTPException(422, "mode must be separates, dress or any")
    w = get_weather()
    if temperature_c is not None:
        w.temperature_c = temperature_c
    items = db.list_items(conn)
    avoid_ids = [i for i in avoid.split(",") if i]
    kind = None if mode == "any" else mode
    pick = (pick_outfit(items, w, taste, avoid=avoid_ids, kind=kind)
            or pick_outfit(items, None, taste, avoid=avoid_ids, kind=kind))
    if pick is None:
        raise HTTPException(404, "No dresses to choose from yet" if mode == "dress" else "Not enough clothes to make an outfit")
    return pick


# ---- photoreal try-on (see input_pipeline/tryon_render.py) ----
class RenderRequest(BaseModel):
    item_ids: List[str] = Field(min_length=1)
    person: str = "avatar"  # "avatar" = uploaded photo if there is one, else the stock model; "stock"


def _render_reply(status: Dict) -> Dict:
    reply = {k: status[k] for k in ("key", "status", "reason", "model") if k in status}
    if status.get("status") == "done":
        reply["url"] = f"/renders/{status['key']}.jpg"
    return reply


@app.post("/api/try-on/render")
def start_render(req: RenderRequest, background: BackgroundTasks):
    """Cached look -> done straight away. Otherwise pending: poll GET /api/try-on/render/{key}."""
    if tryon_render.mode() == "off":
        return {"status": "off"}
    items = db.get_items(conn, req.item_ids)
    if len(items) != len(set(req.item_ids)):
        raise HTTPException(404, "Unknown item id")
    person = tryon_render.person_path(req.person)
    if person is None:
        return {"status": "failed", "reason": "no stock model yet (run scripts/make_stock_model.py)"}
    key = tryon_render.render_key(person, items)
    status = tryon_render.read_status(key)
    if status and status["status"] in ("done", "pending"):
        return _render_reply(status)
    if tryon_render.mode() == "cache-only":
        return {"key": key, "status": "failed", "reason": "cache-only mode: this look wasn't pre-rendered"}
    tryon_render.mark_pending(key, person)
    background.add_task(tryon_render.render, key, person, items, only_if_latest=True)
    return {"key": key, "status": "pending"}


@app.get("/api/try-on/render/{key}")
def render_status(key: str):
    if not re.fullmatch(r"[0-9a-f]{24}", key):
        raise HTTPException(404, "Unknown render")
    status = tryon_render.read_status(key)
    if status is None:
        raise HTTPException(404, "Unknown render")
    return _render_reply(status)


@app.post("/api/feedback")
def feedback(fb: Feedback):
    db.save_feedback(conn, fb)
    retrain()
    return {"saved": True, "taste_model_trained": taste.model is not None}


@app.post("/api/avatar")
async def upload_avatar(file: UploadFile = File(...)):
    try:
        image = Image.open(io.BytesIO(await file.read()))
        image.load()
    except Exception:
        raise HTTPException(400, "That file isn't an image")

    try:
        cutout = await run_in_threadpool(remove_background, image)
        # Same 180:420 frame and body placement as the Cher silhouette (head at the top, feet at
        # the bottom), so the try-on page's garment boxes land on the right body parts.
        cutout = cutout.convert("RGBA")
        framed = fit_to_frame(cutout)
        AVATAR_PATH.parent.mkdir(parents=True, exist_ok=True)
        framed.save(AVATAR_PATH, format="PNG")
        tryon_render.purge_person("avatar")  # renders of the previous photo no longer apply
    except Exception as exc:
        logging.getLogger(__name__).exception("avatar processing failed")
        raise HTTPException(400, f"Couldn't process that photo ({type(exc).__name__})")

    # A standing person is about 2.5-4x taller than wide. Anything much squatter is probably a
    # close-up or half-body shot, which the paper doll can't dress (the head ends up where the legs go).
    reply = {"url": "/images/avatar.png"}
    bbox = cutout.getbbox()
    if bbox and (bbox[3] - bbox[1]) < 1.7 * (bbox[2] - bbox[0]):
        reply["warning"] = "This looks like a close-up. For try-on, use a full-body photo, head to feet."
    return reply


@app.get("/api/avatar")
def get_avatar():
    return {"url": "/images/avatar.png"} if AVATAR_PATH.exists() else {"url": None}


@app.delete("/api/avatar")
def delete_avatar():
    AVATAR_PATH.unlink(missing_ok=True)
    tryon_render.purge_person("avatar")  # don't keep renders of someone's photo after they remove it
    return {"url": None}


# ---- static files: item images + Person 3's frontend ----
app.mount("/images", StaticFiles(directory=ROOT / "data" / "images"), name="images")
tryon_render.RENDER_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/renders", StaticFiles(directory=tryon_render.RENDER_DIR), name="renders")
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")


@app.get("/try-on.html")
def try_on_page():
    return FileResponse(ROOT / "frontend" / "try-on.html")


@app.get("/")
def index():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/try-on")
def try_on():
    return FileResponse(ROOT / "frontend" / "try-on.html")
