"""
PERSON 4 — The API that connects everyone's code.

Run from the project root:
    uvicorn backend.main:app --reload
Then open http://localhost:8000  (the frontend)
and   http://localhost:8000/docs (interactive API docs — try every endpoint here)

Endpoints
  GET    /api/items              all items
  POST   /api/items              add an item (JSON in the shared format)
  POST   /api/items/upload       upload a photo -> Person 1's pipeline -> new item
  DELETE /api/items/{id}         remove an item
  POST   /api/score              score an outfit (list of item ids)
  GET    /api/suggest            best outfits for today's weather
  GET    /api/weather            today's weather
  POST   /api/feedback           thumbs up/down (retrains the taste model)
  POST   /api/worn               record that an outfit was worn today

TODO (Person 4):
  - [ ] Error handling for bad photos / unknown ids
  - [ ] Users and login if needed
"""
import io
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from backend import db
from backend.weather import get_weather
from outfit_logic.feedback_model import TasteModel
from outfit_logic.scorer import rate, suggest
from shared.schema import Feedback, Item, Outfit, ScoredOutfit, Weather

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Wardrobe API")
conn = db.connect()
db.init(conn)
taste = TasteModel()


def retrain() -> None:
    fb = db.list_feedback(conn)
    outfits = [db.get_items(conn, f.item_ids) for f in fb]
    taste.train(outfits, [f.liked for f in fb])


retrain()


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
    from input_pipeline.pipeline import process_photo  # Person 1
    try:
        img = Image.open(io.BytesIO(await photo.read()))
    except Exception:
        raise HTTPException(400, "That file isn't an image")
    item, needs_review = process_photo(img, name=name)
    db.save_item(conn, item)
    return {"item": item, "needs_review": needs_review}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    for item in db.get_items(conn, [item_id]):
        (ROOT / "data" / item.image).unlink(missing_ok=True)
    db.delete_item(conn, item_id)
    return {"deleted": item_id}


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
