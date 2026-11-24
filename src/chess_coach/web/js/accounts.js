// Linked accounts panel on the stats page: link, sync and unlink. Text goes in with textContent.
const el = (tag, props = {}, ...kids) => {
  const e = document.createElement(tag);
  Object.assign(e, props);
  kids.forEach((k) => e.append(k));
  return e;
};
const SITE = { chesscom: "Chess.com", lichess: "Lichess" };

async function call(url, method = "GET", body) {
  const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${r.status})`);
  return data;
}

export function syncText(s) {
  if (s.state === "fetching") return "Fetching games…";
  if (s.state === "analysing") return `Analysing ${s.done} of ${s.total}`;
  if (s.state === "error") return `Sync failed: ${s.message}`;
  if (s.state === "cancelled") return "Sync stopped.";
  if (s.state === "done") return `Synced: ${s.imported} new${s.message ? ", " + s.message : ""}.`;
  return "";
}
const active = (a) => a.sync.state === "fetching" || a.sync.state === "analysing";

export function mountAccounts(host, onChange) {
  let accounts = [], confirming = null, error = "", timer = null;

  async function refresh() {
    try { accounts = await call("/api/accounts"); } catch (e) { error = e.message; }
    draw();
    clearTimeout(timer);
    if (accounts.some(active)) timer = setTimeout(refresh, 3000);
    else if (wasActive) { wasActive = false; onChange(); }
    if (accounts.some(active)) wasActive = true;
  }
  let wasActive = false;

  async function act(fn) {
    error = "";
    try { await fn(); } catch (e) { error = e.message; }
    confirming = null;
    await refresh();
  }

  function row(a) {
    const when = a.last_synced_at ? `last synced ${a.last_synced_at.slice(0, 10)}` : "not synced yet";
    const head = el("div", { className: "acct-head" },
      el("strong", { textContent: a.username }), el("span", { className: "chip", textContent: SITE[a.platform] }),
      el("span", { className: "muted", textContent: `${a.games} games · ${when}` }));
    const status = el("p", { className: "muted acct-status", textContent: syncText(a.sync) });
    const buttons = el("div", { className: "acct-actions" });
    if (confirming === a.id) {
      buttons.append(
        el("span", { className: "muted", textContent: `Unlink ${a.username}? ` }),
        el("button", { textContent: "Unlink, keep games", onclick: () => act(() => call(`/api/accounts/${a.id}`, "DELETE")) }),
        el("button", { className: "danger", textContent: `Unlink and delete ${a.games} games`, onclick: () => act(() => call(`/api/accounts/${a.id}?delete_games=true`, "DELETE")).then(onChange) }),
        el("button", { textContent: "Cancel", onclick: () => { confirming = null; draw(); } }));
    } else {
      buttons.append(
        el("button", { textContent: "Sync now", disabled: accounts.some(active), onclick: () => act(() => call(`/api/accounts/${a.id}/sync`, "POST")) }),
        el("button", { textContent: "Unlink account", onclick: () => { confirming = a.id; draw(); } }));
    }
    return el("li", { className: "acct" }, head, status, buttons);
  }

  function form() {
    const platform = el("select", { ariaLabel: "Site" }, el("option", { value: "chesscom", textContent: "Chess.com" }), el("option", { value: "lichess", textContent: "Lichess" }));
    const name = el("input", { type: "text", placeholder: "username", ariaLabel: "Username", maxLength: 30, autocomplete: "off", spellcheck: false });
    const months = el("select", { ariaLabel: "How far back" }, ...[[1, "last month"], [3, "last 3 months"], [12, "last 12 months"]].map(([v, t]) => el("option", { value: v, textContent: t, selected: v === 3 })));
    const go = el("button", { type: "submit", textContent: "Link and import" });
    const f = el("form", { className: "acct-form" }, platform, name, months, go);
    f.onsubmit = (ev) => {
      ev.preventDefault();
      if (!name.value.trim()) return;
      go.disabled = true;
      act(() => call("/api/accounts", "POST", { platform: platform.value, username: name.value.trim(), months: Number(months.value) }));
    };
    return f;
  }

  function draw() {
    host.replaceChildren(
      el("h2", { textContent: "Linked accounts" }),
      el("p", { className: "sub", textContent: "Link a Chess.com or Lichess account to import your recent games. Only the username is sent, to that site's public API; no password or token is needed or stored. Each game is analysed on this computer, which takes a while. Unlinking can keep or delete the games it brought in." }),
      ...(accounts.length ? [el("ul", { className: "accts" }, ...accounts.map(row))] : []),
      form(),
      ...(error ? [el("p", { className: "acct-error", role: "alert", textContent: error })] : []));
  }

  draw();
  refresh();
}
