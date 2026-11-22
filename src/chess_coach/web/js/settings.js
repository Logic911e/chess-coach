// Safe settings store. No window/document access at import time; never throws.
const PREFIX = "chesscoach.";
const THEMES = ["walnut", "slate", "paper"];
const PALETTES = ["felt", "wood", "off"];

function sanitize(key, value) {
  if (key === "theme") return THEMES.includes(value) ? value : undefined;
  if (key === "soundPalette") return PALETTES.includes(value) ? value : undefined;
  if (key === "volume") {
    return typeof value === "number" && Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : undefined;
  }
  if (key === "me") return value === null || (typeof value === "string" && value !== "") ? value : undefined;
  if (key === "meDismissed") return typeof value === "boolean" ? value : undefined;
  if (key === "studyMode") return typeof value === "boolean" ? value : undefined;
  if (key === "analysis") return typeof value === "boolean" ? value : undefined;
  if (key === "analysisTab") return value === "coach" || value === "analysis" ? value : undefined;
  return value;
}

/** Only a theme change needs the board redrawn (arrow colours); sound, mute and study do not. */
export function settingNeedsRender(key) { return key === "theme"; }

export function createSettings(storage) {
  const mem = new Map();
  return {
    get(key, fallback) {
      let v;
      if (mem.has(key)) v = mem.get(key);
      else {
        try {
          const raw = storage && storage.getItem(PREFIX + key);
          if (raw != null) v = JSON.parse(raw);
        } catch (e) { v = undefined; }
      }
      const ok = sanitize(key, v);
      return ok === undefined ? fallback : ok;
    },
    set(key, value) {
      const ok = sanitize(key, value);
      if (ok === undefined) return;
      mem.set(key, ok);
      try { if (storage) storage.setItem(PREFIX + key, JSON.stringify(ok)); } catch (e) { /* in-memory only */ }
    },
  };
}
