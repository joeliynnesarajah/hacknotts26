"""
PERSON 4 — The API that connects everyone's code.

Run from the project root:
    uvicorn backend.main:app --reload
Then open http://localhost:8000  (the frontend)
and   http://localhost:8000/docs (interactive API docs — try every endpoint here)

The frontend (frontend/app.js) and tests/test_api.py call these exact URLs,
so keep the paths and reply shapes.

TODO (Person 4):
  - [ ] Setup: open the database, create the taste model, train it at startup
  - [ ] Fill in every endpoint below
  - [ ] Serve the item images and the frontend (bottom of the file)
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

# TODO: conn = database connection (db.connect, then db.init)
# TODO: taste = TasteModel(), then retrain() once at startup


def retrain() -> None:
    """Train the taste model on all saved feedback: for each feedback, look up
    its items, then taste.train(outfits, liked_list)."""
    pass


# ---- items ----
@app.get("/api/items", response_model=List[Item])
def list_items():
    """Every item."""
    pass


@app.post("/api/items", response_model=Item)
def add_item(item: Item):
    """Save the item and return it."""
    pass


@app.post("/api/items/upload")
async def upload_item(photo: UploadFile = File(...), name: str = Form("New item")):
    """Open the photo with PIL (400 error if it isn't an image), pass it to
    input_pipeline.pipeline.process_photo(img, name=name) -> (item, needs_review),
    save the item, return {"item": item, "needs_review": needs_review}."""
    pass


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    """Delete the item's image file in data/ as well as the row.
    Return {"deleted": item_id}."""
    pass


# ---- outfits ----
@app.post("/api/score", response_model=ScoredOutfit)
def score(outfit: Outfit):
    """Look up the items (404 if any id is unknown) and return rate(items, taste)."""
    pass


@app.get("/api/weather", response_model=Weather)
def weather(lat: Optional[float] = None, lon: Optional[float] = None):
    """Today's weather, for lat/lon if given, otherwise the default location."""
    pass


@app.get("/api/suggest", response_model=List[ScoredOutfit])
def suggest_outfits(top_n: int = 5, temperature_c: Optional[float] = None, avoid_recent: bool = True):
    """Best outfits for today's weather. temperature_c overrides the real temperature
    (handy for testing: /api/suggest?temperature_c=3). If avoid_recent, skip items in
    db.recently_worn. Return suggest(items, weather, taste, exclude, top_n)."""
    pass


@app.post("/api/feedback")
def feedback(fb: Feedback):
    """Save the thumbs up/down and retrain.
    Return {"saved": True, "taste_model_trained": <is the model trained now?>}."""
    pass


@app.post("/api/worn")
def worn(outfit: Outfit):
    """Record that this outfit was worn today. Return {"saved": True}."""
    pass


# ---- static files: item images + Person 3's frontend ----
# TODO: serve data/images at /images and frontend/ at /static (StaticFiles)


@app.get("/")
def index():
    """Return frontend/index.html."""
    pass
