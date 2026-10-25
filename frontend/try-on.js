const $ = (id) => document.getElementById(id);
const esc = (value) => String(value).replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);

let items = [];
let mode = "separates";
let avatarAudioContext;
let scoreRequest = 0;
const positions = { top: 0, bottom: 0, dress: 0, shoes: 0 };
const categories = {
  separates: ["top", "bottom", "shoes"],
  dress: ["dress", "shoes"],
};

// Photoreal try-on state. "Dress me" can add a coat when it's cold; the paper doll has no coat
// slot, so those extra items ride along here and are included in the AI render only.
let extraIds = [];
let renderToken = 0;       // bumping it cancels any render we're still waiting for
const RENDER_POLL_MS = 2000;
const RENDER_GIVE_UP_MS = 200000; // longer than the backend's worst case (two models x 90s timeout)

function prepareTryOnAudio() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return null;
  avatarAudioContext ||= new AudioContextClass();
  if (avatarAudioContext.state === "suspended") avatarAudioContext.resume();
  return avatarAudioContext;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function itemsFor(category) {
  return items.filter((item) => item.category === category);
}

function currentOutfit() {
  return categories[mode]
    .map((category) => itemsFor(category)[positions[category] || 0])
    .filter(Boolean);
}

// ---- paper doll: fit each garment cutout onto the body ----
// Width / height of each layer box in try-on.css (% of the 180x420 frame), to choose fill vs contain
const LAYER_BOX_ASPECT = {
  torso: (0.65 * 180) / (0.305 * 420),
  legs: (0.49 * 180) / (0.43 * 420),
  dress: (0.66 * 180) / (0.56 * 420),
};
const preparedCache = {};
let layerRequest = 0;

// Crop a cutout to its visible pixels (they're padded squares) and, for tops, cut off a hanger:
// narrow rows at the very top (the hook) are dropped. Returns {src, aspect}; cached per image.
function prepareGarment(src, category) {
  const cacheKey = `${category}|${src}`;
  if (!preparedCache[cacheKey]) {
    preparedCache[cacheKey] = new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const w = img.naturalWidth;
        const h = img.naturalHeight;
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0);
        let data;
        try {
          data = ctx.getImageData(0, 0, w, h).data;
        } catch {
          return resolve({ src, aspect: w / h });
        }
        const rowWidth = new Array(h).fill(0);
        let x0 = w, x1 = -1, y0 = h, y1 = -1;
        for (let y = 0; y < h; y++) {
          let first = -1, last = -1;
          for (let x = 0; x < w; x++) {
            if (data[(y * w + x) * 4 + 3] > 24) {
              if (first < 0) first = x;
              last = x;
            }
          }
          if (first >= 0) {
            rowWidth[y] = last - first + 1;
            if (y < y0) y0 = y;
            y1 = y;
          }
        }
        if (y1 < 0) return resolve({ src, aspect: w / h });
        if (["top", "outerwear", "dress"].includes(category)) {
          const widest = Math.max(...rowWidth);
          while (y0 < y1 && rowWidth[y0] < widest * 0.3) y0++; // hanger hook / tag loop
        }
        for (let y = y0; y <= y1; y++) {
          for (let x = 0; x < w; x++) {
            if (data[(y * w + x) * 4 + 3] > 24) {
              if (x < x0) x0 = x;
              if (x > x1) x1 = x;
            }
          }
        }
        const out = document.createElement("canvas");
        out.width = x1 - x0 + 1;
        out.height = y1 - y0 + 1;
        out.getContext("2d").drawImage(canvas, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
        resolve({ src: out.toDataURL("image/png"), aspect: out.width / out.height });
      };
      img.onerror = () => resolve({ src, aspect: 1 });
      img.src = src;
    });
  }
  return preparedCache[cacheKey];
}

function showItemLayer(layerId, item, prepared, box) {
  const layer = $(layerId);
  layer.classList.toggle("dress", item?.category === "dress");
  if (!item || !prepared) {
    layer.removeAttribute("src");
    layer.hidden = true;
    return;
  }
  // Stretch to the body when the garment's shape is close to its box; otherwise keep its shape
  const ratio = box ? prepared.aspect / LAYER_BOX_ASPECT[box] : 1;
  layer.classList.toggle("fit-contain", Boolean(box) && (ratio < 0.7 || ratio > 1.45));
  layer.src = prepared.src;
  layer.alt = item.name;
  layer.hidden = false;
}

