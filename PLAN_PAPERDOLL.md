# Clueless-Style Paper Doll Try-On — Grounded Plan (Verified)

Confirmed: `rembg` installed and working in `.venv`. `/images` static mount exists at `backend/main.py:202` serving `ROOT/data/images`. `remove_background()` lives in `input_pipeline/background.py` (rembg when available, white-pixel fallback otherwise). `crop_to_content()` does bbox + 10px pad + square. `flashStamp()` at `frontend/app.js:110` is text-only.

---

## Architecture
New page: `frontend/try-on.html` — separate from `frontend/index.html` (the closet-computer page stays untouched). Served as a static file from `ROOT/frontend`.

Layers map to `data/sample_items.json` categories:
- `top` (t1-t6) → torso overlay
- `bottom` (b1-b5), `dress` (d1) → legs overlay  
- `shoes` (s1-s4) → feet overlay
- `outerwear` (o1-o2): optional later, skip for now

---

## Phase 0: Default avatar — Cher silhouette SVG

Create `frontend/cher-silhouette.svg` (standalone file, ~180×420). Use as `#mannequin` background-image fallback when no custom avatar is uploaded:

```
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 420" width="180" height="420">
  <!-- head / hair bob -->
  <circle cx="90" cy="55" r="24" fill="#fce7d3"/>
  <path d="M66 55 Q90 30 114 55 V 90 Q90 95 66 90 Z" fill="#ffe4c4"/>

  <!-- neck -->
  <rect x="81" y="90" w="18" h="16" fill="#fce7d3"/>

  <!-- torso / jacket -->
  <path d="M62 106 L50 160 Q52 200 70 215 L110 215 Q128 200 130 160 L118 106 Z" fill="#c8102e"/>

  <!-- arms -->
  <path d="M50 130 Q30 140 35 170 Q40 200 58 185 L58 130 Z" fill="#fce7d3"/>
  <path d="M130 130 Q150 140 145 170 Q140 200 122 185 L122 130 Z" fill="#fce7d3"/>

  <!-- legs / skirt -->
  <path d="M66 215 Q90 225 114 215 L122 240 Q122 380 90 380 Q58 380 58 240 Z" fill="#fce7d3"/>

  <!-- shoes -->
  <ellipse cx="78" cy="395" rx="18" ry="10" fill="#c8102e"/>
  <ellipse cx="102" cy="395" rx="18" ry="10" fill="#c8102e"/>
</svg>
```

Mannequin background chain: custom `avatar.png` → falls back to `/static/cher-silhouette.svg` → solid CRT beige.

---

## Phase 1: Backend `/api/avatar` endpoints (`backend/main.py`)

Add near other endpoints (before `@app.get("/")` at line ~218):

```python
AVATAR_PATH = ROOT / "data" / "images" / "avatar.png"

@app.post("/api/avatar")
async def upload_avatar(file: UploadFile):
    if not AVATAR_PATH.parent.exists():
        AVATAR_PATH.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(await file.read())
    img = remove_background(img)
    img.save(AVATAR_PATH)
    return {"url": "/images/avatar.png"}

@app.get("/api/avatar")
def get_avatar():
    return {"url": "/images/avatar.png"} if AVATAR_PATH.exists() else {"url": None}

@app.delete("/api/avatar")
def delete_avatar():
    if AVATAR_PATH.exists(): AVATAR_PATH.unlink()
    return {"url": None}
```

Imports needed in main.py: `from PIL import Image` (already present at line 36), `from input_pipeline.background import remove_background`, `from fastapi import UploadFile`. `ROOT` is defined at line 51.

---

## Phase 2: New page `frontend/try-on.html`

Structure:
- Header: `WARDROBE — Try-On` + `[Cher]` toggle | `[+ Upload Photo]` hidden file input
- Center: `<div id="mannequin">` with background image + absolutely positioned layer overlays
- Side: flat-lay preview of current outfit and `◀◀ ◀ ▶ ▶▶` per category
- Footer: `Love it`, `As if!`, `Wear today` buttons
- Same VT323 font / CRT styling as `index.html`

---

## Phase 3: CSS layer positions (`frontend/style.css`)

Mannequin container is **180px × 420px** vertical portrait. Body proportions from the SVG:

```css
#mannequin {
  position: relative;
  width: 180px;
  height: 420px;
  margin: 0 auto;
  background-size: contain;
  background-repeat: no-repeat;
  background-position: center;
  background-color: #f4e8d9; /* CRT beige */
}

.layer {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  width: auto;
  height: auto;
  max-width: 90%;
  pointer-events: none;
  will-change: transform;
}

.layer.torso { top: 90px; }   /* below neck, over jacket chest */
.layer.legs  { top: 210px; }  /* skirt/leg region */
.layer.feet  { top: 330px; }  /* shoe region, above y=395 shoes */
```

Overlays use `data/images/{item_id}.png` (square transparent PNGs from `crop_to_content()`), so centering via `translateX(-50%)` keeps alignment consistent across items.

---

## Phase 4: Retro audio (`frontend/app.js`)

Add inside `flashStamp()` (line 110) or call from `scoreCurrent()`:

```js
function beepMismatch() {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const o1 = ctx.createOscillator(), o2 = ctx.createOscillator();
  const s = ctx.createGain();
  o1.type = "square"; o1.frequency.setValueAtTime(120, ctx.currentTime);
  o2.type = "square"; o2.frequency.setValueAtTime(126, ctx.currentTime);
  o1.connect(s); o2.connect(s); s.connect(ctx.destination);
  o1.start(); o2.start();
  s.gain.setValueAtTime(0.3, ctx.currentTime);
  s.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
  o1.stop(ctx.currentTime + 0.5); o2.stop(ctx.currentTime + 0.5);
}
```

- `MISMATCH`: dual-oscillator harsh square buzz at `120Hz` + `126Hz`
- `MATCH!`: high-frequency FM/arpeggiated bell chime (same pattern, different freq)

---

## Verification checklist
1. `frontend/cher-silhouette.svg` renders as mannequin fallback
2. `POST /api/avatar` accepts photo → rembg removes background → `/images/avatar.png`
3. `GET /api/avatar` returns url or `null`
4. `DELETE /api/avatar` clears custom avatar, falls back to SVG
5. `/try-on.html` loads, shows mannequin with SVG fallback
6. Upload photo replaces background instantly
7. Cycling items layers torso/legs/feet correctly
8. Audio plays on score
9. All pytest tests still pass

**Nothing implemented yet — plan only.**
