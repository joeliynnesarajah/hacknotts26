// PERSON 3 — Interface logic.
// Talks only to Person 4's API (see backend/main.py or http://localhost:8000/docs).
//
// TODO (Person 3):
//   - [ ] Swipe gestures on mobile for the carousels
//   - [ ] Outerwear row when it's cold
//   - [ ] Tag review screen after upload (needs_review = true)
//   - [ ] Nicer flat-lay: overlap items like a real photo

const SLOTS = {
  separates: ["top", "bottom", "shoes"],
  dress: ["dress", "shoes"],
};

let items = [];
let mode = "separates";
const index = {}; // category -> current position in the carousel

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function ofCategory(cat) {
  return items.filter((it) => it.category === cat);
}

function currentOutfit() {
  return SLOTS[mode].map((cat) => ofCategory(cat)[index[cat] || 0]).filter(Boolean);
}

function renderCarousels() {
  const box = $("carousels");
  box.innerHTML = "";
  for (const cat of SLOTS[mode]) {
    const list = ofCategory(cat);
    const item = list[index[cat] || 0];
    const row = document.createElement("div");
    row.className = "carousel";
    row.innerHTML = `
      <span class="label">${cat}</span>
      <button aria-label="previous ${cat}">‹</button>
      <figure>
        ${item ? `<img src="/${item.image}" alt="${item.name}"><figcaption>${item.name}</figcaption>`
               : "<figcaption>No items yet</figcaption>"}
      </figure>
      <button aria-label="next ${cat}">›</button>`;
    const [prev, next] = row.querySelectorAll("button");
    prev.onclick = () => step(cat, -1);
    next.onclick = () => step(cat, 1);
    box.appendChild(row);
  }
}

function step(cat, delta) {
  const n = ofCategory(cat).length;
  if (!n) return;
  index[cat] = ((index[cat] || 0) + delta + n) % n;
  refresh();
}

function renderFlatlay(outfit) {
  $("flatlay").innerHTML = outfit.map((it) => `<img src="/${it.image}" alt="${it.name}">`).join("");
}

async function scoreCurrent() {
  const outfit = currentOutfit();
  renderFlatlay(outfit);
  if (outfit.length < SLOTS[mode].length) {
    $("verdict").textContent = "Add more clothes";
    $("verdict").className = "verdict";
    return;
  }
  const result = await api("/api/score", {
    method: "POST",
    body: JSON.stringify({ item_ids: outfit.map((it) => it.id) }),
  });
  $("verdict").textContent = result.verdict === "MATCH" ? "MATCH!" : "MISMATCH";
  $("verdict").className = "verdict " + result.verdict.toLowerCase();
  $("score").textContent = `Score ${(result.score * 100).toFixed(0)} / 100`;
  $("reasons").innerHTML = result.reasons.map((r) => `<li>${r}</li>`).join("");
}

function refresh() {
  renderCarousels();
  scoreCurrent().catch(console.error);
}

// Jump the carousels to a suggested outfit
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

async function sendFeedback(liked) {
  const ids = currentOutfit().map((it) => it.id);
  const res = await api("/api/feedback", { method: "POST", body: JSON.stringify({ item_ids: ids, liked }) });
  $("upload-msg").textContent = res.taste_model_trained
    ? "Thanks! Your taste model has been updated."
    : "Thanks! A few more ratings and suggestions will start learning your taste.";
  scoreCurrent();
}

async function init() {
  items = await api("/api/items");
  refresh();

  api("/api/weather").then((w) => {
    $("weather").textContent = `${Math.round(w.temperature_c)}°C${w.raining ? ", raining" : ""} · ${w.season}`;
  });

  document.querySelectorAll(".mode button").forEach((btn) => {
    btn.onclick = () => {
      mode = btn.dataset.mode;
      document.querySelectorAll(".mode button").forEach((b) => b.classList.toggle("active", b === btn));
      refresh();
    };
  });

  $("suggest").onclick = async () => {
    const [best] = await api("/api/suggest?top_n=5");
    if (best) showOutfit(best.item_ids);
    else $("verdict").textContent = "Nothing suits today's weather";
  };
  $("like").onclick = () => sendFeedback(true);
  $("dislike").onclick = () => sendFeedback(false);
  $("wear").onclick = async () => {
    await api("/api/worn", { method: "POST", body: JSON.stringify({ item_ids: currentOutfit().map((i) => i.id) }) });
    $("upload-msg").textContent = "Noted — these won't be suggested for a few days.";
  };

  $("upload").onsubmit = async (e) => {
    e.preventDefault();
    $("upload-msg").textContent = "Processing photo…";
    try {
      const res = await api("/api/items/upload", { method: "POST", body: new FormData(e.target) });
      items = await api("/api/items");
      $("upload-msg").textContent = res.needs_review
        ? `Added "${res.item.name}". Tags are guesses — check them (review screen is a TODO).`
        : `Added "${res.item.name}" as a ${res.item.category}.`;
      e.target.reset();
      refresh();
    } catch (err) {
      $("upload-msg").textContent = "Upload failed: " + err.message;
    }
  };
}

init().catch((err) => ($("verdict").textContent = "Can't reach the API — is the server running?"));
