"""
How accurate is the tagger? Compares tag_item() against the Kaggle dataset's real labels.

    python scripts/check_tagger.py path/to/fashion-product-images-small --count 30

Prints category accuracy (exact), formality (within ±1), season overlap, which
provider answered, and the 5 worst misses. The dataset has no pattern labels,
so check pattern by eye. Uses one API call per image — keep --count small.
"""
import argparse
import csv
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from shared.env import load_env  # noqa: E402

load_env()

from input_pipeline.background import crop_to_content, remove_background  # noqa: E402
from input_pipeline.tagger import tag_item  # noqa: E402
from scripts.load_kaggle_sample import ARTICLE_TO_CATEGORY, SEASON_MAP, USAGE_TO_FORMALITY  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", type=Path, help="Folder with styles.csv and images/")
    ap.add_argument("--count", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    by_cat = defaultdict(list)
    with open(args.dataset / "styles.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cat = ARTICLE_TO_CATEGORY.get(row.get("articleType", ""))
            if cat and (args.dataset / "images" / f"{row['id']}.jpg").exists():
                by_cat[cat].append(row)

    # Balanced across categories so one easy class can't hide a bad one
    random.seed(args.seed)
    per_cat = max(1, args.count // len(by_cat))
    rows = [r for rs in by_cat.values() for r in random.sample(rs, min(len(rs), per_cat))]

    cat_ok = form_ok = form_n = season_ok = season_n = 0
    sources, misses = Counter(), []
    for i, row in enumerate(rows, 1):
        img = crop_to_content(remove_background(Image.open(args.dataset / "images" / f"{row['id']}.jpg")))
        tags = tag_item(img)
        sources[tags["source"]] += 1
        want_cat = ARTICLE_TO_CATEGORY[row["articleType"]]
        cat_ok += tags["category"] == want_cat
        if row.get("usage") in USAGE_TO_FORMALITY:
            form_n += 1
            form_ok += abs(tags["formality"] - USAGE_TO_FORMALITY[row["usage"]]) <= 1
        if row.get("season") in SEASON_MAP:
            season_n += 1
            season_ok += SEASON_MAP[row["season"]].value in tags["seasons"]
        if tags["category"] != want_cat:
            misses.append((tags["confidence"], row["productDisplayName"][:40], want_cat, tags["category"]))
        print(f"\r{i}/{len(rows)} tagged", end="", flush=True)

    pct = lambda a, b: f"{a}/{b} = {a / b:.0%}" if b else "n/a"  # noqa: E731
    print("\n")
    print(f"Category (exact)      {pct(cat_ok, len(rows))}   target >= 80%")
    print(f"Formality (within ±1) {pct(form_ok, form_n)}")
    print(f"Season (overlap)      {pct(season_ok, season_n)}")
    print(f"Answered by           {dict(sources)}")
    if misses:
        print("\nWorst category misses (most confident first):")
        for conf, name, want, got in sorted(misses, reverse=True)[:5]:
            print(f"  {name:40} expected {want:9} got {got:9} (confidence {conf:.2f})")


if __name__ == "__main__":
    main()
