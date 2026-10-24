"""
Load ~50 real product photos from the Kaggle "Fashion Product Images (Small)" dataset
into the app, using its labels instead of auto-tagging.

1. Download the dataset from Kaggle (search "Fashion Product Images Small") and unzip it.
   You need the folder containing styles.csv and images/.
2. Run from the project root:
       python scripts/load_kaggle_sample.py path/to/dataset --count 50
3. Restart the server — the items appear in the carousels.

Bonus for Person 1: run with --check-tagger to compare CLIP's tags against
the dataset's real labels and print an accuracy score.
"""
import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db  # noqa: E402
from input_pipeline.background import crop_to_content, remove_background  # noqa: E402
from shared.schema import Item, Season  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT / "data" / "images"

ARTICLE_TO_CATEGORY = {
    "Tshirts": "top", "Shirts": "top", "Tops": "top", "Sweaters": "top", "Sweatshirts": "top", "Kurtas": "top",
    "Jeans": "bottom", "Trousers": "bottom", "Shorts": "bottom", "Skirts": "bottom", "Track Pants": "bottom",
    "Dresses": "dress",
    "Casual Shoes": "shoes", "Formal Shoes": "shoes", "Sports Shoes": "shoes", "Sandals": "shoes",
    "Heels": "shoes", "Flats": "shoes", "Flip Flops": "shoes",
    "Jackets": "outerwear", "Blazers": "outerwear",
}
USAGE_TO_FORMALITY = {"Sports": 1, "Casual": 2, "Travel": 2, "Smart Casual": 3, "Ethnic": 3, "Formal": 4, "Party": 4}
SEASON_MAP = {"Spring": Season.spring, "Summer": Season.summer, "Fall": Season.autumn, "Winter": Season.winter}
COLOUR_HEX = {
    "Black": "#1b1b1b", "White": "#f4f4f2", "Grey": "#8a8d91", "Blue": "#3b6fb6", "Navy Blue": "#1f3a5f",
    "Red": "#c0392b", "Green": "#3e8e41", "Olive": "#6b6b2e", "Brown": "#6b4226", "Beige": "#d6c4a3",
    "Pink": "#e88aa8", "Purple": "#7b4fa0", "Yellow": "#f2c94c", "Orange": "#e67e22", "Maroon": "#7a1f2b",
    "Cream": "#f3e9d2", "Khaki": "#c3b091", "Tan": "#c8a27a", "Charcoal": "#36454f", "Teal": "#2a8c8c",
    "Silver": "#c0c0c0", "Gold": "#c9a227", "Off White": "#f1ede4", "Lavender": "#b4a7d6", "Peach": "#f5b895",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path, help="Folder with styles.csv and images/")
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--check-tagger", action="store_true", help="Compare CLIP tags to the real labels")
    args = ap.parse_args()

    by_cat = defaultdict(list)
    with open(args.dataset / "styles.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat = ARTICLE_TO_CATEGORY.get(row.get("articleType", ""))
            if cat and row.get("baseColour") in COLOUR_HEX and (args.dataset / "images" / f"{row['id']}.jpg").exists():
                by_cat[cat].append(row)

    # Balanced sample: tops, bottoms and shoes matter most for outfits
    share = {"top": 0.3, "bottom": 0.25, "shoes": 0.25, "dress": 0.1, "outerwear": 0.1}
    random.seed(args.seed)
    chosen = []
    for cat, frac in share.items():
        chosen += random.sample(by_cat[cat], min(len(by_cat[cat]), round(args.count * frac)))

    conn = db.connect()
    db.init(conn, seed=False)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    correct = total = 0

    for row in chosen:
        img = Image.open(args.dataset / "images" / f"{row['id']}.jpg")
        cutout = crop_to_content(remove_background(img))
        item_id = f"k{row['id']}"
        cutout.save(IMAGES_DIR / f"{item_id}.png")
        cat = ARTICLE_TO_CATEGORY[row["articleType"]]
        season = SEASON_MAP.get(row.get("season", ""))
        item = Item(
            id=item_id,
            name=row["productDisplayName"][:40],
            image=f"images/{item_id}.png",
            category=cat,
            colors=[COLOUR_HEX[row["baseColour"]]],
            formality=USAGE_TO_FORMALITY.get(row.get("usage", ""), 2),
            seasons=[season] if season else list(Season),
        )
        db.save_item(conn, item)

        if args.check_tagger:
            from input_pipeline.tagger import tag_item
            total += 1
            correct += tag_item(cutout)["category"] == cat

    print(f"Loaded {len(chosen)} items into {db.DB_PATH}")
    if args.check_tagger and total:
        print(f"Tagger category accuracy: {correct}/{total} = {correct / total:.0%}")


if __name__ == "__main__":
    main()