async function renderLayers() {
  const request = ++layerRequest;
  const outfit = currentOutfit();
  $("try-on-flatlay").innerHTML = outfit.map((item) =>
    `<img class="try-on-flat-item" src="/${esc(item.image)}" alt="${esc(item.name)}">`).join("");
  const top = mode === "separates" ? outfit.find((item) => item.category === "top") : null;
  const lower = outfit.find((item) => item.category === "bottom" || item.category === "dress");
  const shoes = outfit.find((item) => item.category === "shoes");
  const [topImg, lowerImg, shoeImg] = await Promise.all([top, lower, shoes].map((item) =>
    item ? prepareGarment(`/${item.image}`, item.category) : null));
  if (request !== layerRequest) return; // the outfit changed while images were loading
  showItemLayer("layer-torso", top, topImg, "torso");
  showItemLayer("layer-legs", lower, lowerImg, lower?.category === "dress" ? "dress" : "legs");
  showItemLayer("layer-feet", shoes, shoeImg, null);
  showItemLayer("layer-feet-left", shoes, shoeImg, null);
}

function renderSlots() {
  const slots = $("try-on-slots");
  slots.innerHTML = "";
  for (const category of categories[mode]) {
    const list = itemsFor(category);
    const item = list[positions[category] || 0];
    const row = document.createElement("div");
    row.className = "try-on-slot";
    row.innerHTML = `
      <span class="try-on-slot-label">${esc(category)}</span>
      <span class="try-on-slot-name">${item ? esc(item.name) : "No items yet"}</span>
      <span class="try-on-slot-controls">
        <button type="button" aria-label="Previous ${esc(category)}" ${list.length < 2 ? "disabled" : ""}>◀</button>
        <button type="button" aria-label="Next ${esc(category)}" ${list.length < 2 ? "disabled" : ""}>▶</button>
      </span>`;
    const [previous, next] = row.querySelectorAll("button");
    previous.onclick = () => step(category, -1);
    next.onclick = () => step(category, 1);
    slots.appendChild(row);
  }
}

function playMismatch() {
  const ctx = prepareTryOnAudio();
  if (!ctx) return;
  const first = ctx.createOscillator();
  const second = ctx.createOscillator();
  const gain = ctx.createGain();
  first.type = "square";
  second.type = "square";
  first.frequency.setValueAtTime(120, ctx.currentTime);
  second.frequency.setValueAtTime(126, ctx.currentTime);
  first.connect(gain);
  second.connect(gain);
  gain.connect(ctx.destination);
  gain.gain.setValueAtTime(0.0001, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.15, ctx.currentTime + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.5);
  first.start();
  second.start();
  first.stop(ctx.currentTime + 0.5);
  second.stop(ctx.currentTime + 0.5);
}

function playMatch() {
  const ctx = prepareTryOnAudio();
  if (!ctx) return;
  const notes = [659.25, 783.99, 987.77];
  const start = ctx.currentTime;
  for (const [index, frequency] of notes.entries()) {
    const oscillator = ctx.createOscillator();
    const modulation = ctx.createOscillator();
    const modulationGain = ctx.createGain();
    const gain = ctx.createGain();
    oscillator.type = "sine";
    modulation.type = "sine";
    oscillator.frequency.setValueAtTime(frequency, start);
    modulation.frequency.setValueAtTime(frequency * 2, start);
    modulationGain.gain.setValueAtTime(frequency / 8, start);
    modulation.connect(modulationGain);
    modulationGain.connect(oscillator.frequency);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    const noteStart = start + index * 0.09;
    gain.gain.setValueAtTime(0.0001, noteStart);
    gain.gain.exponentialRampToValueAtTime(0.12, noteStart + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, noteStart + 0.35);
    oscillator.start(noteStart);
    modulation.start(noteStart);
    oscillator.stop(noteStart + 0.36);
    modulation.stop(noteStart + 0.36);
  }
}

