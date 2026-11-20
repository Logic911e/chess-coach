import { test } from "node:test";
import assert from "node:assert/strict";
import { soundsFor, createPlayer } from "../../src/chess_coach/web/js/sound.js";
import { createSettings } from "../../src/chess_coach/web/js/settings.js";

const mv = (o = {}) => ({ capture: false, check: false, classification: "good", ...o });

function fakeCtx() {
  const log = { nodes: 0, starts: 0 };
  const param = () => ({ value: 0, setValueAtTime() {}, exponentialRampToValueAtTime() {} });
  const node = () => { log.nodes++; return { connect() {}, gain: param(), frequency: param(), Q: param(),
    start() { log.starts++; }, stop() {}, buffer: null, type: "" }; };
  const ctx = { sampleRate: 8000, currentTime: 0, state: "running", destination: {}, resume() {},
    createBuffer: (c, n) => ({ getChannelData: () => new Float32Array(n) }),
    createGain: node, createOscillator: node, createBiquadFilter: node, createBufferSource: node };
  return { ctx, log };
}
function setup(values = {}) {
  const settings = createSettings(undefined);
  for (const [k, v] of Object.entries(values)) settings.set(k, v);
  const made = fakeCtx();
  let calls = 0;
  const player = createPlayer({ settings, audioContextFactory: () => { calls++; return made.ctx; } });
  return { player, log: made.log, calls: () => calls };
}

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
    const { player, log } = setup({ soundPalette: pal });
    player.unlock();
    for (const e of ["move", "capture", "check", "best", "blunder"]) {
      const before = log.starts;
      player.play([e]);
      assert.ok(log.starts > before, `${pal} ${e}`);
    }
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
