// PERSON 3 — Interface logic.
// Talks only to Person 4's API (see backend/main.py or http://localhost:8000/docs).
//
// How it works, in one go:
//   1. init() loads every clothing item from the API into `items`.
//   2. The screen shows one carousel per slot (top / bottom / shoes, or dress / shoes).
//      `index` remembers which item each carousel is currently showing.
//   3. Any change (arrow click, mode switch, suggestion) calls refresh(), which
//      redraws the carousels and asks the API to score the outfit on screen.
//   4. The score comes back as MATCH / MISMATCH plus reasons, and we show it in
//      the STATUS window and flash it across the screen.
//
// TODO (Person 3):
//   - [ ] Swipe gestures on mobile for the carousels
//   - [ ] Outerwear row when it's cold
//   - [ ] Nicer flat-lay: overlap items like a real photo

// Which carousels to show for each mode. The menu bar buttons switch between these.
const SLOTS = {
  separates: ["top", "bottom", "shoes"],
  dress: ["dress", "shoes"],
};

let items = [];         // every clothing item, as returned by GET /api/items
let mode = "separates"; // key into SLOTS
const index = {};       // category -> current position in the carousel (missing = 0)
let tagMeta = {};       // item id -> where its tags came from, from GET /api/tag-meta (optional)

// Shorthand: $("verdict") instead of document.getElementById("verdict")
const $ = (id) => document.getElementById(id);

// Item names can come from the vision model, so escape them before putting them in HTML
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// Tag chip text, e.g. "pollinations · 0.82" or "placeholder · 0.00  review"
function chipFor(meta) {
  if (!meta) return "";
  const conf = (meta.confidence ?? 0).toFixed(2);
  return `${meta.source} · ${conf}${meta.needs_review ? "  review" : ""}`;
}

// Call the backend and return the JSON reply. Throws if the server returns an error.
// File uploads (FormData) must not get a JSON Content-Type, so we only set it for JSON bodies.
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// All items in one category, e.g. ofCategory("shoes")
function ofCategory(cat) {
  return items.filter((it) => it.category === cat);
}

// The items currently showing in the carousels, in slot order.
// Empty categories are dropped, so this can be shorter than the slot list.
function currentOutfit() {
  return SLOTS[mode].map((cat) => ofCategory(cat)[index[cat] || 0]).filter(Boolean);
}

// Rebuild the middle column: one white frame + VCR buttons per slot.
// The `slot-<category>` class lets the CSS make the dress frame double height.
function renderCarousels() {
  const box = $("carousels");
  box.innerHTML = "";
  for (const cat of SLOTS[mode]) {
    const list = ofCategory(cat);
    const item = list[index[cat] || 0];
    const row = document.createElement("div");
    row.className = `carousel slot-${cat}`;
    row.innerHTML = `
      <figure>
        <span class="label">${cat}</span>
        ${item ? `<img src="/${item.image}" alt="${esc(item.name)}"><figcaption>${esc(item.name)}</figcaption>`
               : "<figcaption>No items yet</figcaption>"}
        ${item && tagMeta[item.id] ? `<span class="tagchip">${esc(chipFor(tagMeta[item.id]))}</span>` : ""}
      </figure>
      <div class="vcr">
        <button aria-label="previous ${cat}">◀◀</button>
        <button aria-label="random ${cat}">▶</button>
        <button aria-label="next ${cat}">▶▶</button>
      </div>`;
    const [prev, random, next] = row.querySelectorAll("button");
    prev.onclick = () => step(cat, -1);
    // Random: jump forward 1..n-1 places, so we always land on a *different* item
    random.onclick = () => step(cat, 1 + Math.floor(Math.random() * Math.max(list.length - 1, 1)));
    next.onclick = () => step(cat, 1);
    box.appendChild(row);
  }
}

// Move a carousel by `delta` places, wrapping round at either end.
function step(cat, delta) {
  const n = ofCategory(cat).length;
  if (!n) return;
  index[cat] = ((index[cat] || 0) + delta + n) % n;
  refresh();
}

// Show the current outfit's photos side by side in the FLAT-LAY window.
function renderFlatlay(outfit) {
  $("flatlay").innerHTML = outfit.map((it) => `<img src="/${it.image}" alt="${esc(it.name)}">`).join("");
}

// Flash the verdict across the whole screen, like the Clueless closet.
// `kind` is "match" or "mismatch" and picks the colour in style.css (.stamp.match / .stamp.mismatch).
function flashStamp(text, kind) {
  const stamp = $("stamp");
  stamp.textContent = text;
  stamp.className = "stamp " + kind; // removing "show" stops any flash in progress
  void stamp.offsetWidth; // restart the animation if it's already running
  stamp.classList.add("show"); // adding "show" starts the blink animation
}

