"""
PERSON 4 — Database layer (SQLite).

Tables
  items     one row per clothing item (stored as JSON in the shared Item format)
  feedback  thumbs up/down on outfits  -> Person 2 trains on this
  worn      what was worn on which day -> used to avoid repeats

main.py, scripts/load_kaggle_sample.py and tests/test_api.py call these
functions, so keep the names.

TODO (Person 4):
  - [ ] Fill in every function below
  - [ ] Move to Postgres if the team needs multiple users
  - [ ] Add a users table and a user_id column on every table
"""
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import List

from shared.schema import Feedback, Item

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "wardrobe.db"
SAMPLE_PATH = ROOT / "data" / "sample_items.json"


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the database. Allow use from FastAPI's threads, and return rows
    you can index by column name."""
    pass


def init(conn: sqlite3.Connection, seed: bool = True) -> None:
    """Create the items, feedback and worn tables if they don't exist.
    If seed is True and items is empty, load every item from SAMPLE_PATH."""
    pass


# ---- items ----
def save_item(conn, item: Item) -> None:
    """Insert the item, or replace it if the id already exists."""
    pass


def list_items(conn) -> List[Item]:
    """Every item, sorted by id."""
    pass


def get_items(conn, ids: List[str]) -> List[Item]:
    """The items for these ids, in the same order. Skip unknown ids."""
    pass


def delete_item(conn, item_id: str) -> None:
    pass


# ---- feedback ----
def save_feedback(conn, fb: Feedback) -> None:
    pass


def list_feedback(conn) -> List[Feedback]:
    pass


# ---- wear history ----
def save_worn(conn, item_ids: List[str], day: date | None = None) -> None:
    """Record that these items were worn on `day` (default: today)."""
    pass


def recently_worn(conn, days: int = 3) -> set[str]:
    """Every item id worn in the last `days` days."""
    pass
