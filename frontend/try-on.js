// PERSON 3 — Paper-doll try-on logic. Same API as the closet page (app.js).
//
// How it works:
//   1. Load every item. Each slot (top / bottom / shoes, or dress / shoes) has a picker
//      with ◀◀ ▶ ▶▶, and `index` remembers which item each slot shows.
//   2. renderMannequin() layers the chosen cutouts over the figure. The cutouts are square
//      PNGs with lots of transparent padding (shoes fill only a thin strip), so trimmed()
//      crops each one to its visible pixels first; CSS then fits it into that body part's box.
//   3. Every change re-scores the outfit (POST /api/score), flashes MATCH!/MISMATCH and
//      plays a sound (sounds.js).
//   4. The figure is the Cher silhouette, or your own photo from POST /api/avatar.

const SLOTS = {
  separates: ["top", "bottom", "shoes"],
  dress: ["dress", "shoes"],
};
// Which body box each category is drawn in (see .layer.* in style.css)
const LAYER = { top: "torso", bottom: "bottom", dress: "dress", shoes: "shoes" };
const SILHOUETTE = "/static/cher-silhouette.svg";

let items = [];
let mode = "separates";
const index = {};
let renderToken = 0; // so a slow image from an old click can't overwrite a newer outfit

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

const ofCategory = (cat) => items.filter((it) => it.category === cat);
const currentOutfit = () => SLOTS[mode].map((cat) => ofCategory(cat)[index[cat] || 0]).filter(Boolean);

// ---- trimming: crop a cutout to its non-transparent pixels (cached per image) ----
const trimCache = {};
function trimmed(src) {
  if (!trimCache[src]) {
    trimCache[src] = new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const w = img.naturalWidth, h = img.naturalHeight;
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const g = canvas.getContext("2d");
        g.drawImage(img, 0, 0);
        let data;
        try {
          data = g.getImageData(0, 0, w, h).data;
        } catch {
          return resolve(src); // canvas blocked (shouldn't happen, same origin): use as-is
        }
        let x0 = w, y0 = h, x1 = -1, y1 = -1;
        for (let y = 0; y < h; y++) {
          for (let x = 0; x < w; x++) {
            if (data[(y * w + x) * 4 + 3] > 16) {
              if (x < x0) x0 = x;
              if (x > x1) x1 = x;
              if (y < y0) y0 = y;
              if (y > y1) y1 = y;
            }
          }
        }
        if (x1 < 0) return resolve(src); // fully transparent: nothing to trim
        const out = document.createElement("canvas");
        out.width = x1 - x0 + 1;
        out.height = y1 - y0 + 1;
        out.getContext("2d").drawImage(canvas, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
        resolve(out.toDataURL("image/png"));
      };
      img.onerror = () => resolve(src);
      img.src = src;
    });
  }
  return trimCache[src];
}

// ---- drawing ----
async function renderMannequin() {
  const token = ++renderToken;
  const outfit = currentOutfit();
  const srcs = await Promise.all(outfit.map((it) => trimmed(`/${it.image}`)));
  if (token !== renderToken) return; // the user has clicked again since
  const box = $("mannequin");
  box.querySelectorAll(".layer").forEach((el) => el.remove());
  outfit.forEach((it, i) => {
    const img = document.createElement("img");
    img.className = `layer ${LAYER[it.category]}`;
    img.src = srcs[i];
    img.alt = it.name;
    box.appendChild(img);
  });
}

