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
const index = {};       // category -> selected position; -1 means the user hasn't chosen an item
let tagMeta = {};       // item id -> where its tags came from, from GET /api/tag-meta (optional)
let scoreRequest = 0;
let retroAudioContext;

// Shorthand: $("verdict") instead of document.getElementById("verdict")
const $ = (id) => document.getElementById(id);

// Item names can come from the vision model, so escape them before putting them in HTML
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

$("play-now").addEventListener("click", () => {
  clearInterval(loadingProgressTimer);
  $("try-on-loading").hidden = true;
  document.querySelector(".monitor").hidden = false;
  document.querySelector("#carousels button:not(:disabled)")?.focus({ preventScroll: true });
  document.querySelector(".desktop").scrollIntoView({ behavior: "smooth", block: "start" });
});

const LOADING_BLOCK_COUNT = 24;
const LOADING_BATCH_SIZE = 3;
const LOADING_BATCH_INTERVAL_MS = 250;
const loadingBlocks = $("loading-blocks");
const loadingBar = document.querySelector(".loading-bar");
for (let i = 0; i < LOADING_BLOCK_COUNT; i += 1) {
  const block = document.createElement("span");
  block.className = "loading-block";
  loadingBlocks.appendChild(block);
}

let loadedBlockCount = 0;
const loadingProgressTimer = window.setInterval(() => {
  const nextBlockCount = Math.min(LOADING_BLOCK_COUNT, loadedBlockCount + LOADING_BATCH_SIZE);
  for (let i = loadedBlockCount; i < nextBlockCount; i += 1) {
    loadingBlocks.children[i].classList.add("filled");
  }
  loadedBlockCount = nextBlockCount;
  loadingBar.setAttribute("aria-valuenow", String(loadedBlockCount));
  if (loadedBlockCount === LOADING_BLOCK_COUNT) clearInterval(loadingProgressTimer);
}, LOADING_BATCH_INTERVAL_MS);

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

function selectedItem(cat) {
  const position = index[cat] ?? -1;
  return position < 0 ? undefined : ofCategory(cat)[position];
}

// The items currently showing in the carousels, in slot order.
// Categories without a user selection are omitted.
function currentOutfit() {
  return SLOTS[mode].map(selectedItem).filter(Boolean);
}

// Rebuild the middle column: one white frame + VCR buttons per slot.
// The `slot-<category>` class lets the CSS make the dress frame double height.
function renderCarousels() {
  const box = $("carousels");
  box.innerHTML = "";
  for (const cat of SLOTS[mode]) {
    const list = ofCategory(cat);
    const item = selectedItem(cat);
    const row = document.createElement("div");
    row.className = `carousel slot-${cat}`;
    row.innerHTML = `
      <figure>
        <span class="label">${cat}</span>
        ${item ? `<img src="/${item.image}" alt="${esc(item.name)}"><figcaption>${esc(item.name)}</figcaption>`
               : `<figcaption>${list.length ? "Choose an item" : "No items yet"}</figcaption>`}
        ${item && tagMeta[item.id] ? `<span class="tagchip">${esc(chipFor(tagMeta[item.id]))}</span>` : ""}
      </figure>
      <div class="vcr">
        <button aria-label="previous ${cat}" ${list.length ? "" : "disabled"}>◀◀</button>
        <button aria-label="random ${cat}" ${list.length ? "" : "disabled"}>▶</button>
        <button aria-label="next ${cat}" ${list.length ? "" : "disabled"}>▶▶</button>
      </div>`;
    const [prev, random, next] = row.querySelectorAll("button");
    prev.onclick = () => step(cat, -1);
    random.onclick = () => chooseRandom(cat);
    next.onclick = () => step(cat, 1);
    box.appendChild(row);
  }
}

// Move a carousel by `delta` places, wrapping round at either end.
function step(cat, delta) {
  const n = ofCategory(cat).length;
  if (!n) return;
  const current = index[cat] ?? -1;
  index[cat] = current < 0 ? (delta < 0 ? n - 1 : 0) : (current + delta + n) % n;
  prepareRetroAudio();
  refresh();
}

function chooseRandom(cat) {
  const count = ofCategory(cat).length;
  if (!count) return;
  const current = index[cat] ?? -1;
  if (count === 1) {
    index[cat] = 0;
  } else {
    let next;
    do {
      next = Math.floor(Math.random() * count);
    } while (next === current);
    index[cat] = next;
  }
  prepareRetroAudio();
  refresh();
}

