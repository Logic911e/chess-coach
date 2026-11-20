// Synthesised sound (Web Audio). Nothing here touches window/document/AudioContext at import time;
// the context is created in unlock() through the injected factory, after a user gesture.
// Recipes ported from docs/superpowers/specs/2026-11-20-immersive-ui-mockups/sound.html
// (Felt = "B", Wood = "A"). The rejected Chime palette is not included.

export const DEFAULT_VOLUME = 0.6;
const MASTER = 0.5;  // the mockup's output level; the volume slider scales it

export function soundsFor(move) {
  const out = [move.capture ? "capture" : move.check ? "check" : "move"];
  if (move.classification === "best") out.push("best");
  if (move.classification === "mistake" || move.classification === "blunder") out.push("blunder");
  return out;
}

// Each recipe is (t, k) with k = { noise, tone } bound to one context.
const PALETTES = {
  wood: {
    move: (t, k) => { k.noise(t, .05, 1100, 2.5, .9); k.tone(t, 200, 110, .07, .35); },
    capture: (t, k) => { k.noise(t, .07, 800, 2, 1.2); k.noise(t + .045, .05, 1200, 2, .7); k.tone(t, 150, 80, .1, .5); },
    check: (t, k) => { k.noise(t, .05, 1100, 2.5, .9); k.tone(t + .09, 880, 880, .18, .18, "triangle"); },
    best: (t, k) => { k.noise(t, .05, 1100, 2.5, .7); k.tone(t + .06, 660, 990, .3, .2, "triangle", .02); },
    blunder: (t, k) => { k.noise(t, .06, 700, 1.5, .8); k.tone(t + .05, 200, 140, .45, .35); },
    key: (t, k) => { k.tone(t, 440, 440, .9, .14, "sine", .25); },
  },
  felt: {
    move: (t, k) => { k.noise(t, .07, 450, 1.2, .8); k.tone(t, 140, 90, .1, .3); },
    capture: (t, k) => { k.noise(t, .09, 380, 1, 1.1); k.tone(t, 110, 65, .14, .45); },
    check: (t, k) => { k.noise(t, .07, 450, 1.2, .7); k.tone(t + .1, 520, 520, .25, .14); },
    best: (t, k) => { k.noise(t, .06, 450, 1.2, .6); k.tone(t + .07, 392, 523, .4, .16, "sine", .04); },
    blunder: (t, k) => { k.noise(t, .08, 330, 1, .8); k.tone(t + .06, 160, 110, .55, .3); },
    key: (t, k) => { k.tone(t, 330, 330, 1.1, .12, "sine", .35); },
  },
};

export function createPlayer({ settings, audioContextFactory }) {
  let ctx = null, master = null, kit = null, failed = false;

  function build() {
    master = ctx.createGain();
    master.connect(ctx.destination);
    kit = {
      noise(t, dur, freq, q, gain) {  // filtered noise burst = "tap"
        const n = Math.floor(ctx.sampleRate * dur), buf = ctx.createBuffer(1, n, ctx.sampleRate), d = buf.getChannelData(0);
        for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 3);
        const s = ctx.createBufferSource(); s.buffer = buf;
        const f = ctx.createBiquadFilter(); f.type = "bandpass"; f.frequency.value = freq; f.Q.value = q;
        const g = ctx.createGain(); g.gain.value = gain;
        s.connect(f); f.connect(g); g.connect(master); s.start(t);
      },
      tone(t, f0, f1, dur, gain, type, attack) {  // pitched tone with exponential decay
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = type || "sine"; o.frequency.setValueAtTime(f0, t);
        if (f1) o.frequency.exponentialRampToValueAtTime(f1, t + dur);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + (attack || 0.005));
        g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        o.connect(g); g.connect(master); o.start(t); o.stop(t + dur + 0.05);
      },
    };
  }

  function unlock() {
    if (ctx || failed) { if (ctx && ctx.state === "suspended" && ctx.resume) ctx.resume(); return; }
    try { ctx = audioContextFactory(); build(); if (ctx.state === "suspended" && ctx.resume) ctx.resume(); }
    catch (e) { ctx = null; failed = true; }
  }

  function volume() {
    const v = settings.get("volume", DEFAULT_VOLUME);
    return typeof v === "number" && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : DEFAULT_VOLUME;
  }

  function run(names) {
    if (!ctx) return;  // nothing plays before the first user gesture
    if (settings.get("studyMode", false)) return;
    const pal = PALETTES[settings.get("soundPalette", "felt")];
    const vol = volume();
    if (!pal || vol <= 0) return;
    master.gain.value = vol * MASTER;
    const t = ctx.currentTime + .02;
    for (const n of names) if (pal[n]) pal[n](t, kit);
  }

  return { unlock, play: (events) => run(events), playKeyMoment: () => run(["key"]) };
}
