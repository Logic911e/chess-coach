// The stats page: draws what /api/stats returns. Text goes in with textContent only.
import {
  plural, pct, lossText, recordText, levelOf, LEVEL_TEXT, barPercent, resultShares, trendGeometry,
  pickPlayer, storedMe,
} from "./stats-view.js";

const SVG = "http://www.w3.org/2000/svg";
const el = (tag, props = {}, ...kids) => {
  const e = document.createElement(tag);
  Object.assign(e, props);
  kids.forEach((k) => e.append(k));
  return e;
};
const svg = (tag, attrs = {}) => {
  const e = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  return e;
};
async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) { const err = new Error(`${r.status}`); err.status = r.status; throw err; }
  return r.json();
}

function tile(k, v, s) { return el("div", { className: "tile" }, el("div", { className: "k", textContent: k }),
  el("div", { className: "v", textContent: v }), ...(s ? [el("div", { className: "s", textContent: s })] : [])); }

function summary(d) {
  const o = d.overview;
  const classes = Object.entries(d.time_classes).sort((a, b) => b[1] - a[1])
    .map(([k, n]) => el("span", { className: "chip", textContent: `${k} ${n}` }));
  const range = o.first_game && o.last_game ? (o.first_game === o.last_game ? o.first_game : `${o.first_game} to ${o.last_game}`) : "";
  const time = el("div", { className: "tile" }, el("div", { className: "k", textContent: "Time controls" }),
    el("div", { className: "chips" }, ...classes));
  return el("section", { className: "tiles", "aria-label": "Summary" },
    tile("Games", String(o.games), `${recordText(o)}${range ? " · " + range : ""}`),
    tile("Moves analysed", o.moves.toLocaleString(), "your own moves only"),
    tile("Accuracy (estimate)", o.accuracy == null ? "–" : `${o.accuracy}`, "on this app's scale, not Lichess's"),
    tile("Mistakes and blunders", o.errors_per_100 == null ? "–" : String(o.errors_per_100), "per 100 of your moves"), time);
}

function trend(d) {
  const sec = el("section", {}, el("h2", { textContent: "Game by game" }),
    el("p", { className: "sub", textContent: "Estimated accuracy in each game, oldest to newest. The line is the average of the last five games; the dot colour is the result." }));
  const g = trendGeometry(d.trend);
  if (!g) { sec.append(el("p", { className: "muted", textContent: "Needs at least two analysed games." })); return sec; }
  const chart = svg("svg", { viewBox: `0 0 ${g.width} ${g.height}`, class: "chart", role: "img",
    "aria-label": `Accuracy for ${d.trend.length} games, from ${g.lo} to ${g.hi}` });
  for (const v of [g.lo, (g.lo + g.hi) / 2, g.hi]) {
    const y = 14 + ((g.hi - v) * (g.height - 28)) / (g.hi - g.lo);
    chart.append(svg("line", { x1: 40, x2: g.width - 8, y1: y, y2: y, class: "grid" }));
    const t = svg("text", { x: 4, y: y + 4 }); t.textContent = String(Math.round(v)); chart.append(t);
  }
  chart.append(svg("polyline", { points: g.line, class: "avg" }));
  for (const p of g.dots) chart.append(svg("circle", { cx: p.x, cy: p.y, r: 3.5, class: "dot " + p.result }));
  sec.append(chart);
  return sec;
}

function bars(title, sub, rows, overallLoss, unit) {
  const sec = el("section", {}, el("h2", { textContent: title }), el("p", { className: "sub", textContent: sub }));
  const max = Math.max(...rows.map((r) => r.avg_loss || 0));
  const list = el("ul", { className: "rows" });
  for (const r of rows) {
    const level = levelOf(r.ratio, r.small);
    const note = el("div", { className: "note" });
    note.append(el("b", { textContent: lossText(r.avg_loss) }), ` lost per move · ${r.errors_per_100} errors per 100 · ${plural(r.moves, unit)}`);
    const why = LEVEL_TEXT[level];
    if (why) note.append(" · " + why);
    list.append(el("li", { className: `row level-${level}` }, el("span", { className: "name", textContent: r.key }),
      el("div", { className: "track" }, Object.assign(el("div", { className: "fill" }), { style: `width:${barPercent(r.avg_loss, max)}%` })), note));
  }
  sec.append(list);
  return sec;
}

