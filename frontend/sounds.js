// Retro beeps for the verdict, plus the ♪ on/off switch. The closet page (app.js) plays its own
// sounds and only uses Sound.enabled() from here, so the switch mutes them.
//   Sound.play("mismatch")  harsh square-wave buzz, two slightly detuned oscillators
//   Sound.play("match")     bright four-note arpeggio chime
// A button with id="sound-toggle" on the page turns it on/off (remembered per browser).
//
// Browsers only allow audio after the user has clicked something, so sounds are skipped
// until then (e.g. the score shown when the page first loads is silent).

const Sound = (() => {
  const KEY = "wardrobe-sound";
  let ctx = null; // one AudioContext for the whole page; browsers cap how many can exist
  let on = true;
  try { on = localStorage.getItem(KEY) !== "off"; } catch { /* storage blocked: default on */ }

  function context() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!ctx) ctx = new AC();
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  // One note: oscillator -> gain envelope (quick attack, exponential fade) -> speakers
  function tone(c, type, freq, start, duration, volume) {
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, start);
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(volume, start + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
    osc.connect(gain).connect(c.destination);
    osc.start(start);
    osc.stop(start + duration + 0.02);
  }

  function mismatch(c) {
    const t = c.currentTime;
    tone(c, "square", 120, t, 0.5, 0.18); // 6 Hz apart -> the "wrong answer" wobble
    tone(c, "square", 126, t, 0.5, 0.18);
  }

  function match(c) {
    const t = c.currentTime;
    [1046.5, 1318.5, 1568, 2093].forEach((freq, i) => { // C6 E6 G6 C7
      tone(c, "triangle", freq, t + i * 0.08, 0.35, 0.16);
      tone(c, "sine", freq * 2, t + i * 0.08, 0.2, 0.04); // faint overtone for a bell-ish ring
    });
  }

  function play(kind) {
    if (!on) return;
    if (navigator.userActivation && !navigator.userActivation.hasBeenActive) return; // no click yet
    const c = context();
    if (!c) return;
    (kind === "match" ? match : mismatch)(c);
  }

  function wireToggle() {
    const btn = document.getElementById("sound-toggle");
    if (!btn) return;
    const label = () => {
      btn.textContent = on ? "♪ on" : "♪ off";
      btn.setAttribute("aria-pressed", String(on));
    };
    btn.onclick = () => {
      on = !on;
      try { localStorage.setItem(KEY, on ? "on" : "off"); } catch { /* ignore */ }
      label();
      if (on) play("match"); // a little confirmation blip
    };
    label();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wireToggle);
  else wireToggle();

  return { play, enabled: () => on };
})();
