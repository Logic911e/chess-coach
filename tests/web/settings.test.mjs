import { test } from "node:test";
import assert from "node:assert/strict";
import { createSettings } from "../../src/chess_coach/web/js/settings.js";

function memoryStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
  };
}

test("test_works_when_storage_throws", () => {
  const boom = () => { throw new Error("denied"); };
  const s = createSettings({ getItem: boom, setItem: boom });
  assert.equal(s.get("volume", 0.5), 0.5);
  s.set("volume", 0.8);
  assert.equal(s.get("volume", 0.5), 0.8);
});

test("works with no storage at all", () => {
  const s = createSettings(undefined);
  s.set("me", "alice");
  assert.equal(s.get("me", ""), "alice");
});

test("test_roundtrip_with_storage", () => {
  const st = memoryStorage();
  createSettings(st).set("studyMode", true);
  createSettings(st).set("theme", "slate");
  const again = createSettings(st);
  assert.equal(again.get("studyMode", false), true);
  assert.equal(again.get("theme", "walnut"), "slate");
});

test("test_rejects_unknown_theme_value_falls_back_to_walnut", () => {
  const st = memoryStorage();
  st.setItem("theme", JSON.stringify("neon"));
  const s = createSettings(st);
  assert.equal(s.get("theme", "walnut"), "walnut");
  s.set("theme", "neon");
  assert.equal(s.get("theme", "walnut"), "walnut");
});

test("rejects bad soundPalette and clamps volume", () => {
  const s = createSettings(undefined);
  s.set("soundPalette", "chime");
  assert.equal(s.get("soundPalette", "felt"), "felt");
  s.set("volume", 7);
  assert.equal(s.get("volume", 0.5), 1);
});
