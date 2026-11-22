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

test("me and meDismissed are validated and can be cleared", () => {
  const s = createSettings(memoryStorage());
  s.set("me", "Ann"); assert.equal(s.get("me", null), "Ann");
  s.set("me", 42); assert.equal(s.get("me", null), "Ann");
  s.set("me", ""); assert.equal(s.get("me", null), "Ann");
  s.set("meDismissed", true); assert.equal(s.get("meDismissed", false), true);
  s.set("meDismissed", "yes"); assert.equal(s.get("meDismissed", false), true);
  s.set("meDismissed", false); assert.equal(s.get("meDismissed", false), false);
  s.set("me", null); assert.equal(s.get("me", "x"), null);
});

test("test_analysis_settings_defaults_and_junk_fallback", () => {
  const s = createSettings(memoryStorage());
  assert.equal(s.get("analysis", true), true);
  assert.equal(s.get("analysisTab", "coach"), "coach");
  s.set("analysis", false);
  s.set("analysisTab", "analysis");
  assert.equal(s.get("analysis", true), false);
  assert.equal(s.get("analysisTab", "coach"), "analysis");
  s.set("analysis", "yes");
  s.set("analysisTab", "bogus");
  assert.equal(s.get("analysis", true), false);
  assert.equal(s.get("analysisTab", "coach"), "analysis");
  const st = memoryStorage();
  st.setItem("chesscoach.analysis", JSON.stringify("junk"));
  st.setItem("chesscoach.analysisTab", JSON.stringify(7));
  const t = createSettings(st);
  assert.equal(t.get("analysis", true), true);
  assert.equal(t.get("analysisTab", "coach"), "coach");
});