function openings(d) {
  const sec = el("section", {}, el("h2", { textContent: "Openings" }),
    el("p", { className: "sub", textContent: "Your most played openings and how they went. Named from the moves, so a transposition counts as the same opening." }));
  const tabs = el("div", { className: "tabs", role: "tablist" });
  const holder = el("div");
  const draw = (side) => {
    holder.replaceChildren();
    const rows = d.openings[side];
    for (const b of tabs.children) b.setAttribute("aria-selected", String(b.dataset.side === side));
    if (!rows.length) { holder.append(el("p", { className: "muted", textContent: `No games as ${side}.` })); return; }
    const body = el("tbody");
    for (const o of rows) {
      const s = resultShares(o), n = o.wins + o.draws + o.losses;
      const lv = levelOf(o.opening_loss != null && d.overview.avg_loss ? o.opening_loss / d.overview.avg_loss : null, o.small);
      body.append(el("tr", {},
        el("td", {}, el("span", { className: "opening", textContent: o.name }), el("span", { className: "eco", textContent: o.eco || "" }),
          ...(o.small ? [el("span", { className: "few", textContent: "few games" })] : [])),
        el("td", { className: "num", textContent: String(o.games) }),
        el("td", {}, el("div", { className: "stack", role: "img", "aria-label": `${o.wins} wins, ${o.draws} draws, ${o.losses} losses` },
          ...[["w", s.win], ["d", s.draw], ["l", s.loss]].map(([c, w]) => Object.assign(el("i", { className: c }), { style: `width:${w}%` }))),
          el("div", { className: "stack-text", textContent: `${pct(o.wins, n)} win · ${pct(o.draws, n)} draw · ${pct(o.losses, n)} loss` })),
        el("td", { className: "num", textContent: `${lossText(o.opening_loss)}${lv === "good" ? " ✓" : lv === "poor" ? " !" : ""}`, title: LEVEL_TEXT[lv] || "" })));
    }
    holder.append(el("table", {}, el("caption", { className: "muted", textContent: `As ${side}, up to the 10 most played` }),
      el("thead", {}, el("tr", {}, el("th", { textContent: "Opening" }), el("th", { className: "num", textContent: "Games" }),
        el("th", { textContent: "Results" }), el("th", { className: "num", textContent: "Loss in opening" }))), body));
  };
  for (const side of ["white", "black"]) {
    tabs.append(el("button", { type: "button", className: "tab", role: "tab", textContent: `As ${side}`, onclick: () => draw(side) }));
    tabs.lastChild.dataset.side = side;
  }
  sec.append(tabs, holder);
  draw(d.openings.white.length || !d.openings.black.length ? "white" : "black");
  return sec;
}

function legend() {
  const item = (c, t) => Object.assign(el("span", { textContent: t }), { style: `--c:${c}` });
  return el("div", { className: "legend" }, item("var(--lv-good)", "better than your own average"), item("var(--lv-even)", "about your average"),
    item("var(--lv-poor)", "worse than your own average"), item("var(--lv-few)", "too few moves or games to judge"));
}

function render(d) {
  const root = document.getElementById("content");
  const where = bars("Where you lose points", "Average win chance lost on each of your moves, by phase of the game. Compared with your own average, not with other players. Middlegames are harder than openings for everyone, so a low number in the opening is not by itself a strength.",
    d.phases, d.overview.avg_loss, "move");
  const pieces = bars("By piece", "The same measure, by the piece you moved.", d.pieces, d.overview.avg_loss, "move");
  root.replaceChildren(summary(d), trend(d), el("div", { className: "two" }, where, pieces), legend(), openings(d),
    el("p", { className: "foot", textContent: `${d.notes.accuracy}. Everything here is compared with ${d.notes.compared_with}. ${d.unnamed_games ? `${plural(d.unnamed_games, "game")} could not be matched to an opening. ` : ""}Speed, clock use and comparison with other players need clock times and a reference population, which this version does not have.` }));
}

async function load(name) {
  const root = document.getElementById("content");
  root.replaceChildren(el("p", { className: "muted", textContent: "Loading your games…" }));
  try { render(await getJson(`/api/stats?player=${encodeURIComponent(name)}`)); }
  catch (e) {
    root.replaceChildren(el("section", { className: "error", textContent: e.status === 404
      ? `No stored games for ${name}.` : "The stats could not be loaded. Is the server running?" }));
  }
}

async function main() {
  const root = document.getElementById("content");
  let players;
  try { players = await getJson("/api/players"); } catch (e) {
    root.replaceChildren(el("section", { className: "error", textContent: "The stats could not be loaded. Is the server running?" })); return;
  }
  let stored = null;
  try { stored = storedMe(localStorage.getItem("chesscoach.me")); } catch (e) { /* no storage: fine */ }
  const name = pickPlayer({ query: new URLSearchParams(location.search).get("player"), stored, players: players.players, suggested: players.suggested });
  if (!name) { root.replaceChildren(el("p", { className: "muted", textContent: "No games are stored yet. Import some and come back." })); return; }
  const select = document.getElementById("player");
  for (const p of players.players) select.append(el("option", { value: p.name, textContent: `${p.name} (${p.games})`, selected: p.name === name }));
  select.onchange = () => { history.replaceState(null, "", `?player=${encodeURIComponent(select.value)}`); load(select.value); };
  load(name);
}
main();
