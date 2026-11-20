// Thin fetch wrappers. Every failure throws an Error carrying the server's `detail`.
async function call(path, opts) {
  let r;
  try { r = await fetch(path, opts); }
  catch (e) { throw new Error("Cannot reach the server: " + e.message); }
  if (!r.ok) {
    let msg = r.statusText || "request failed";
    try {
      const d = (await r.json()).detail;
      if (typeof d === "string") msg = d;
      else if (Array.isArray(d) && d.length) msg = d.map((x) => x.msg || String(x)).join("; ");
    } catch (_) { /* keep statusText */ }
    throw new Error(msg);
  }
  return r.json();
}
const post = (path, body) => call(path, {
  method: "POST",
  headers: body === undefined ? {} : { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const getGames = () => call("/api/games");
export const getGame = (id) => call(`/api/games/${id}`);
export const getPlayers = () => call("/api/players");
export const explainMove = (id, regenerate = false) => post(`/api/moves/${id}/explain?regenerate=${regenerate ? "true" : "false"}`);
export const guessMove = (id, uci) => post(`/api/moves/${id}/guess`, { uci });
export const chatMove = (id, question, history = []) => post(`/api/moves/${id}/chat`, { question, history });
