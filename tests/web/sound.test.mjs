import { test } from "node:test";
import assert from "node:assert/strict";
import { soundsFor, createPlayer } from "../../src/chess_coach/web/js/sound.js";
import { createSettings } from "../../src/chess_coach/web/js/settings.js";

const mv = (o = {}) => ({ capture: false, check: false, classification: "good", ...o });

function fakeCtx(state = "running") {
  const log = { nodes: 0, starts: 0, freqs: [], kinds: [], master: null, resumes: 0, throwOnStart: false };
  const param = () => ({ value: 0, setValueAtTime(v) { this.set = v; }, exponentialRampToValueAtTime() {} });
  const node = (kind) => () => { log.nodes++; log.kinds.push(kind); const n = { kind, connected: null, gain: param(), frequency: param(), Q: param(),
    threshold: param(), ratio: param(), attack: param(), release: param(), knee: param(),
    connect(d) { n.connected = d; },
    start() { if (log.throwOnStart) throw new Error("boom"); log.starts++; if (kind === "osc") log.freqs.push(n.frequency.set); },
    stop() {}, buffer: null, type: "" }; return n; };
  const ctx = { sampleRate: 8000, currentTime: 0, state, destination: { kind: "dest" },
    resume() { log.resumes++; return Promise.reject(new Error("blocked")); },
    createBuffer: (c, n) => ({ getChannelData: () => new Float32Array(n) }),
    createGain: node("gain"), createOscillator: node("osc"), createBiquadFilter: node("filter"),
    createBufferSource: node("src"), createDynamicsCompressor: node("comp") };
  return { ctx, log };
}
function setup(values = {}, state = "running") {
  const settings = createSettings(undefined);
  for (const [k, v] of Object.entries(values)) settings.set(k, v);
  const made = fakeCtx(state);
  let calls = 0;
  const player = createPlayer({ settings, audioContextFactory: () => { calls++; return made.ctx; } });
  return { player, log: made.log, ctx: made.ctx, calls: () => calls, settings };
}
const firstFreqs = (pal, ev) => { const { player, log } = setup({ soundPalette: pal }); player.unlock(); player.play([ev]); return log.freqs.join(","); };

test("test_sounds_for_capture_with_check_prefers_capture", () => {
  assert.deepEqual(soundsFor(mv({ capture: true, check: true })), ["capture"]);
  assert.deepEqual(soundsFor(mv({ check: true })), ["check"]);
  assert.deepEqual(soundsFor(mv()), ["move"]);
  assert.deepEqual(soundsFor(mv({ classification: "best", capture: true })), ["capture", "best"]);
});

test("test_blunder_label_adds_blunder_sound_only_for_mistake_and_blunder", () => {
  assert.deepEqual(soundsFor(mv({ classification: "blunder" })), ["move", "blunder"]);
  assert.deepEqual(soundsFor(mv({ classification: "mistake" })), ["move", "blunder"]);
  assert.deepEqual(soundsFor(mv({ classification: "inaccuracy" })), ["move"]);
  assert.deepEqual(soundsFor(mv({ classification: "excellent" })), ["move"]);
});

test("test_player_makes_no_audio_before_unlock", () => {
  const { player, log, calls } = setup();
  player.play(["move", "capture"]);
  player.playKeyMoment();
  assert.equal(calls(), 0);
  assert.equal(log.starts, 0);
  player.unlock();
  assert.equal(calls(), 1);
  player.unlock();
  assert.equal(calls(), 1);
  player.play(["move"]);
  assert.ok(log.starts > 0);
});

test("test_both_palettes_play_every_event", () => {
  for (const pal of ["felt", "wood"]) {
    const { player, log, ctx } = setup({ soundPalette: pal });
    player.unlock();
    for (const e of ["move", "capture", "check", "best", "blunder"]) {
      ctx.currentTime += 1;
      const before = log.starts;
      player.play([e]);
      assert.ok(log.starts > before, `${pal} ${e}`);
    }
    ctx.currentTime += 1;
    const before = log.starts;
    player.playKeyMoment();
    assert.ok(log.starts > before);
  }
});

test("test_study_mode_and_off_palette_are_silent", () => {
  for (const v of [{ studyMode: true }, { soundPalette: "off" }]) {
    const { player, log } = setup(v);
    player.unlock();
    player.play(["move", "blunder"]);
    player.playKeyMoment();
    assert.equal(log.starts, 0);
  }
});

test("test_volume_zero_is_silent", () => {
  const { player, log } = setup({ volume: 0 });
  player.unlock();
  player.play(["capture"]);
  player.playKeyMoment();
  assert.equal(log.starts, 0);
});

test("test_unavailable_audio_context_does_not_throw", () => {
  const player = createPlayer({ settings: createSettings(undefined), audioContextFactory: () => { throw new Error("no"); } });
  player.unlock();
  player.play(["move"]);
});

test("test_felt_and_wood_schedule_different_sounds", () => {
  for (const ev of ["move", "capture", "best", "blunder"]) assert.notEqual(firstFreqs("felt", ev), firstFreqs("wood", ev), ev);
  assert.equal(firstFreqs("wood", "move"), "200");
  assert.equal(firstFreqs("felt", "move"), "140");
});

test("test_master_gain_is_volume_times_half_and_invalid_volume_falls_back", () => {
  const find = (s) => { s.player.unlock(); s.player.play(["move"]); return s.log; };
  const t = setup({ volume: 0.4 });
  let masterGain; const og = t.ctx.createGain; const made = [];
  t.ctx.createGain = () => { const n = og(); made.push(n); return n; };
  t.player.unlock(); t.player.play(["move"]);
  masterGain = made[0].gain.value;
  assert.ok(Math.abs(masterGain - 0.2) < 1e-9);
  const d = setup(); d.settings.set("volume", null);
  const made2 = []; const og2 = d.ctx.createGain; d.ctx.createGain = () => { const n = og2(); made2.push(n); return n; };
  d.player.unlock(); d.player.play(["move"]);
  assert.ok(Math.abs(made2[0].gain.value - 0.6 * 0.5) < 1e-9);
  void find;
});

test("test_suspended_context_is_silent_and_resume_rejection_is_swallowed", async () => {
  const { player, log } = setup({}, "suspended");
  player.unlock();
  player.play(["move", "capture"]);
  assert.equal(log.starts, 0);
  assert.ok(log.resumes >= 1);
  await new Promise((r) => setTimeout(r, 5));  // an unhandled rejection would fail the test run
});

test("test_play_within_70ms_is_dropped_and_after_70ms_is_allowed", () => {
  const { player, log, ctx } = setup();
  player.unlock();
  player.play(["move"]);
  const one = log.starts;
  ctx.currentTime = 0.03; player.play(["move"]);
  assert.equal(log.starts, one);
  ctx.currentTime = 0.08; player.play(["move"]);
  assert.ok(log.starts > one);
});

test("test_master_goes_through_a_compressor_to_the_destination", () => {
  const { player, ctx } = setup();
  const nodes = []; for (const m of ["createGain", "createDynamicsCompressor"]) { const o = ctx[m]; ctx[m] = () => { const n = o(); nodes.push(n); return n; }; }
  player.unlock();
  const comp = nodes.find((n) => n.kind === "comp"), gain = nodes.find((n) => n.kind === "gain");
  assert.equal(gain.connected, comp);
  assert.equal(comp.connected, ctx.destination);
});

test("test_web_audio_error_inside_play_is_swallowed", () => {
  const { player, log } = setup();
  player.unlock();
  log.throwOnStart = true;
  player.play(["move"]);
  player.playKeyMoment();
});