function renderPickers() {
  const box = $("pickers");
  box.innerHTML = "";
  for (const cat of SLOTS[mode]) {
    const list = ofCategory(cat);
    const item = list[index[cat] || 0];
    const row = document.createElement("div");
    row.className = "picker";
    row.innerHTML = `
      <span class="picker-label">${cat}</span>
      <span class="picker-name">${item ? esc(item.name) : "No items yet"}</span>
      <div class="vcr">
        <button aria-label="previous ${cat}">◀◀</button>
        <button aria-label="random ${cat}">▶</button>
        <button aria-label="next ${cat}">▶▶</button>
      </div>`;
    const [prev, random, next] = row.querySelectorAll("button");
    prev.onclick = () => step(cat, -1);
    random.onclick = () => step(cat, 1 + Math.floor(Math.random() * Math.max(list.length - 1, 1)));
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

function flashStamp(text, kind) {
  const stamp = $("stamp");
  stamp.textContent = text;
  stamp.className = "stamp " + kind;
  void stamp.offsetWidth; // restart the animation
  stamp.classList.add("show");
  Sound.play(kind);
}

async function scoreCurrent() {
  const outfit = currentOutfit();
  if (outfit.length < SLOTS[mode].length) {
    $("verdict").textContent = "Add more clothes";
    $("verdict").className = "verdict";
    $("score").textContent = "";
    $("reasons").innerHTML = "";
    return;
  }
  const result = await api("/api/score", {
    method: "POST",
    body: JSON.stringify({ item_ids: outfit.map((it) => it.id) }),
  });
  const kind = result.verdict.toLowerCase();
  $("verdict").textContent = result.verdict === "MATCH" ? "MATCH!" : "MISMATCH";
  $("verdict").className = "verdict " + kind;
  flashStamp($("verdict").textContent, kind);
  $("score").textContent = `Score ${(result.score * 100).toFixed(0)} / 100`;
  $("reasons").innerHTML = result.reasons.map((r) => `<li>${esc(r)}</li>`).join("");
}

function refresh() {
  renderPickers();
  renderMannequin().catch(console.error);
  scoreCurrent().catch(console.error);
}

function setMode(next) {
  mode = next;
  document.querySelectorAll(".mode button").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
}

function showOutfit(itemIds) {
  const chosen = itemIds.map((id) => items.find((it) => it.id === id)).filter(Boolean);
  setMode(chosen.some((it) => it.category === "dress") ? "dress" : "separates");
  for (const it of chosen) {
    const pos = ofCategory(it.category).findIndex((x) => x.id === it.id);
    if (pos >= 0) index[it.category] = pos;
  }
  refresh();
}

async function sendFeedback(liked) {
  const ids = currentOutfit().map((it) => it.id);
  if (!ids.length) return;
  const res = await api("/api/feedback", { method: "POST", body: JSON.stringify({ item_ids: ids, liked }) });
  $("feedback-msg").textContent = res.taste_model_trained
    ? "Thanks! Your taste model has been updated."
    : "Thanks! A few more ratings and suggestions will start learning your taste.";
}

// ---- avatar ----
function showAvatar(url) {
  // Your photo if there is one, otherwise the Cher silhouette; CRT beige shows behind either
  $("mannequin").style.backgroundImage = `url("${url || SILHOUETTE}")`;
  $("mannequin").classList.toggle("custom", Boolean(url));
  $("avatar-reset").hidden = !url;
}

async function init() {
  items = await api("/api/items");
  const wanted = new URLSearchParams(location.search).get("mode"); // e.g. /try-on?mode=dress
  if (wanted in SLOTS) setMode(wanted);
  refresh();

  api("/api/weather").then((w) => {
    $("weather").textContent = `${Math.round(w.temperature_c)}°C${w.raining ? ", raining" : ""} · ${w.season}`;
  }).catch(() => ($("weather").textContent = ""));

  showAvatar(null);
  api("/api/avatar").then((a) => showAvatar(a.url)).catch(() => {});

  document.querySelectorAll(".mode button").forEach((btn) => {
    btn.onclick = () => { setMode(btn.dataset.mode); refresh(); };
  });

  $("suggest").onclick = async () => {
    const [best] = await api("/api/suggest?top_n=5");
    if (best) showOutfit(best.item_ids);
    else $("verdict").textContent = "Nothing suits today's weather";
  };
  $("like").onclick = () => sendFeedback(true).catch((e) => ($("feedback-msg").textContent = e.message));
  $("dislike").onclick = () => sendFeedback(false).catch((e) => ($("feedback-msg").textContent = e.message));

  $("avatar-form").onsubmit = async (e) => {
    e.preventDefault();
    const button = e.target.querySelector("button");
    button.disabled = true;
    $("avatar-msg").textContent = "Cutting you out…";
    try {
      const res = await api("/api/avatar", { method: "POST", body: new FormData(e.target) });
      showAvatar(res.url);
      $("avatar-msg").textContent = "Looking good. Clothes are placed for a standard pose, so the fit is approximate.";
      e.target.reset();
    } catch (err) {
      $("avatar-msg").textContent = "Couldn't use that photo: " + err.message;
    } finally {
      button.disabled = false;
    }
  };

  $("avatar-reset").onclick = async () => {
    await api("/api/avatar", { method: "DELETE" }).catch(() => {});
    showAvatar(null);
    $("avatar-msg").textContent = "Back to Cher.";
  };
}

init().catch(() => ($("verdict").textContent = "Can't reach the API — is the server running?"));