function playFeedbackSound(liked) {
  const ctx = prepareTryOnAudio();
  if (!ctx) return;
  const notes = liked
    ? [[880, 0], [1174.66, 0.09], [1567.98, 0.18]]
    : [[392, 0], [293.66, 0.12], [196, 0.24]];
  const start = ctx.currentTime;
  for (const [frequency, offset] of notes) {
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    const noteStart = start + offset;
    oscillator.type = liked ? "triangle" : "square";
    oscillator.frequency.setValueAtTime(frequency, noteStart);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0.0001, noteStart);
    gain.gain.exponentialRampToValueAtTime(liked ? 0.12 : 0.09, noteStart + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, noteStart + (liked ? 0.34 : 0.16));
    oscillator.start(noteStart);
    oscillator.stop(noteStart + (liked ? 0.35 : 0.17));
  }
}

function flashVerdict(verdict) {
  const stamp = $("try-on-stamp");
  stamp.textContent = verdict === "MATCH" ? "MATCH!" : "MISMATCH";
  stamp.className = `try-on-stamp ${verdict.toLowerCase()}`;
  void stamp.offsetWidth;
  stamp.classList.add("show");
}

function flashReaction(liked) {
  const stamp = $("try-on-stamp");
  const icon = liked
    ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 3h6v2h4V3h6v2h2v7h-2v3h-2v2h-2v2h-2v2h-2v-2h-2v-2H8v-2H6v-3H4z"/></svg>'
    : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3h4v12H3zM9 3h9l3 3v7l-2 3h-3l-3 5-3-1v-5H7V5h2z"/></svg>';
  const label = liked ? "LOVE IT!" : "UGH, AS IF!";
  stamp.innerHTML = `<span class="reaction-icon">${icon}</span><span class="reaction-label">${label}</span>`;
  stamp.className = `try-on-stamp reaction ${liked ? "love" : "dislike"}`;
  void stamp.offsetWidth;
  stamp.classList.add("show");
}

async function scoreOutfit(announceChange = false) {
  const request = ++scoreRequest;
  const outfit = currentOutfit();
  if (!outfit.length) {
    $("try-on-verdict").textContent = "Add clothes";
    $("try-on-verdict").className = "try-on-verdict";
    $("try-on-score").textContent = "";
    $("try-on-reasons").innerHTML = "";
    $("try-on-stamp").className = "try-on-stamp";
    return;
  }
  const result = await api("/api/score", {
    method: "POST",
    body: JSON.stringify({ item_ids: outfit.map((item) => item.id) }),
  });
  if (request !== scoreRequest) return;
  $("try-on-verdict").textContent = result.verdict === "MATCH" ? "MATCH!" : "MISMATCH";
  $("try-on-verdict").className = `try-on-verdict ${result.verdict.toLowerCase()}`;
  $("try-on-score").textContent = `Score ${(result.score * 100).toFixed(0)} / 100`;
  $("try-on-reasons").innerHTML = result.reasons.map((reason) => `<li>${esc(reason)}</li>`).join("");
  if (announceChange) {
    flashVerdict(result.verdict);
    result.verdict === "MATCH" ? playMatch() : playMismatch();
  }
}

function refresh(announceChange = false) {
  clearRender(); // any AI photo on screen shows the previous outfit
  extraIds = [];  // a coat from "Dress me" belongs to that pick only
  renderSlots();
  renderLayers().catch(console.error);
  scoreOutfit(announceChange).catch((error) => {
    $("try-on-status").textContent = `Couldn't score outfit: ${error.message}`;
  });
}

// ---- photoreal try-on (backend: POST /api/try-on/render, see input_pipeline/tryon_render.py) ----
function outfitIds() {
  return [...currentOutfit().map((item) => item.id), ...extraIds];
}

function clearRender() {
  renderToken += 1;
  const img = $("ai-render");
  img.classList.remove("visible");
  img.hidden = true;
  $("ai-badge").hidden = true;
  $("render-overlay").hidden = true;
}

