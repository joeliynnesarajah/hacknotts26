# Wardrobe — a Clueless-style outfit picker

Flip through your clothes, and the app tells you whether the outfit is a **MATCH** or a **MISMATCH**, suggests outfits for today's weather, and learns your taste from 👍 / 👎.
Choose **My clothes** to browse your full wardrobe and delete individual items.

This is a **starter template**: everything runs end to end with simple versions of each part, and every file has a `TODO` list for its owner.

## Quick start

```bash
pip install -r requirements.txt
python scripts/make_placeholders.py      # draws placeholder clothing images
uvicorn backend.main:app --reload
```

- App: http://localhost:8000
- API docs (try every endpoint): http://localhost:8000/docs
- Tests: `pytest`

Optional, for offline CLIP tagging (large download):
`pip install -r requirements-ml.txt`

## Tagging uploads with a vision model

Uploads are tagged by a hosted vision model. Put your keys in `keys.env` in the project root (gitignored):

```
POLLINATIONS_API_KEY=sk_...     # https://enter.pollinations.ai/keys — tried first
GEMINI_API_KEY=...              # https://aistudio.google.com/apikey — used if Pollinations fails
```

The chain is **Pollinations → Gemini → CLIP → placeholder**. With no keys and no network the app still works:
uploads get placeholder tags marked `needs_review`. Change the order with
`TAGGER_PROVIDER_ORDER=gemini,clip,placeholder`. Test one photo with
`python -m input_pipeline.tagger_vlm data/images/t2.png`.

Before a demo, pre-tag a folder of photos straight into the database (no server needed):

```bash
python scripts/pretag_demo.py data/demo_photos      # --force to re-tag
python scripts/check_tagger.py path/to/kaggle-dataset --count 30   # accuracy check
```

## Who owns what

| Person | Folder | Job | Main tech |
|---|---|---|---|
| **1 — Wardrobe input** | `input_pipeline/` | Photo → cut-out → colors → tags → Item | Pillow, rembg, scikit-learn KMeans, CLIP |
| **2 — Outfit logic** | `outfit_logic/` | Build outfits, score them, learn from feedback | NumPy, scikit-learn |
| **3 — Interface** | `frontend/` | Carousels, verdict, flat-lay, upload | HTML/CSS/JS (React later if wanted) |
| **4 — Backend & integration** | `backend/`, `tests/` | Database, API, weather, joining it all | FastAPI, SQLite, Open-Meteo, pytest |

**Shared by everyone:** `shared/schema.py` — the item format. Don't change it without telling the team.

## How it flows

```
photo ─► P1 pipeline ─► P4 database ─► P3 carousels
                              │              │ user flips items
                              │              ▼
              weather (P4) ─► P2 scorer ◄── /api/score
                              ▲              │ MATCH / MISMATCH
                              │              ▼
                   P2 retrains ◄─ P4 saves ◄─ 👍 / 👎
```

## Project layout

```
shared/schema.py          the agreed Item / Outfit / Feedback format
data/sample_items.json    18 sample items to develop with
data/images/              item cut-outs (placeholders for now)
input_pipeline/           PERSON 1
  background.py           remove background (rembg, or white-background fallback)
  colors.py               main colors with KMeans
  tagger.py               the tagging chain: vision model -> CLIP -> placeholder
  tagger_vlm.py           Pollinations / Gemini vision-model tagging
  pipeline.py             all of the above: photo -> Item + tag metadata
outfit_logic/             PERSON 2
  generate.py             outfit templates + weather filters
  rules.py                color harmony, pattern, formality scoring
  feedback_model.py       scikit-learn taste model from 👍/👎
  scorer.py               what the backend calls
frontend/                 PERSON 3
  index.html, style.css, app.js
backend/                  PERSON 4
  main.py                 FastAPI endpoints
  db.py                   SQLite tables (items, feedback, tag_meta)
  weather.py              Open-Meteo weather
shared/env.py             loads API keys from keys.env
scripts/
  make_placeholders.py    draw placeholder images
  load_kaggle_sample.py   load ~50 real product photos from Kaggle
  pretag_demo.py          tag a folder of demo photos into the database
  check_tagger.py         measure tagging accuracy against Kaggle labels
tests/                    pytest
```

## Using real sample photos

Download **Fashion Product Images (Small)** from Kaggle, unzip it, then:

```bash
python scripts/load_kaggle_sample.py path/to/dataset --count 50
```

Add `--check-tagger` to measure how accurate the CLIP tagging is against the dataset's real labels.
Also photograph a few of your own clothes — real photos are much messier than shop photos.

## Suggested first week

1. **Day 1 (together):** read `shared/schema.py`, agree on it, get the app running on everyone's laptop.
2. **Each person:** work through the `TODO` list at the top of your files.
3. **End of week:** everyone's improvements merged, `pytest` passing.
