import { test } from "node:test";
import assert from "node:assert/strict";
import { createAnalysis } from "../../src/chess_coach/web/js/analysis.js";
import { analysePosition } from "../../src/chess_coach/web/js/api.js";

const FEN_A = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
const FEN_B = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1";
const OK = (n = 1) => ({ game_over: false, version: "17", depth: 16,
  lines: [{ score: { cp: n * 10, mate: null }, moves: [{ san: "e4" }] }] });
const busyErr = () => Object.assign(new Error("engine busy"), { busy: true });

function fakeTimer() {
  let id = 0; const q = new Map();
  return {
    set(fn, ms) { id += 1; q.set(id, { fn, ms }); return id; },
    clear(h) { q.delete(h); },
    pending: () => q.size,
    lastMs: () => [...q.values()].at(-1)?.ms,
    // run the timers that are due now (one generation), as a real clock would
    tick() { const due = [...q.entries()]; q.clear(); for (const [, t] of due) t.fn(); },
  };
}
function deferred() { let res, rej; const p = new Promise((a, b) => { res = a; rej = b; }); return { p, res, rej }; }
const flush = () => new Promise((r) => setImmediate(r));

function setup(apiImpl) {
  const calls = [], events = [];
  const api = { analysePosition: (fen, o) => { calls.push(fen); return apiImpl(fen, o, calls.length); } };
  const ui = {
    thinking: (f) => events.push(["thinking", f]), loaded: (f, r) => events.push(["loaded", f, r]),
    gameOver: (f, r) => events.push(["gameOver", f, r]), error: (f, m) => events.push(["error", f, m]),
    busyDim: () => events.push(["busyDim"]),
  };
  const timer = fakeTimer();
  const a = createAnalysis({ api, ui, timer });
  const names = () => events.map((e) => e[0]);
  return { a, calls, events, timer, names };
}

test("test_burst_of_requests_sends_only_the_last", async () => {
  const s = setup(async () => OK());
  for (const f of [FEN_A, FEN_B, "x y", FEN_B + "1"]) s.a.request(f, { enabled: true });
  assert.equal(s.calls.length, 0);
  assert.equal(s.timer.pending(), 1);
  assert.equal(s.timer.lastMs(), 250);
  s.timer.tick(); await flush();
  assert.deepEqual(s.calls, [FEN_B + "1"]);
});

test("test_stale_response_is_discarded", async () => {
  const d = deferred();
  const s = setup((fen) => (fen === FEN_A ? d.p : Promise.resolve(OK(2))));
  s.a.request(FEN_A, { enabled: true }); s.timer.tick();
  s.a.request(FEN_B, { enabled: true }); s.timer.tick(); await flush();
  d.res(OK(9)); await flush();
  const loaded = s.events.filter((e) => e[0] === "loaded");
  assert.equal(loaded.length, 1);
  assert.equal(loaded[0][1], FEN_B);
  assert.equal(s.a.peek(FEN_A), null);
});

test("test_cached_fen_makes_no_api_call", async () => {
  const s = setup(async () => OK());
  s.a.request(FEN_A, { enabled: true }); s.timer.tick(); await flush();
  s.a.request(FEN_B, { enabled: true }); s.timer.tick(); await flush();
  assert.equal(s.calls.length, 2);
  s.events.length = 0;
  s.a.request(FEN_A, { enabled: true });
  assert.equal(s.calls.length, 2);
  assert.equal(s.timer.pending(), 0);
  assert.deepEqual(s.names(), ["loaded"]);  // delivered immediately, no thinking flash
  assert.ok(s.a.peek(FEN_A));
});

test("test_same_fen_in_flight_or_loaded_is_a_noop", async () => {
  const d = deferred();
  const s = setup(() => d.p);
  s.a.request(FEN_A, { enabled: true });
  s.a.request(FEN_A, { enabled: true });   // pending in the debounce
  assert.equal(s.timer.pending(), 1);
  s.timer.tick(); await flush();
  s.a.request(FEN_A, { enabled: true });   // in flight
  assert.equal(s.calls.length, 1);
  assert.equal(s.timer.pending(), 0);
  d.res(OK()); await flush();
  const n = s.events.length;
  s.a.request(FEN_A, { enabled: true });   // loaded
  assert.equal(s.events.length, n);
  assert.equal(s.calls.length, 1);
  assert.equal(s.names().filter((x) => x === "thinking").length, 1);
});

