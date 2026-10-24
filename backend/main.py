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
  POST   /api/worn                    record that an outfit was worn today

TODO (Person 4):
  - [ ] Users and login if needed
"""
import io
import logging
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from shared.env import load_env

load_env()  # API keys from keys.env, before the tagger reads them

from backend import db  # noqa: E402
from backend.weather import get_weather  # noqa: E402
from outfit_logic.feedback_model import TasteModel  # noqa: E402
from outfit_logic.scorer import rate, suggest  # noqa: E402
from shared.schema import Category, Feedback, Item, Outfit, Pattern, ScoredOutfit, Season, Weather  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

ROOT = Path(__file__).resolve().parent.parent
TASTE_PATH = db.DB_PATH.with_name("taste_model.joblib")  # lives next to the database

app = FastAPI(title="Wardrobe API")
conn = db.connect()
db.init(conn)


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
def suggest_outfits(top_n: int = 5, temperature_c: Optional[float] = None, avoid_recent: bool = True):
    w = get_weather()
    if temperature_c is not None:  # handy for testing: /api/suggest?temperature_c=3
        w.temperature_c = temperature_c
    exclude = db.recently_worn(conn) if avoid_recent else set()
    return suggest(db.list_items(conn), w, taste, exclude, top_n)


@app.post("/api/feedback")
def feedback(fb: Feedback):
    db.save_feedback(conn, fb)
    retrain()
    return {"saved": True, "taste_model_trained": taste.model is not None}


@app.post("/api/worn")
def worn(outfit: Outfit):
    db.save_worn(conn, outfit.item_ids)
    return {"saved": True}


# ---- static files: item images + Person 3's frontend ----
app.mount("/images", StaticFiles(directory=ROOT / "data" / "images"), name="images")
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "frontend" / "index.html")
