"""
Pre-render the demo's hero outfits, so they appear instantly on stage (no network needed).

    python scripts/prerender.py [--person stock|avatar]

Renders go to data/renders/ (the same cache the app uses). That folder is gitignored (it also
holds renders of people's own photos); commit the hero renders with `git add -f data/renders/<key>.*`
so any teammate's laptop gets them too. They only match while the stock model and the sample item
images are unchanged. About 1 cent and ~25s per outfit; already-rendered outfits are skipped.

The heroes are sample items (in git, so present on every machine) that the rules score as a
full-marks MATCH, picked to cover different looks.
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db  # noqa: E402
from input_pipeline import tryon_render  # noqa: E402
from outfit_logic.rules import score_outfit  # noqa: E402

HERO_OUTFITS = [
    ("o1", "t6", "b4", "s3"),  # camel coat, black turtleneck, plaid skirt, black loafers (very Cher)
    ("t3", "b1", "s1"),        # red striped top, blue jeans, white trainers
    ("d1", "s2"),              # green midi dress, brown leather boots
    ("t5", "b2", "s3"),        # yellow floral blouse, black trousers, black loafers
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", choices=["stock", "avatar"], default="stock")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="  %(message)s")

    if tryon_render.mode() != "live":
        sys.exit(f"TRYON_MODE is {tryon_render.mode()!r}; pre-rendering needs live mode")
    person = tryon_render.person_path(args.person)
    if person is None:
        sys.exit("No stock model yet: run python scripts/make_stock_model.py first")

    conn = db.connect()
    db.init(conn)
    failed = 0
    for ids in HERO_OUTFITS:
        items = db.get_items(conn, list(ids))
        if len(items) != len(ids):
            print(f"{ids}: SKIPPED, missing items in the database")
            failed += 1
            continue
        verdict = score_outfit(items)
        names = " + ".join(it.name for it in items)
        key = tryon_render.render_key(person, items)
        status = tryon_render.read_status(key)
        if status and status["status"] == "done":
            print(f"{names}: already rendered ({key})")
            continue
        print(f"{names}: rendering (rules: {verdict.verdict} {verdict.score:.2f})...")
        tryon_render.mark_pending(key)
        result = tryon_render.render(key, person, items)
        if result["status"] == "done":
            print(f"  done with {result.get('model')} in {result.get('seconds')}s -> {tryon_render.image_path(key)}")
        else:
            failed += 1
            print(f"  FAILED: {result.get('reason')}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
