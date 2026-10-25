"""
Generate the default try-on person once: data/images/stock_model.png (committed to git,
so the whole team shares the same model and nobody pays to regenerate it).

    python scripts/make_stock_model.py [--force]

One Pollinations image call (~1 cent with openai/gpt-image-1-mini). She's fictional, so
there are no privacy or likeness issues with sending her to the image model.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from input_pipeline import tryon_render  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="replace an existing stock model")
    args = ap.parse_args()
    path = tryon_render.STOCK_MODEL_PATH
    if path.is_file() and not args.force:
        sys.exit(f"{path} already exists (use --force to regenerate; cached renders will no longer match)")
    ok, reason = tryon_render.generate_stock_model(path)
    if not ok:
        sys.exit(f"Failed: {reason}")
    print(f"Saved {path}")


if __name__ == "__main__":
    main()