test("test_busy_retries_quietly_then_reports_error", async () => {
  const s = setup(async () => { throw busyErr(); });
  s.a.request(FEN_A, { enabled: true }); s.timer.tick(); await flush();
  assert.equal(s.timer.lastMs(), 600);
  s.timer.tick(); await flush();
  s.timer.tick(); await flush();
  assert.equal(s.calls.length, 3);  // first try + 2 retries
  const errs = s.events.filter((e) => e[0] === "error");
  assert.equal(errs.length, 1);
  assert.equal(errs[0][2], "engine busy");
  assert.equal(s.timer.pending(), 0);
  // quiet: no error was reported before the retries ran out
  assert.ok(s.names().indexOf("error") === s.names().length - 1);
  assert.ok(s.names().includes("busyDim"));
});

test("test_busy_then_success_never_reports_an_error", async () => {
  const s = setup(async (f, o, n) => { if (n === 1) throw busyErr(); return OK(); });
  s.a.request(FEN_A, { enabled: true }); s.timer.tick(); await flush();
  s.timer.tick(); await flush();
  assert.ok(!s.names().includes("error"));
  assert.ok(s.names().includes("loaded"));
});

test("test_error_state_offers_retry_and_retry_calls_api_again", async () => {
  const s = setup(async (f, o, n) => { if (n === 1) throw new Error("engine failed"); return OK(); });
  s.a.request(FEN_A, { enabled: true }); s.timer.tick(); await flush();
  assert.deepEqual(s.events.at(-1), ["error", FEN_A, "engine failed"]);
  s.a.request(FEN_A, { enabled: true });  // render() noise must not re-fire
  assert.equal(s.calls.length, 1);
  s.a.retry(); await flush();
  assert.equal(s.calls.length, 2);
  assert.equal(s.events.at(-1)[0], "loaded");
});

test("test_non_busy_error_is_not_retried", async () => {
  const s = setup(async () => { throw new Error("bad fen"); });
  s.a.request(FEN_A, { enabled: true }); s.timer.tick(); await flush();
  assert.equal(s.calls.length, 1);
  assert.equal(s.timer.pending(), 0);
  assert.ok(!s.names().includes("busyDim"));
});

test("test_disabled_or_hidden_makes_zero_api_calls", async () => {
  const s = setup(async () => OK());
  s.a.request(FEN_A, { enabled: false });
  assert.equal(s.timer.pending(), 0);
  s.a.request(FEN_B, { enabled: true });        // pending
  assert.equal(s.timer.pending(), 1);
  s.a.request(FEN_B, { enabled: false });       // now hidden: cancels the pending timer
  assert.equal(s.timer.pending(), 0);
  s.timer.tick(); await flush();
  assert.equal(s.calls.length, 0);
  assert.equal(s.events.length, 1);             // only the earlier thinking
});

test("test_disabled_drops_an_in_flight_response", async () => {
  const d = deferred();
  const s = setup(() => d.p);
  s.a.request(FEN_A, { enabled: true }); s.timer.tick();
  s.a.request(FEN_A, { enabled: false });
  d.res(OK()); await flush();
  assert.ok(!s.names().includes("loaded"));
  assert.equal(s.a.peek(FEN_A), null);
});

test("test_game_over_response_calls_gameOver_not_loaded", async () => {
  const s = setup(async () => ({ game_over: true, result: "checkmate" }));
  s.a.request(FEN_A, { enabled: true }); s.timer.tick(); await flush();
  assert.deepEqual(s.events.at(-1), ["gameOver", FEN_A, "checkmate"]);
  assert.ok(!s.names().includes("loaded"));
  s.events.length = 0;
  s.a.request(FEN_A, { enabled: true });  // noop
  assert.equal(s.events.length, 0);
  s.a.request(FEN_B, { enabled: true }); s.a.request(FEN_A, { enabled: true });  // cached
  assert.equal(s.calls.length, 1);
  assert.equal(s.events.at(-1)[0], "gameOver");
});

