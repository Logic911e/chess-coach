// Keyboard map. Pure: imports cleanly in node, no window/document access.
const MAP = {  // key -> [action name, argument]
  ArrowLeft: ["step", -1], ArrowRight: ["step", 1], j: ["nextKey"], k: ["prevKey"], g: ["guess"],
  "/": ["chat"], Escape: ["close"], m: ["mute"], "?": ["help"],
};

/**
 * Returns handle(event) -> whether the key was handled (the caller then calls preventDefault).
 * Keys typed into INPUT/TEXTAREA are ignored except Escape; Cmd/Ctrl combos belong to the browser.
 * An action returning false declines the key (e.g. Escape with nothing open).
 */
export function createKeyHandler(actions) {
  return function handle(event) {
    if (event.metaKey || event.ctrlKey) return false;
    const tag = event.target && event.target.tagName;
    if ((tag === "INPUT" || tag === "TEXTAREA") && event.key !== "Escape") return false;
    const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
    const entry = MAP[key];
    if (!entry || typeof actions[entry[0]] !== "function") return false;
    return actions[entry[0]](...entry.slice(1)) !== false;
  };
}

/** Mute toggle on the sound palette: off remembers what to restore. */
export function toggleMute(current, prev) {
  if (current !== "off") return { palette: "off", prev: current };
  return { palette: prev && prev !== "off" ? prev : "felt", prev };
}
