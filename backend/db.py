"""
PERSON 4 — Database layer (SQLite).

Tables
  items     one row per clothing item (stored as JSON in the shared Item format)
  feedback  thumbs up/down on outfits  -> Person 2 trains on this
  worn      what was worn on which day -> used to avoid repeats
  tag_meta  where each item's tags came from, and how sure the tagger was

main.py, scripts/load_kaggle_sample.py and tests/test_api.py call these
functions, so keep the names.

TODO (Person 4):
  - [ ] Move to Postgres if the team needs multiple users
  - [ ] Add a users table and a user_id column on every table
"""
import json
import os
import sqlite3
import threading
from datetime import date
from pathlib import Path
from typing import List

from shared.schema import Feedback, Item

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "wardrobe.db"
SAMPLE_PATH = ROOT / "data" / "sample_items.json"

# FastAPI runs sync endpoints in a threadpool, so several threads share this one
# connection. SQLite connections are not thread-safe: without the lock, a read
# racing a write raises InterfaceError / "cannot commit - no transaction is
# active" and the request 500s. RLock, because init() -> save_item() nests.
_LOCK = threading.RLock()

SCHEMA = """
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
CREATE TABLE IF NOT EXISTS tag_meta (
    item_id        TEXT PRIMARY KEY,
    source         TEXT NOT NULL,
    confidence     REAL NOT NULL DEFAULT 0,
    needs_review   INTEGER NOT NULL DEFAULT 1,
    suggested_name TEXT,
    updated        TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def _db_path() -> Path:
    """Resolved per call so tests can point WARDROBE_DB at a throwaway file."""
    return Path(os.environ.get("WARDROBE_DB") or DB_PATH)


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the database. Allow use from FastAPI's threads, and return rows
    you can index by column name."""
    target = Path(path) if path is not None else _db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection, seed: bool = True) -> None:
    """Create the items, feedback and worn tables if they don't exist.
    If seed is True and items is empty, load every item from SAMPLE_PATH."""
    with _LOCK:
        conn.executescript(SCHEMA)
        conn.commit()
        if seed and conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            for raw in json.loads(SAMPLE_PATH.read_text()):
                save_item(conn, Item(**raw))


# ---- items ----
def save_item(conn, item: Item) -> None:
    """Insert the item, or replace it if the id already exists."""
    with _LOCK:
        conn.execute(
            "INSERT OR REPLACE INTO items (id, data) VALUES (?, ?)",
            (item.id, item.model_dump_json()),
        )
        conn.commit()


def list_items(conn) -> List[Item]:
    """Every item, sorted by id."""
    with _LOCK:
        rows = conn.execute("SELECT data FROM items ORDER BY id").fetchall()
    return [Item.model_validate_json(r["data"]) for r in rows]


def get_items(conn, ids: List[str]) -> List[Item]:
    """The items for these ids, in the same order. Skip unknown ids."""
    by_id = {item.id: item for item in list_items(conn)}
    return [by_id[i] for i in ids if i in by_id]


def delete_item(conn, item_id: str) -> None:
    with _LOCK:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        conn.execute("DELETE FROM tag_meta WHERE item_id = ?", (item_id,))
        conn.commit()


# ---- tag metadata ----
def _row_to_meta(row: sqlite3.Row) -> dict:
    return {
        "source": row["source"],
        "confidence": row["confidence"],
        "needs_review": bool(row["needs_review"]),
        "suggested_name": row["suggested_name"],
        "updated": row["updated"],
    }


def save_tag_meta(conn, item_id: str, meta: dict) -> None:
    with _LOCK:
        conn.execute(
            """INSERT OR REPLACE INTO tag_meta
               (item_id, source, confidence, needs_review, suggested_name, updated)
               VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
            (
                item_id,
                meta["source"],
                float(meta.get("confidence") or 0.0),
                int(bool(meta.get("needs_review"))),
                meta.get("suggested_name"),
            ),
        )
        conn.commit()


def get_tag_meta(conn, item_id: str) -> dict | None:
    with _LOCK:
        row = conn.execute("SELECT * FROM tag_meta WHERE item_id = ?", (item_id,)).fetchone()
    return _row_to_meta(row) if row else None


def all_tag_meta(conn) -> dict[str, dict]:
    with _LOCK:
        rows = conn.execute("SELECT * FROM tag_meta").fetchall()
    return {r["item_id"]: _row_to_meta(r) for r in rows}


def clear_needs_review(conn, item_id: str) -> None:
    with _LOCK:
        conn.execute(
            "UPDATE tag_meta SET needs_review = 0, updated = CURRENT_TIMESTAMP WHERE item_id = ?",
            (item_id,),
        )
        conn.commit()


# ---- feedback ----
def save_feedback(conn, fb: Feedback) -> None:
    with _LOCK:
        conn.execute(
            "INSERT INTO feedback (item_ids, liked) VALUES (?, ?)",
            (json.dumps(fb.item_ids), int(fb.liked)),
        )
        conn.commit()


def list_feedback(conn) -> List[Feedback]:
    with _LOCK:
        rows = conn.execute("SELECT item_ids, liked FROM feedback").fetchall()
    return [Feedback(item_ids=json.loads(r["item_ids"]), liked=bool(r["liked"])) for r in rows]


# ---- wear history ----
def save_worn(conn, item_ids: List[str], day: date | None = None) -> None:
    """Record that these items were worn on `day` (default: today)."""
    with _LOCK:
        conn.execute(
            "INSERT INTO worn (item_ids, day) VALUES (?, ?)",
            (json.dumps(item_ids), (day or date.today()).isoformat()),
        )
        conn.commit()


def recently_worn(conn, days: int = 3) -> set[str]:
    """Every item id worn in the last `days` days, today included."""
    with _LOCK:
        rows = conn.execute(
            "SELECT item_ids FROM worn WHERE day >= date('now', ?)", (f"-{days - 1} days",)
        ).fetchall()
    worn: set[str] = set()
    for r in rows:
        worn.update(json.loads(r["item_ids"]))
    return worn
