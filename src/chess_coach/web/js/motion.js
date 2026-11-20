// The one predicate that gates all motion: piece slides, arrows drawing in, the drawer slide.
// Imports cleanly in node; the browser state is read lazily, and tests inject it.
function browserEnv() {
  if (typeof document === "undefined") return { study: false, reduced: false };
  const mq = typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  return { study: document.documentElement.dataset.study === "on", reduced: !!(mq && mq.matches) };
}

/** False when study mode is on or the user prefers reduced motion. */
export function motionAllowed(env = browserEnv()) {
  return !env.study && !env.reduced;
}
