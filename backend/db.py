"""
PERSON 4 — Database layer (SQLite).

Tables
  items     one row per clothing item (stored as JSON in the shared Item format)
  feedback  thumbs up/down on outfits  -> Person 2 trains on this
  worn      what was worn on which day -> used to avoid repeats

TODO (Person 4):
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
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection, seed: bool = True) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS items (
            id   TEXT PRIMARY KEY,
            data TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS feedback (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            item_ids TEXT NOT NULL,
            liked    INTEGER NOT NULL,
            created  TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS worn (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            item_ids TEXT NOT NULL,
            day      TEXT NOT NULL
        );
        """
    )
    if seed and conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
        for raw in json.loads(SAMPLE_PATH.read_text()):
            save_item(conn, Item(**raw))
    conn.commit()


# ---- items ----
def save_item(conn, item: Item) -> None:
    conn.execute("INSERT OR REPLACE INTO items (id, data) VALUES (?, ?)", (item.id, item.model_dump_json()))
    conn.commit()


def list_items(conn) -> List[Item]:
    return [Item.model_validate_json(r["data"]) for r in conn.execute("SELECT data FROM items ORDER BY id")]


def get_items(conn, ids: List[str]) -> List[Item]:
    by_id = {i.id: i for i in list_items(conn)}
    return [by_id[i] for i in ids if i in by_id]


def delete_item(conn, item_id: str) -> None:
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()


# ---- feedback ----
def save_feedback(conn, fb: Feedback) -> None:
    conn.execute("INSERT INTO feedback (item_ids, liked) VALUES (?, ?)", (json.dumps(fb.item_ids), int(fb.liked)))
    conn.commit()


def list_feedback(conn) -> List[Feedback]:
    return [Feedback(item_ids=json.loads(r["item_ids"]), liked=bool(r["liked"]))
            for r in conn.execute("SELECT item_ids, liked FROM feedback")]


# ---- wear history ----
def save_worn(conn, item_ids: List[str], day: date | None = None) -> None:
    conn.execute("INSERT INTO worn (item_ids, day) VALUES (?, ?)",
                 (json.dumps(item_ids), (day or date.today()).isoformat()))
    conn.commit()


def recently_worn(conn, days: int = 3) -> set[str]:
    rows = conn.execute("SELECT item_ids FROM worn WHERE day >= date('now', ?)", (f"-{days} days",))
    worn: set[str] = set()
    for r in rows:
        worn.update(json.loads(r["item_ids"]))
    return worn