// Ask the API to score whatever is on screen, then show the result.
async function scoreCurrent() {
  const outfit = currentOutfit();
  renderFlatlay(outfit);
  // A slot is empty (e.g. no shoes uploaded yet), so there's nothing to score
  if (outfit.length < SLOTS[mode].length) {
    $("verdict").textContent = "Add more clothes";
    $("verdict").className = "verdict";
    return;
  }
  // POST /api/score -> { verdict: "MATCH" | "MISMATCH", score: 0..1, reasons: [...] }
  const result = await api("/api/score", {
    method: "POST",
    body: JSON.stringify({ item_ids: outfit.map((it) => it.id) }),
  });
  $("verdict").textContent = result.verdict === "MATCH" ? "MATCH!" : "MISMATCH";
  $("verdict").className = "verdict " + result.verdict.toLowerCase(); // colours it green/red
  flashStamp($("verdict").textContent, result.verdict.toLowerCase());
  $("score").textContent = `Score ${(result.score * 100).toFixed(0)} / 100`;
  $("reasons").innerHTML = result.reasons.map((r) => `<li>${esc(r)}</li>`).join("");
}

// Redraw everything after any change. Scoring is async; errors go to the console.
function refresh() {
  renderCarousels();
  scoreCurrent().catch(console.error);
}

// Jump the carousels to a suggested outfit (used by DRESS ME).
// Switches to dress mode if the outfit has a dress, then points each carousel at the right item.
function showOutfit(itemIds) {
  const chosen = itemIds.map((id) => items.find((it) => it.id === id));
  mode = chosen.some((it) => it.category === "dress") ? "dress" : "separates";
  document.querySelectorAll(".mode button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  for (const it of chosen) {
    const pos = ofCategory(it.category).findIndex((x) => x.id === it.id);
    if (pos >= 0) index[it.category] = pos;
  }
  refresh();
}

// LOVE IT / AS IF! — save a thumbs up/down. The backend retrains the taste model
// each time, and once it has enough ratings the model starts affecting scores.
async function sendFeedback(liked) {
  const ids = currentOutfit().map((it) => it.id);
  const res = await api("/api/feedback", { method: "POST", body: JSON.stringify({ item_ids: ids, liked }) });
  $("upload-msg").textContent = res.taste_model_trained
    ? "Thanks! Your taste model has been updated."
    : "Thanks! A few more ratings and suggestions will start learning your taste.";
  scoreCurrent();
}

// Runs once when the page loads: fetch data and wire up every button.
async function init() {
  items = await api("/api/items");
  refresh();

  // Weather in the title bar, e.g. "12°C, raining · autumn".
  // Display only — the backend fetches its own weather when suggesting outfits.
  api("/api/weather").then((w) => {
    $("weather").textContent = `${Math.round(w.temperature_c)}°C${w.raining ? ", raining" : ""} · ${w.season}`;
  });

  // Tag chips under the carousel captions. Optional: if this fails, the page just has no chips.
  api("/api/tag-meta").then((m) => { tagMeta = m; renderCarousels(); }).catch(() => {});

  // Menu bar: SEPARATES / DRESSES. Each button's data-mode is a key in SLOTS.
  document.querySelectorAll(".mode button").forEach((btn) => {
    btn.onclick = () => {
      mode = btn.dataset.mode;
      document.querySelectorAll(".mode button").forEach((b) => b.classList.toggle("active", b === btn));
      refresh();
    };
  });

  // DRESS ME — ask the backend for the best outfits for today's weather and show the top one
  $("suggest").onclick = async () => {
    const [best] = await api("/api/suggest?top_n=5");
    if (best) showOutfit(best.item_ids);
    else $("verdict").textContent = "Nothing suits today's weather";
  };
  $("like").onclick = () => sendFeedback(true);
  $("dislike").onclick = () => sendFeedback(false);
  // WEAR TODAY — logged so DRESS ME skips these items for a few days
  $("wear").onclick = async () => {
    await api("/api/worn", { method: "POST", body: JSON.stringify({ item_ids: currentOutfit().map((i) => i.id) }) });
    $("upload-msg").textContent = "Noted — these won't be suggested for a few days.";
  };

  // ADD CLOTHES — send the photo to the backend, which removes the background,
  // tags it with the vision model, then reload the item list so it appears.
  // The tag chip has its own element (#tagchip) so feedback messages don't overwrite it.
  $("upload").onsubmit = async (e) => {
    e.preventDefault(); // stop the browser doing a normal page-reloading form submit
    $("upload-msg").textContent = "Processing photo…";
    $("tagchip").textContent = "";
    try {
      const res = await api("/api/items/upload", { method: "POST", body: new FormData(e.target) });
      items = await api("/api/items");
      if (res.tag_meta) tagMeta[res.item.id] = res.tag_meta;
      $("tagchip").textContent = chipFor(res.tag_meta);
      $("upload-msg").textContent = `Added "${res.item.name}" as a ${res.item.category}.`;
      e.target.reset();
      // Jump that carousel to the new item so you see it straight away
      const pos = ofCategory(res.item.category).findIndex((x) => x.id === res.item.id);
      if (pos >= 0) index[res.item.category] = pos;
      refresh();
    } catch (err) {
      $("upload-msg").textContent = "Upload failed: " + err.message;
    }
  };
}

init().catch((err) => ($("verdict").textContent = "Can't reach the API — is the server running?"));
