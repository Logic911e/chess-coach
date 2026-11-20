import { test } from "node:test";
import assert from "node:assert/strict";
import { createKeyHandler, toggleMute } from "../../src/chess_coach/web/js/keys.js";
import { motionAllowed } from "../../src/chess_coach/web/js/motion.js";

function setup() {
  const calls = [];
  const actions = {
    step: (d) => calls.push(["step", d]), nextKey: () => calls.push(["nextKey"]),
    prevKey: () => calls.push(["prevKey"]), guess: () => calls.push(["guess"]),
    chat: () => calls.push(["chat"]), close: () => calls.push(["close"]),
    mute: () => calls.push(["mute"]), help: () => calls.push(["help"]),
  };
  return { calls, handle: createKeyHandler(actions) };
}
const ev = (key, extra = {}) => ({ key, target: { tagName: "BODY" }, ...extra });

test("test_shortcuts_map_to_actions", () => {
  const { calls, handle } = setup();
  const expected = [
    ["ArrowLeft", ["step", -1]], ["ArrowRight", ["step", 1]], ["j", ["nextKey"]], ["k", ["prevKey"]],
    ["g", ["guess"]], ["/", ["chat"]], ["Escape", ["close"]], ["m", ["mute"]], ["?", ["help"]],
  ];
  for (const [key, call] of expected) {
    calls.length = 0;
    assert.equal(handle(ev(key)), true, key);
    assert.deepEqual(calls, [call], key);
  }
  calls.length = 0;
  assert.equal(handle(ev("J")), true);  // caps lock
  assert.deepEqual(calls, [["nextKey"]]);
  assert.equal(handle(ev("x")), false);
  assert.equal(calls.length, 1);
});

test("test_ignores_keys_typed_into_inputs", () => {
  const { calls, handle } = setup();
  for (const tagName of ["INPUT", "TEXTAREA"]) {
    for (const key of ["j", "k", "g", "m", "/", "?", "ArrowLeft", "ArrowRight"]) {
      assert.equal(handle({ key, target: { tagName } }), false, tagName + key);
    }
  }
  assert.deepEqual(calls, []);
  assert.equal(handle({ key: "Escape", target: { tagName: "INPUT" } }), true);
  assert.deepEqual(calls, [["close"]]);
});

test("test_ignores_modified_keys", () => {
  const { calls, handle } = setup();
  assert.equal(handle(ev("j", { metaKey: true })), false);
  assert.equal(handle(ev("j", { ctrlKey: true })), false);
  assert.equal(handle(ev("ArrowLeft", { metaKey: true })), false);
  assert.deepEqual(calls, []);
});

test("test_close_can_decline_the_key", () => {
  const h = createKeyHandler({ close: () => false });
  assert.equal(h(ev("Escape")), false);
  assert.equal(createKeyHandler({})(ev("j")), false);  // missing action: not handled
});

test("test_toggle_mute_restores_previous_palette", () => {
  assert.deepEqual(toggleMute("wood", undefined), { palette: "off", prev: "wood" });
  assert.deepEqual(toggleMute("off", "wood"), { palette: "wood", prev: "wood" });
  assert.deepEqual(toggleMute("off", undefined), { palette: "felt", prev: undefined });
  assert.equal(toggleMute("off", "off").palette, "felt");
});

test("test_motion_allowed_is_false_in_study_mode_or_reduced_motion", () => {
  assert.equal(motionAllowed({ study: false, reduced: false }), true);
  assert.equal(motionAllowed({ study: true, reduced: false }), false);
  assert.equal(motionAllowed({ study: false, reduced: true }), false);
  assert.equal(motionAllowed({ study: true, reduced: true }), false);
});
