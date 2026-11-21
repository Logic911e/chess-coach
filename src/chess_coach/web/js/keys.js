// Keyboard map. Pure: imports cleanly in node, no window/document access.
const TOGGLES = ["m", "?", "a"];
const PALETTES = ["felt", "wood"];
const MAP = {  // key -> [action name, argument]
  ArrowLeft: ["step", -1], ArrowRight: ["step", 1], j: ["nextKey"], k: ["prevKey"], g: ["guess"],
  "/": ["chat"], Escape: ["close"], m: ["mute"], "?": ["help"], a: ["analysis"],
};

/**
 * Returns handle(event) -> whether the key was handled (the caller then calls preventDefault).
 * Keys typed into INPUT/TEXTAREA are ignored except Escape; Cmd/Ctrl combos belong to the browser.
 * An action returning false declines the key (e.g. Escape with nothing open).
 */
export function createKeyHandler(actions) {
  return function handle(event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return false;  // browser shortcuts (Alt+Left is Back)
    const t = event.target;
    const tag = t && t.tagName;
    const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || !!(t && t.isContentEditable);
    if (typing && event.key !== "Escape") return false;
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    if (event.repeat && TOGGLES.includes(key)) return false;  // holding m or ? must not flicker
    const entry = MAP[key];
    if (!entry || typeof actions[entry[0]] !== "function") return false;
    return actions[entry[0]](...entry.slice(1)) !== false;
  };
}

/** Mute toggle on the sound palette: off remembers what to restore. */
export function toggleMute(current, prev) {
  if (current !== "off") return { palette: "off", prev: current };
  return { palette: PALETTES.includes(prev) ? prev : "felt", prev };
}