function showRender(url, token, model) {
  const img = $("ai-render");
  const preload = new Image();
  preload.onload = () => {
    if (token !== renderToken) return; // the outfit changed while it loaded
    img.src = url;
    img.hidden = false;
    $("render-overlay").hidden = true;
    $("ai-badge").hidden = false;
    requestAnimationFrame(() => img.classList.add("visible")); // fade in over the doll
    $("try-on-status").textContent = model ? `Photo by ${model.split("/").pop()}.` : "Photo ready.";
  };
  preload.onerror = () => renderFailed(token, "couldn't load the photo");
  preload.src = url;
}

function renderFailed(token, reason) {
  if (token !== renderToken) return;
  $("render-overlay").hidden = true;
  $("try-on-status").textContent = `Photo unavailable (${reason}). Showing the paper doll.`;
}

async function requestRender(note = "") {
  const ids = outfitIds();
  if (!ids.length) return;
  clearRender();
  const token = renderToken;
  $("render-overlay").hidden = false;
  $("try-on-status").textContent = `${note}Dressing the model… (about 25 seconds)`;
  const started = Date.now();
  try {
    let status = await api("/api/try-on/render", {
      method: "POST",
      body: JSON.stringify({ item_ids: ids, person: "avatar" }),
    });
    while (status.status === "pending") {
      if (token !== renderToken) return; // cancelled: the user picked something else
      if (Date.now() - started > RENDER_GIVE_UP_MS) return renderFailed(token, "took too long");
      await new Promise((resolve) => setTimeout(resolve, RENDER_POLL_MS));
      if (token !== renderToken) return;
      status = await api(`/api/try-on/render/${status.key}`);
    }
    if (status.status === "done") showRender(status.url, token, status.model);
    else if (status.status === "off") renderFailed(token, "photo mode is switched off");
    else renderFailed(token, status.reason || "render failed");
  } catch (error) {
    renderFailed(token, error.message);
  }
}

// DRESS ME: a random good match (never the outfit already on screen), then photograph it
async function dressMe() {
  const button = $("try-on-dress-me");
  button.disabled = true;
  try {
    const avoid = outfitIds().join(",");
    // Stay in the mode the user is in: Dress mode always gets a dress
    const pick = await api(`/api/outfit/random?mode=${mode}&avoid=${encodeURIComponent(avoid)}`);
    const chosen = pick.item_ids.map((id) => items.find((item) => item.id === id)).filter(Boolean);
    selectCategory(chosen.some((item) => item.category === "dress") ? "dress" : "top");
    for (const item of chosen) {
      const position = itemsFor(item.category).findIndex((candidate) => candidate.id === item.id);
      if (position >= 0 && item.category in positions) positions[item.category] = position;
    }
    refresh(true);
    // Items with no paper-doll slot (a coat on a cold day) only appear in the photo
    const extras = chosen.filter((item) => !categories[mode].includes(item.category));
    extraIds = extras.map((item) => item.id);
    // Not awaited: Dress me works again straight away (a new pick cancels this render)
    requestRender(extras.length ? `Plus ${extras.map((item) => item.name).join(", ")} for today's weather. ` : "");
  } catch (error) {
    $("try-on-status").textContent = `Couldn't pick an outfit: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function step(category, delta) {
  const count = itemsFor(category).length;
  if (count < 1) return;
  prepareTryOnAudio();
  positions[category] = ((positions[category] || 0) + delta + count) % count;
  $("try-on-status").textContent = "";
  refresh(true);
}

function setAvatar(url) {
  clearRender(); // a photo of the old person no longer applies
  const mannequin = $("mannequin");
  const fallback = 'url("/static/cher-silhouette.svg")';
  if (!url) {
    mannequin.style.backgroundImage = fallback;
    $("reset-avatar").disabled = true;
    return;
  }
  const image = new Image();
  image.onload = () => {
    mannequin.style.backgroundImage = `url("${url}")`;
    $("reset-avatar").disabled = false;
  };
  image.onerror = () => {
    mannequin.style.backgroundImage = fallback;
    $("try-on-status").textContent = "Couldn't load your photo; showing Cher instead.";
  };
  image.src = url;
}

async function loadAvatar() {
  const avatar = await api("/api/avatar");
  setAvatar(avatar.url);
}

async function submitFeedback(liked) {
  const outfit = currentOutfit();
  if (!outfit.length) {
    $("try-on-status").textContent = "Choose at least one item first.";
    return;
  }
  scoreRequest += 1;
  flashReaction(liked);
  playFeedbackSound(liked);
  try {
    await api("/api/feedback", {
      method: "POST",
      body: JSON.stringify({ item_ids: outfit.map((item) => item.id), liked }),
    });
    $("try-on-status").textContent = "Thanks for the feedback!";
    await scoreOutfit();
  } catch (error) {
    $("try-on-status").textContent = `Couldn't save feedback: ${error.message}`;
  }
}