// Show the current outfit's photos side by side in the FLAT-LAY window.
function renderFlatlay(outfit) {
  $("flatlay").innerHTML = outfit.map((it) => `<img src="/${it.image}" alt="${esc(it.name)}">`).join("");
}

function renderWardrobe() {
  const list = $("wardrobe-items");
  list.innerHTML = "";
  if (!items.length) {
    list.textContent = "Your wardrobe is empty.";
    return;
  }

  for (const item of items) {
    const row = document.createElement("article");
    row.className = "wardrobe-item";
    row.innerHTML = `
      <img src="/${esc(item.image)}" alt="${esc(item.name)}">
      <div class="wardrobe-item-info">
        <strong>${esc(item.name)}</strong>
        <span>${esc(item.category)}</span>
      </div>
      <button type="button" class="wardrobe-delete">Delete</button>`;
    row.querySelector("button").onclick = async (event) => {
      if (!window.confirm(`Delete "${item.name}" from your wardrobe?`)) return;
      const button = event.currentTarget;
      button.disabled = true;
      $("wardrobe-msg").textContent = "";
      try {
        await api(`/api/items/${encodeURIComponent(item.id)}`, { method: "DELETE" });
        const selected = Object.fromEntries(
          [...new Set(items.map((it) => it.category))]
            .map((category) => [category, selectedItem(category)?.id]),
        );
        items = items.filter((it) => it.id !== item.id);
        delete tagMeta[item.id];
        for (const [category, selectedId] of Object.entries(selected)) {
          const categoryItems = ofCategory(category);
          const selectedIndex = categoryItems.findIndex((it) => it.id === selectedId);
          index[category] = selectedIndex >= 0
            ? selectedIndex
            : selectedId
              ? Math.min(index[category] ?? 0, Math.max(categoryItems.length - 1, 0))
              : -1;
        }
        $("wardrobe-msg").textContent = `"${item.name}" deleted.`;
        renderWardrobe();
        refresh();
      } catch (err) {
        $("wardrobe-msg").textContent = `Couldn't delete "${item.name}": ${err.message}`;
        button.disabled = false;
      }
    };
    list.appendChild(row);
  }
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

function flashReaction(liked) {
  const stamp = $("stamp");
  const icon = liked
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 3h6v2h4V3h6v2h2v7h-2v3h-2v2h-2v2h-2v2h-2v-2h-2v-2H8v-2H6v-3H4z"/></svg>'
    : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3h4v12H3zM9 3h9l3 3v7l-2 3h-3l-3 5-3-1v-5H7V5h2z"/></svg>';
  const label = liked ? "LOVE IT!" : "UGH, AS IF!";
  stamp.innerHTML = `<span class="reaction-icon">${icon}</span><span class="reaction-label">${label}</span>`;
  stamp.className = `stamp reaction ${liked ? "love" : "dislike"}`;
  void stamp.offsetWidth;
  stamp.classList.add("show");
}

function prepareRetroAudio() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return null;
  retroAudioContext ||= new AudioContextClass();
  if (retroAudioContext.state === "suspended") retroAudioContext.resume();
  return retroAudioContext;
}

function playRetroSound(kind) {
  if (typeof Sound !== "undefined" && !Sound.enabled()) return; // the ♪ off switch in the title bar
  const ctx = prepareRetroAudio();
  if (!ctx) return;

  const patterns = {
    match: { notes: [[659.25, 0], [783.99, 0.09], [987.77, 0.18]], wave: "sine", duration: 0.32 },
    mismatch: { notes: [[120, 0], [126, 0]], wave: "square", duration: 0.42, volume: 0.11 },
    love: { notes: [[880, 0], [1174.66, 0.09], [1567.98, 0.18]], wave: "triangle", duration: 0.34 },
    dislike: { notes: [[392, 0], [293.66, 0.12], [196, 0.24]], wave: "square", duration: 0.16, volume: 0.09 },
  };
  const pattern = patterns[kind];
  if (!pattern) return;

  const start = ctx.currentTime;
  for (const [frequency, offset] of pattern.notes) {
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    const noteStart = start + offset;
    oscillator.type = pattern.wave;
    oscillator.frequency.setValueAtTime(frequency, noteStart);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0.0001, noteStart);
    gain.gain.exponentialRampToValueAtTime(pattern.volume ?? 0.12, noteStart + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, noteStart + pattern.duration);
    oscillator.start(noteStart);
    oscillator.stop(noteStart + pattern.duration + 0.01);
  }
}

