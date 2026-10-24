"""
PERSON 4 — The API that connects everyone's code.

Run from the project root:
    uvicorn backend.main:app --reload
Then open http://localhost:8000  (the frontend)
and   http://localhost:8000/docs (interactive API docs — try every endpoint here)

The frontend (frontend/app.js) and tests/test_api.py call these exact URLs,
so keep the paths and reply shapes.

TODO (Person 4):
  - [ ] Users and login if needed
"""
import io
from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from backend import db
from backend.weather import get_weather, season_for
from outfit_logic.feedback_model import TasteModel
from outfit_logic.scorer import rate, suggest
from shared.schema import (
    Category,
    Feedback,
    Item,
    Outfit,
    Pattern,
    ScoredOutfit,
    Season,
    Weather,
)

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Wardrobe API")

conn = db.connect()
db.init(conn)
taste = TasteModel()


def retrain() -> None:
    """Train the taste model on all saved feedback: for each feedback, look up
    its items, then taste.train(outfits, liked_list)."""
    pairs = [(db.get_items(conn, fb.item_ids), fb.liked) for fb in db.list_feedback(conn)]
    # A feedback row can outlive a deleted item. An empty outfit breaks the
    # feature extractor, so drop those pairs rather than crashing.
    pairs = [(items, liked) for items, liked in pairs if items]
    taste.train([items for items, _ in pairs], [liked for _, liked in pairs])


try:
    retrain()
except Exception:
    # A bad feedback row must never stop the server from booting.
    taste.model = None


# ---- items ----
@app.get("/api/items", response_model=List[Item])
def list_items():
    """Every item."""
    return db.list_items(conn)


@app.post("/api/items", response_model=Item)
def add_item(item: Item):
    """Save the item and return it."""
    if not item.colors:
        # An empty color list makes the rules scorer index [0] and 500 on every
        # later /api/score and /api/suggest, so reject it at the door.
        raise HTTPException(422, "An item needs at least one color")
    db.save_item(conn, item)
    return item


@app.post("/api/items/upload")
def upload_item(photo: UploadFile = File(...), name: str = Form("New item")):
    """Open the photo with PIL (400 error if it isn't an image), pass it to
    input_pipeline.pipeline.process_photo_with_meta(img, name=name), save the
    item, return {"item": item, "needs_review": needs_review, "tag_meta": meta}.

    Plain `def`, not `async def`: PIL decode + KMeans are CPU-bound, so this
    belongs in the threadpool, not on the event loop.
    """
    from input_pipeline.pipeline import process_photo_with_meta  # Person 1

    try:
        img = Image.open(io.BytesIO(photo.file.read()))
        img.load()  # Image.open is lazy: force the decode so a truncated file fails here, not later
    except Exception:
        raise HTTPException(400, "That file isn't an image")

    try:
        item, needs_review, tag_meta = process_photo_with_meta(img, name=name)
    except Exception:
        raise HTTPException(400, "Couldn't process that photo")

    db.save_item(conn, item)
    db.save_tag_meta(conn, item.id, tag_meta)
    return {"item": item, "needs_review": needs_review, "tag_meta": tag_meta}


class ItemPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    category: Optional[Category] = None
    colors: Optional[List[str]] = Field(default=None, min_length=1)
    pattern: Optional[Pattern] = None
    formality: Optional[int] = Field(default=None, ge=1, le=5)
    seasons: Optional[List[Season]] = None
    warmth: Optional[int] = Field(default=None, ge=1, le=5)


@app.patch("/api/items/{item_id}", response_model=Item)
def patch_item(item_id: str, patch: ItemPatch):
    """Apply the given fields, save, and clear needs_review."""
    found = db.get_items(conn, [item_id])
    if not found:
        raise HTTPException(404, "Unknown item id")
    updated = found[0].model_copy(update=patch.model_dump(exclude_none=True))
    db.save_item(conn, updated)
    db.clear_needs_review(conn, item_id)
    return updated


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    """Delete the item's image file in data/ as well as the row.
    Return {"deleted": item_id}."""
    for item in db.get_items(conn, [item_id]):
        (ROOT / "data" / item.image).unlink(missing_ok=True)
    db.delete_item(conn, item_id)
    return {"deleted": item_id}


# ---- tag metadata ----
@app.get("/api/tag-meta")
def all_item_tag_meta():
    """Every tag_meta record, keyed by item id (one request for the whole grid)."""
    return db.all_tag_meta(conn)


@app.get("/api/items/{item_id}/tag-meta")
def item_tag_meta(item_id: str):
    meta = db.get_tag_meta(conn, item_id)
    if meta is None:
        raise HTTPException(404, "No tag metadata for that item")
    return meta


# ---- outfits ----
@app.post("/api/score", response_model=ScoredOutfit)
def score(outfit: Outfit):
    """Look up the items (404 if any id is unknown) and return rate(items, taste)."""
    if not outfit.item_ids:
        raise HTTPException(422, "An outfit needs at least one item")
    items = db.get_items(conn, outfit.item_ids)
    if len(items) != len(outfit.item_ids):
        raise HTTPException(404, "Unknown item id")
    return rate(items, taste)


@app.get("/api/weather", response_model=Weather)
def weather(lat: Optional[float] = None, lon: Optional[float] = None):
    """Today's weather, for lat/lon if given, otherwise the default location."""
    if lat is not None and lon is not None:
        return get_weather(lat, lon)
    return get_weather()


@app.get("/api/suggest", response_model=List[ScoredOutfit])
def suggest_outfits(top_n: int = 5, temperature_c: Optional[float] = None, avoid_recent: bool = True):
    """Best outfits for today's weather. temperature_c overrides the real temperature
    (handy for testing: /api/suggest?temperature_c=3). If avoid_recent, skip items in
    db.recently_worn. Return suggest(items, weather, taste, exclude, top_n)."""
    if temperature_c is not None:
        # The caller already told us the temperature — don't wait 5s on Open-Meteo.
        w = Weather(temperature_c=temperature_c, raining=False, season=season_for(date.today()))
    else:
        w = get_weather()
    exclude = db.recently_worn(conn) if avoid_recent else set()
    return suggest(db.list_items(conn), w, taste, exclude, top_n)


@app.post("/api/feedback")
def feedback(fb: Feedback):
    """Save the thumbs up/down and retrain.
    Return {"saved": True, "taste_model_trained": <is the model trained now?>}."""
    db.save_feedback(conn, fb)
    retrain()
    return {"saved": True, "taste_model_trained": taste.model is not None}


@app.post("/api/worn")
def worn(outfit: Outfit):
    """Record that this outfit was worn today. Return {"saved": True}."""
    db.save_worn(conn, outfit.item_ids)
    return {"saved": True}


# ---- static files: item images + Person 3's frontend ----
app.mount("/images", StaticFiles(directory=ROOT / "data" / "images"), name="images")
app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")


@app.get("/")
def index():
    """Return frontend/index.html."""
    return FileResponse(ROOT / "frontend" / "index.html")