function selectCategory(category) {
  if (category === "dress") {
    mode = "dress";
  } else if (["top", "bottom", "shoes"].includes(category)) {
    mode = "separates";
  } else {
    return false;
  }
  document.querySelectorAll(".try-on-modes button").forEach((button) =>
    button.classList.toggle("active", button.dataset.mode === mode));
  return true;
}

async function init() {
  try {
    [items] = await Promise.all([api("/api/items"), loadAvatar()]);
  } catch (error) {
    $("try-on-status").textContent = `Couldn't load try-on: ${error.message}`;
    return;
  }

  document.querySelectorAll(".try-on-modes button").forEach((button) => {
    button.onclick = () => {
      prepareTryOnAudio();
      mode = button.dataset.mode;
      document.querySelectorAll(".try-on-modes button").forEach((modeButton) =>
        modeButton.classList.toggle("active", modeButton === button));
      $("try-on-status").textContent = "";
      refresh(true);
    };
  });

  $("avatar-file").onchange = async (event) => {
    const [file] = event.target.files;
    if (!file) return;
    $("try-on-status").textContent = "Removing photo background…";
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await api("/api/avatar", { method: "POST", body: form });
      setAvatar(result.url);
      $("try-on-status").textContent = result.warning || "Photo uploaded.";
    } catch (error) {
      $("try-on-status").textContent = `Photo upload failed: ${error.message}`;
    } finally {
      event.target.value = "";
    }
  };

  $("reset-avatar").onclick = async () => {
    try {
      const result = await api("/api/avatar", { method: "DELETE" });
      setAvatar(result.url);
      $("try-on-status").textContent = "Back to Cher.";
    } catch (error) {
      $("try-on-status").textContent = `Couldn't reset photo: ${error.message}`;
    }
  };

  $("clothing-upload").onsubmit = async (event) => {
    event.preventDefault();
    prepareTryOnAudio();
    const form = event.currentTarget;
    const button = $("clothing-upload-button");
    button.disabled = true;
    $("clothing-upload-msg").textContent = "Processing photo…";
    $("clothing-tagchip").textContent = "";
    try {
      const result = await api("/api/items/upload", {
        method: "POST",
        body: new FormData(form),
      });
      items = await api("/api/items");
      const category = result.item.category;
      const categoryItems = itemsFor(category);
      const newPosition = categoryItems.findIndex((item) => item.id === result.item.id);
      if (newPosition >= 0) positions[category] = newPosition;
      const isTryOnCategory = selectCategory(category);
      $("clothing-upload-msg").textContent = isTryOnCategory
        ? `Added "${result.item.name}" as a ${category}.`
        : `Added "${result.item.name}" as a ${category}. This category isn't shown in try-on yet.`;
      const meta = result.tag_meta;
      if (meta) {
        const confidence = (meta.confidence ?? 0).toFixed(2);
        $("clothing-tagchip").textContent =
          `${meta.source} · ${confidence}${meta.needs_review ? "  review" : ""}`;
      }
      form.reset();
      refresh(isTryOnCategory);
    } catch (error) {
      $("clothing-upload-msg").textContent = `Upload failed: ${error.message}`;
    } finally {
      button.disabled = false;
    }
  };

  $("try-on-dress-me").onclick = () => {
    prepareTryOnAudio();
    dressMe();
  };
  $("try-on-render").onclick = () => requestRender();
  $("try-on-like").onclick = () => {
    prepareTryOnAudio();
    submitFeedback(true);
  };
  $("try-on-dislike").onclick = () => {
    prepareTryOnAudio();
    submitFeedback(false);
  };
  $("try-on-status").textContent = "Choose items to try another look.";
  refresh();
}

init();
