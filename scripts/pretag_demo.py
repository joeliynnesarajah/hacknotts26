"""
Tag a folder of demo photos straight into the database — no server needed.

    python scripts/pretag_demo.py data/demo_photos [--force]

Each photo becomes an item with id "demo-<file name>", so re-running skips photos
that are already in (use --force to re-tag them). Afterwards, open /api/items and
check every row: a "placeholder" source means no API key was found — fix keys.env
and re-run with --force.
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.env import load_env  # noqa: E402

load_env()

from backend import db  # noqa: E402
from input_pipeline.pipeline import process_photo_with_meta  # noqa: E402

PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}


def item_id_for(path: Path) -> str:
    return "demo-" + re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")


def pretty(path: Path) -> str:
    """navy_oxford-shirt.jpg -> 'Navy oxford shirt'"""
    return re.sub(r"[_\-]+", " ", path.stem).strip().capitalize()[:40] or "New item"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path, nargs="?", default=ROOT / "data" / "demo_photos")
    ap.add_argument("--force", action="store_true", help="re-tag photos that are already in the DB")
    args = ap.parse_args()

    photos = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in PHOTO_TYPES) \
        if args.folder.is_dir() else []
    if not photos:
        sys.exit(f"No photos found in {args.folder}")

    conn = db.connect()
    db.init(conn)
    existing = {it.id for it in db.list_items(conn)}
    tally, skipped = Counter(), 0

    print(f"{'name':40} | {'category':9} | {'source':12} | conf | review?")
    for path in photos:
        item_id = item_id_for(path)
        if item_id in existing and not args.force:
            skipped += 1
            continue
        try:
            item, needs_review, meta = process_photo_with_meta(Image.open(path), name=None, item_id=item_id)
        except Exception as exc:
            print(f"{path.name}: FAILED ({type(exc).__name__}: {exc})")
            tally["failed"] += 1
            continue
        if meta["source"] in ("clip", "placeholder"):  # no real name from the tagger
            item.name = pretty(path)
        db.save_item(conn, item)
        db.save_tag_meta(conn, item.id, **meta)
        tally[meta["source"]] += 1
        print(f"{item.name:40} | {item.category.value:9} | {meta['source']:12} | "
              f"{meta['confidence']:.2f} | {'REVIEW' if needs_review else ''}")

    parts = [f"{k} {v}" for k, v in tally.most_common()]
    if skipped:
        parts.append(f"skipped {skipped} already in the DB")
    print("\nTally: " + ", ".join(parts))
    if tally["placeholder"]:
        print("Placeholder rows mean no working API key - check keys.env, then re-run with --force.")


if __name__ == "__main__":
    main()
