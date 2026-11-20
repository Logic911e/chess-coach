// Who "me" is. Pure: imports cleanly in node, no window/document access.

/**
 * The stored name wins if it is among the players; else the suggested name (also must be a player);
 * else the page must ask, once: a dismissed prompt is not shown again on load. With no players at all there is nobody to choose, so never ask.
 */
export function resolveMe({ stored, players, suggested, dismissed = false }) {
  const names = (players || []).map((p) => p.name);
  if (!names.length) return { me: null, needsPrompt: false };
  if (stored && names.includes(stored)) return { me: stored, needsPrompt: false };
  if (suggested && names.includes(suggested)) return { me: suggested, needsPrompt: false };
  return { me: null, needsPrompt: !dismissed };
}