test("test_invalidate_drops_in_flight_response", async () => {
  const d = deferred();
  const s = setup(() => d.p);
  s.a.request(FEN_A, { enabled: true }); s.timer.tick();
  s.a.invalidate();
  d.res(OK()); await flush();
  assert.ok(!s.names().includes("loaded"));
  assert.equal(s.a.peek(FEN_A), null);
  // and a pending timer is cancelled too
  s.a.request(FEN_B, { enabled: true });
  s.a.invalidate();
  assert.equal(s.timer.pending(), 0);
  // after invalidate the same FEN may be requested again
  s.a.request(FEN_A, { enabled: true });
  assert.equal(s.timer.pending(), 1);
});

test("analysePosition posts the fen and marks 'engine busy' with busy: true", async () => {
  const real = globalThis.fetch;
  try {
    let seen;
    globalThis.fetch = async (path, opts) => { seen = [path, JSON.parse(opts.body)];
      return { ok: true, json: async () => ({ game_over: true, result: "draw" }) }; };
    await analysePosition(FEN_A);
    assert.equal(seen[0], "/api/analysis");
    assert.deepEqual(seen[1], { fen: FEN_A, depth: 16, lines: 3 });
    const fail = (status, detail) => async () => ({ ok: false, status, statusText: "x", json: async () => ({ detail }) });
    globalThis.fetch = fail(503, "engine busy");
    await assert.rejects(analysePosition(FEN_A), (e) => e.busy === true && e.message === "engine busy");
    globalThis.fetch = fail(503, "Stockfish crashed");
    await assert.rejects(analysePosition(FEN_A), (e) => e.busy !== true && e.message === "Stockfish crashed");
    globalThis.fetch = fail(422, "engine busy");
    await assert.rejects(analysePosition(FEN_A), (e) => e.busy !== true);
  } finally { globalThis.fetch = real; }
});

test("test_throwing_ui_callbacks_leave_the_controller_working", async () => {
  const calls = [], events = [];
  const api = { analysePosition: (f) => { calls.push(f); return Promise.resolve(OK()); } };
  const boom = () => { throw new Error("ui broke"); };
  const ui = { thinking: boom, loaded: boom, gameOver: boom, error: boom, busyDim: boom };
  const timer = fakeTimer();
  const a = createAnalysis({ api, ui, timer });
  const realErr = console.error; console.error = () => {};
  const unhandled = []; const h = (e) => unhandled.push(e); process.on("unhandledRejection", h);
  try {
    a.request(FEN_A, { enabled: true });          // thinking throws: the request must still be scheduled
    assert.equal(timer.pending(), 1);
    timer.tick(); await flush();                  // loaded throws: swallowed
    assert.deepEqual(calls, [FEN_A]);
    assert.ok(a.peek(FEN_A));                     // and the response was still cached
    a.request(FEN_B, { enabled: true }); timer.tick(); await flush();
    assert.deepEqual(calls, [FEN_A, FEN_B]);      // the next request still goes through
    await flush();
    assert.equal(unhandled.length, 0);
  } finally { console.error = realErr; process.off("unhandledRejection", h); }
  void events;
});

test("test_cache_is_capped_at_200_dropping_the_oldest", async () => {
  const s = setup(async () => OK());
  for (let i = 0; i < 205; i++) { s.a.request(`fen ${i}`, { enabled: true }); s.timer.tick(); await flush(); }
  assert.equal(s.calls.length, 205);
  assert.equal(s.a.peek("fen 0"), null);
  assert.equal(s.a.peek("fen 4"), null);
  assert.ok(s.a.peek("fen 5"));
  assert.ok(s.a.peek("fen 204"));
});

test("test_same_fen_after_invalidate_with_old_response_pending_delivers_once", async () => {
  const ds = [deferred(), deferred()];
  const s = setup((f, o, n) => ds[n - 1].p);
  s.a.request(FEN_A, { enabled: true }); s.timer.tick();
  s.a.invalidate();
  s.a.request(FEN_A, { enabled: true }); s.timer.tick();
  assert.equal(s.calls.length, 2);
  ds[0].res(OK(1)); await flush();
  assert.ok(!s.names().includes("loaded"));       // the old one is discarded
  ds[1].res(OK(2)); await flush();
  const loaded = s.events.filter((e) => e[0] === "loaded");
  assert.equal(loaded.length, 1);
  assert.equal(loaded[0][2].lines[0].score.cp, 20);
});
