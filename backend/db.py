"""
PERSON 4 — Database layer (SQLite).

Tables
  items     one row per clothing item (stored as JSON in the shared Item format)
  feedback  thumbs up/down on outfits  -> Person 2 trains on this
  worn      what was worn on which day -> used to avoid repeats
  tag_meta  where an item's tags came from (pollinations/gemini/clip/placeholder/manual),
            how confident the tagger was, and whether a human should check them

Set WARDROBE_DB to use a different database file (the tests do).

TODO (Person 4):
  - [ ] Move to Postgres if the team needs multiple users
  - [ ] Add a users table and a user_id column on every table
"""
import functools
import json
import os
import sqlite3
import threading
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from shared.schema import Feedback, Item

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("WARDROBE_DB") or ROOT / "data" / "wardrobe.db")
SAMPLE_PATH = ROOT / "data" / "sample_items.json"

# FastAPI runs sync endpoints in a threadpool, so every request shares one
# connection. SQLite connections are not thread-safe: without this lock a read
# racing a write raises InterfaceError / "cannot commit - no transaction is
# active" and the request 500s. RLock, because init() -> save_item() nests.
_LOCK = threading.RLock()


def _locked(fn):
    """Serialize access to the shared connection."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)

    return wrapper


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@_locked
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
        CREATE TABLE IF NOT EXISTS tag_meta (
            item_id        TEXT PRIMARY KEY,
            source         TEXT NOT NULL,
            confidence     REAL,
            needs_review   INTEGER NOT NULL DEFAULT 0,
            suggested_name TEXT,
            updated        TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    if seed and conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
        for raw in json.loads(SAMPLE_PATH.read_text()):
            save_item(conn, Item(**raw))
    conn.commit()


# ---- items ----
@_locked
def save_item(conn, item: Item) -> None:
    conn.execute("INSERT OR REPLACE INTO items (id, data) VALUES (?, ?)", (item.id, item.model_dump_json()))
    conn.commit()


@_locked
def list_items(conn) -> List[Item]:
    return [Item.model_validate_json(r["data"]) for r in conn.execute("SELECT data FROM items ORDER BY id")]


@_locked
def get_items(conn, ids: List[str]) -> List[Item]:
    by_id = {i.id: i for i in list_items(conn)}
    return [by_id[i] for i in ids if i in by_id]


@_locked
def delete_item(conn, item_id: str) -> None:
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.execute("DELETE FROM tag_meta WHERE item_id = ?", (item_id,))
    conn.commit()


# ---- tag metadata ----
@_locked
def save_tag_meta(conn, item_id: str, source: str, confidence: Optional[float] = None,
                  needs_review: bool = False, suggested_name: Optional[str] = None) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO tag_meta (item_id, source, confidence, needs_review, suggested_name, updated)
           VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (item_id, source, confidence, int(needs_review), suggested_name))
    conn.commit()


def _meta_row(r) -> Dict:
    return {"source": r["source"], "confidence": r["confidence"], "needs_review": bool(r["needs_review"]),
            "suggested_name": r["suggested_name"], "updated": r["updated"]}


@_locked
def get_tag_meta(conn, item_id: str) -> Optional[Dict]:
    r = conn.execute("SELECT * FROM tag_meta WHERE item_id = ?", (item_id,)).fetchone()
    return _meta_row(r) if r else None


@_locked
def list_tag_meta(conn) -> Dict[str, Dict]:
    """item_id -> meta, for every item that has any."""
    return {r["item_id"]: _meta_row(r) for r in conn.execute("SELECT * FROM tag_meta")}


@_locked
def mark_reviewed(conn, item_id: str) -> None:
    """A human has checked/edited this item's tags. Items with no meta yet get source 'manual'."""
    cur = conn.execute("UPDATE tag_meta SET needs_review = 0, updated = CURRENT_TIMESTAMP WHERE item_id = ?",
                       (item_id,))
    if cur.rowcount == 0:
        save_tag_meta(conn, item_id, "manual", needs_review=False)
    conn.commit()


# ---- feedback ----
@_locked
def save_feedback(conn, fb: Feedback) -> None:
    conn.execute("INSERT INTO feedback (item_ids, liked) VALUES (?, ?)", (json.dumps(fb.item_ids), int(fb.liked)))
    conn.commit()


@_locked
def list_feedback(conn) -> List[Feedback]:
    return [Feedback(item_ids=json.loads(r["item_ids"]), liked=bool(r["liked"]))
            for r in conn.execute("SELECT item_ids, liked FROM feedback")]


# ---- wear history ----
@_locked
def save_worn(conn, item_ids: List[str], day: date | None = None) -> None:
    conn.execute("INSERT INTO worn (item_ids, day) VALUES (?, ?)",
                 (json.dumps(item_ids), (day or date.today()).isoformat()))
    conn.commit()


@_locked
def recently_worn(conn, days: int = 3) -> set[str]:
    rows = conn.execute("SELECT item_ids FROM worn WHERE day >= date('now', ?)", (f"-{days} days",))
    worn: set[str] = set()
    for r in rows:
        worn.update(json.loads(r["item_ids"]))
    return worn