// Ask the API to score whatever is on screen, then show the result.
async function scoreCurrent(showVerdict = true) {
  const request = ++scoreRequest;
  const outfit = currentOutfit();
  renderFlatlay(outfit);
  // A slot is empty (e.g. no shoes uploaded yet), so there's nothing to score
  if (outfit.length < SLOTS[mode].length) {
    $("verdict").textContent = outfit.length ? "Choose the rest of your outfit" : "Pick an outfit";
    $("verdict").className = "verdict";
    $("score").textContent = "";
    $("reasons").innerHTML = "";
    return;
  }
  // POST /api/score -> { verdict: "MATCH" | "MISMATCH", score: 0..1, reasons: [...] }
  const result = await api("/api/score", {
    method: "POST",
    body: JSON.stringify({ item_ids: outfit.map((it) => it.id) }),
  });
  if (request !== scoreRequest) return;
  $("verdict").textContent = result.verdict === "MATCH" ? "MATCH!" : "MISMATCH";
  $("verdict").className = "verdict " + result.verdict.toLowerCase(); // colours it green/red
  if (showVerdict) {
    flashStamp($("verdict").textContent, result.verdict.toLowerCase());
    playRetroSound(result.verdict.toLowerCase());
  }
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
  const chosen = itemIds.map((id) => items.find((it) => it.id === id)).filter(Boolean);
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
  const outfit = currentOutfit();
  if (outfit.length !== SLOTS[mode].length) {
    $("upload-msg").textContent = "Choose a complete outfit before rating it.";
    return;
  }
  scoreRequest += 1;
  flashReaction(liked);
  playRetroSound(liked ? "love" : "dislike");
  const ids = outfit.map((it) => it.id);
  try {
    const res = await api("/api/feedback", { method: "POST", body: JSON.stringify({ item_ids: ids, liked }) });
    $("upload-msg").textContent = res.taste_model_trained
      ? "Thanks! Your taste model has been updated."
      : "Thanks! A few more ratings and suggestions will start learning your taste.";
    scoreCurrent(false).catch(console.error);
  } catch (err) {
    $("upload-msg").textContent = `Couldn't save feedback: ${err.message}`;
  }
}

// Runs once when the page loads: fetch data and wire up every button.
async function init() {
  $("open-try-on").addEventListener("click", (event) => {
    event.preventDefault();
    window.location.assign("/try-on.html");
  });

  items = await api("/api/items");
  refresh();

  $("show-wardrobe").onclick = () => {
    $("wardrobe-msg").textContent = "";
    renderWardrobe();
    $("wardrobe-dialog").showModal();
  };
  $("wardrobe-close").onclick = () => $("wardrobe-dialog").close();

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
      prepareRetroAudio();
      mode = btn.dataset.mode;
      document.querySelectorAll(".mode button").forEach((b) => b.classList.toggle("active", b === btn));
      refresh();
    };
  });

  // DRESS ME — a random good match for today's weather (different every press, never the
  // outfit already on screen). Higher-scoring matches are more likely; see pick_outfit().
  let dressRequest = 0; // so a slow reply to an earlier press can't overwrite a newer one
  $("suggest").onclick = async () => {
    prepareRetroAudio();
    const request = ++dressRequest;
    try {
      const avoid = currentOutfit().map((it) => it.id).join(",");
      // Stay in the mode the user is in: Dresses mode always gets a dress
      const pick = await api(`/api/outfit/random?mode=${mode}&avoid=${encodeURIComponent(avoid)}`);
      if (request !== dressRequest) return;
      showOutfit(pick.item_ids);
      // A coat on a cold day has no carousel slot, so mention it
      const coats = pick.item_ids.map((id) => items.find((it) => it.id === id))
        .filter((it) => it && it.category === "outerwear");
      $("upload-msg").textContent = coats.length ? `Add the ${coats.map((c) => c.name).join(", ")}: it's chilly out.` : "";
    } catch (err) {
      $("verdict").textContent = mode === "dress" ? "No dresses yet" : "Nothing to wear yet";
    }
  };
  $("like").onclick = () => sendFeedback(true);
  $("dislike").onclick = () => sendFeedback(false);

  // ADD CLOTHES — send the photo to the backend, which removes the background,
  // tags it with the vision model, then reload the item list so it appears.
  // The tag chip has its own element (#tagchip) so feedback messages don't overwrite it.
  $("upload").onsubmit = async (e) => {
    e.preventDefault(); // stop the browser doing a normal page-reloading form submit
    prepareRetroAudio();
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
